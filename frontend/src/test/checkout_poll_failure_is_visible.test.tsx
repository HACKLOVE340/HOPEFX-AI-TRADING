/**
 * The crypto checkout must not claim to be polling while every poll is failing.
 *
 * `CryptoCheckout` handles its errors well almost everywhere: the deposit-address
 * call surfaces through `setAddressError`, the Flutterwave init surfaces through
 * an alert, and an expired or failed payment stops the timer and explains why.
 * One place did not — the status poll:
 *
 *     } catch {
 *       // Non-fatal — keep polling
 *     }
 *
 * Continuing to poll through a transient failure is right. Doing it silently is
 * not, because the confirming screen states two things it cannot know while the
 * endpoint is unreachable: the confirmation count ("0 / 3"), and the sentence
 * "This page polls automatically every 15 seconds". A customer who has already
 * sent funds sees a page that looks like it is watching for their money when it
 * has lost contact with the server entirely.
 *
 * This is the same defect class as F1-01 (a page rendering identically whether
 * its data arrived or not), so it takes the same remedy the audit already built:
 * `useDataFreshness` to record it and `<StaleDataNotice>` to show it.
 *
 * These tests pin the behaviour, not the implementation: after a run of
 * consecutive failures the page says so, one failure does not cry wolf, the
 * timer keeps running throughout, and recovery clears the notice.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
}));

vi.mock('../hooks/useApi', () => ({
  api: {
    get: mockApiGet,
    post: mockApiPost,
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    defaults: { baseURL: '/api', timeout: 15000, headers: {} },
    interceptors: {
      request: { handlers: [{}], use: vi.fn() },
      response: { handlers: [{}], use: vi.fn() },
    },
  },
}));

vi.mock('../hooks/usePlan', () => ({
  useRefreshPlan: () => vi.fn().mockResolvedValue(undefined),
  usePlan: () => ({ plan: 'free', loading: false }),
}));

import CryptoCheckout, { POLL_INTERVAL_MS } from '../pages/CryptoCheckout';

const PLAN = { id: 'pro', name: 'Pro', price_usd_monthly: 99, features: ['everything'] };

const ADDRESS = {
  payment_id: 'pay_1',
  address: 'bc1qexampleaddressonlyfortests',
  amount_crypto: 0.0011,
  currency: 'BTC',
  network: 'bitcoin',
  confirmations_required: 3,
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
};

/** Route every GET this page makes; the status endpoint is the one under test. */
function routeGets(statusImpl: () => Promise<unknown>) {
  mockApiGet.mockImplementation((url: string) => {
    if (url.startsWith('/payments/crypto/status/')) return statusImpl();
    if (url === '/payments/crypto/rates') return Promise.resolve({ data: { BTC: 90000 } });
    if (url === '/billing/payments/flutterwave/status') return Promise.resolve({ data: { enabled: false } });
    if (url === '/billing/plans') return Promise.resolve({ data: { plans: [PLAN] } });
    return Promise.resolve({ data: {} });
  });
}

/**
 * Drive the page through the real flow to the confirming step, where the poll
 * runs. Rendering alone leaves it on 'select' and the poll never starts — a
 * harness that skips these clicks asserts against a page that is not polling.
 */
async function reachConfirming() {
  mockApiPost.mockResolvedValue({ data: ADDRESS });
  render(
    <MemoryRouter initialEntries={['/checkout?plan=pro']}>
      <CryptoCheckout />
    </MemoryRouter>,
  );
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });

  const pay = screen.getByRole('button', { name: /Pay with/i });
  await act(async () => { fireEvent.click(pay); await Promise.resolve(); await Promise.resolve(); });

  const sent = screen.getByRole('button', { name: /sent the payment/i });
  await act(async () => { fireEvent.click(sent); await Promise.resolve(); });

  // Prove the harness is live before anything asserts on what it shows.
  expect(screen.getByText(/Waiting for blockchain confirmations/i)).toBeTruthy();
}

async function tickPolls(n: number) {
  for (let i = 0; i < n; i++) {
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
      await Promise.resolve();
      await Promise.resolve();
    });
  }
}

describe('CryptoCheckout — a failing status poll is visible', () => {
  beforeEach(() => {
    // shouldAdvanceTime lets testing-library's waitFor/findBy* still resolve;
    // plain fake timers deadlock them, because waitFor polls on a timer too.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApiGet.mockReset();
    mockApiPost.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('exports the poll interval so a test can advance real time by it', () => {
    // Pinning this makes the rest of the suite honest: a test that guesses the
    // interval passes for the wrong reason when the interval changes.
    expect(typeof POLL_INTERVAL_MS).toBe('number');
    expect(POLL_INTERVAL_MS).toBeGreaterThan(0);
  });

  it('says the status could not be read after a run of failures', async () => {
    routeGets(() => Promise.reject(new Error('ECONNREFUSED')));
    await reachConfirming();
    await tickPolls(4);

    // The page must not look identical to the healthy case.
    const notice = screen.queryByRole('status');
    expect(notice, 'a run of failed status polls must produce a visible notice').not.toBeNull();
    expect(notice!.textContent).toMatch(/payment status|not live|out of date/i);
  });

  it('does not cry wolf on a single failed poll', async () => {
    let calls = 0;
    routeGets(() => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new Error('blip'))
        : Promise.resolve({ data: { status: 'confirming', confirmations: 1 } });
    });
    await reachConfirming();
    await tickPolls(2);

    expect(screen.queryByRole('status'), 'one transient blip is not a degraded state').toBeNull();
  });

  it('keeps polling while degraded — a lost connection must not stop the watch', async () => {
    routeGets(() => Promise.reject(new Error('down')));
    await reachConfirming();
    await tickPolls(5);

    const statusCalls = mockApiGet.mock.calls.filter(
      (call) => typeof call[0] === 'string' && call[0].startsWith('/payments/crypto/status/'),
    );
    expect(statusCalls.length).toBeGreaterThanOrEqual(5);
  });

  it('clears the notice when the endpoint comes back', async () => {
    let failing = true;
    routeGets(() =>
      failing
        ? Promise.reject(new Error('down'))
        : Promise.resolve({ data: { status: 'confirming', confirmations: 2 } }),
    );
    await reachConfirming();
    await tickPolls(4);
    expect(screen.queryByRole('status')).not.toBeNull();

    failing = false;
    await tickPolls(1);
    expect(screen.queryByRole('status'), 'recovery must clear the notice').toBeNull();
  });
});
