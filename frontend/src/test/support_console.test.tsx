/**
 * The operator console — what it must never let an operator believe.
 *
 * Approved from the flow-prototype review surface (MASTER_OUTSTANDING §A7).
 * These tests carry the three approved rules into production, because a
 * prototype proves interaction intent and nothing else.
 *
 *  1. **A queue that stopped updating must not look like a quiet queue.**
 *     The prototype's live pill is not decoration: when the socket drops or
 *     the server refuses the privileged channel, the page says which source is
 *     feeding it. This is the D6 rule — a surface that renders its status from
 *     a constant makes a degraded system look healthy.
 *
 *  2. **A ticket held by someone else is never actionable here.** The server
 *     refuses a second claim with 409 and names the holder; the console must
 *     not offer a button the server would refuse, and must show who has it.
 *
 *  3. **An escalated ticket carries its reason.** The floor's own words travel
 *     to the operator taking over, because "needs a human" without the reason
 *     is not something you can act on at 3am.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

const queueRows = [
  {
    id: 't-8841', user_id: 'cust-1', subject: 'Withdrawal has not arrived',
    status: 'awaiting_operator', category: 'account_or_money', department: null,
    needs_human: true, assigned_operator_id: null,
    escalation_reason: 'Anything that moves money or changes an account is a human action here.',
    matched_on: 'withdraw', created_at: '2026-09-10T04:00:00Z',
    updated_at: '2026-09-10T04:00:00Z', first_response_at: null, resolved_at: null,
  },
  {
    id: 't-8836', user_id: 'cust-2', subject: 'Order rejected',
    status: 'with_operator', category: 'orders_or_execution', department: 'markets_execution',
    needs_human: true, assigned_operator_id: 'ops-ren',
    escalation_reason: 'The support AI is unavailable (NoProviderAvailable).',
    matched_on: null, created_at: '2026-09-10T03:00:00Z',
    updated_at: '2026-09-10T03:00:00Z', first_response_at: null, resolved_at: null,
  },
];

const supportApi = {
  queue:   vi.fn(),
  thread:  vi.fn(),
  claim:   vi.fn(),
  release: vi.fn(),
  reply:   vi.fn(),
  resolve: vi.fn(),
};

let liveState = { source: 'live' as 'live' | 'poll' | 'refused', lastEventAt: Date.now() };

vi.mock('../hooks/useApi', () => ({ supportApi }));
vi.mock('../hooks/useSupportQueue', () => ({
  useSupportQueue: () => liveState,
}));

async function mount() {
  const { default: SupportConsole } = await import('../pages/SupportConsole');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><SupportConsole /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  liveState = { source: 'live', lastEventAt: Date.now() };
  supportApi.queue.mockResolvedValue({ data: { tickets: queueRows, count: 2 } });
  supportApi.thread.mockResolvedValue({
    data: {
      ticket: queueRows[0],
      messages: [{ author_kind: 'customer', author_id: 'cust-1', body: 'Where is my money?', created_at: '2026-09-10T04:00:00Z' }],
    },
  });
});

describe('a queue that stopped updating never looks like a quiet queue', () => {
  it('says the live channel is feeding it', async () => {
    await mount();
    expect(await screen.findByTestId('live-source')).toHaveTextContent(/live/i);
  });

  it('says so when it has fallen back to polling', async () => {
    liveState = { source: 'poll', lastEventAt: Date.now() - 47_000 };
    await mount();
    const pill = await screen.findByTestId('live-source');
    expect(pill.textContent).toMatch(/poll/i);
    expect(pill.textContent).not.toMatch(/^live$/i);
  });

  it('says so when the server refused the channel for this role', async () => {
    liveState = { source: 'refused', lastEventAt: 0 };
    await mount();
    expect(await screen.findByTestId('live-source')).toHaveTextContent(/refus/i);
  });

  it('an empty queue reads as finished work, not as a blank', async () => {
    supportApi.queue.mockResolvedValue({ data: { tickets: [], count: 0 } });
    await mount();
    expect(await screen.findByTestId('queue-empty')).toBeTruthy();
  });

  it('a failed queue request says so rather than rendering an empty queue', async () => {
    supportApi.queue.mockRejectedValue(new Error('network down'));
    await mount();
    expect(await screen.findByTestId('queue-error')).toBeTruthy();
    expect(screen.queryByTestId('queue-empty')).toBeNull();
  });
});

describe('a ticket held by someone else is never actionable here', () => {
  it('names the holder', async () => {
    await mount();
    expect(await screen.findByText(/ops-ren/)).toBeTruthy();
  });

  it('offers no claim button for it — the server would refuse', async () => {
    supportApi.thread.mockResolvedValue({ data: { ticket: queueRows[1], messages: [] } });
    await mount();
    fireEvent.click(await screen.findByTestId('row-t-8836'));
    await waitFor(() => expect(screen.getByTestId('thread-subject')).toHaveTextContent('Order rejected'));
    const claim = screen.queryByTestId('act-claim');
    expect(claim === null || (claim as HTMLButtonElement).disabled).toBe(true);
  });

  it('a lost claim reports the holder instead of failing silently', async () => {
    supportApi.claim.mockRejectedValue({
      response: { status: 409, data: { detail: "Ticket 't-8841' is already held by 'ops-ren'." } },
    });
    await mount();
    fireEvent.click(await screen.findByTestId('row-t-8841'));
    fireEvent.click(await screen.findByTestId('act-claim'));
    const banner = await screen.findByTestId('action-error');
    expect(banner.textContent).toMatch(/ops-ren/);
  });
});

describe('an escalated ticket carries the reason the floor gave', () => {
  it('shows it on the queue row', async () => {
    await mount();
    expect(await screen.findByText(/moves money or changes an account/)).toBeTruthy();
  });

  it('shows the AI-unavailable reason too — it is not the same as the floor', async () => {
    await mount();
    expect(await screen.findByText(/support AI is unavailable/)).toBeTruthy();
  });
});

describe('the composer cannot send what the server would refuse', () => {
  it('is disabled until the ticket is held by this operator', async () => {
    await mount();
    fireEvent.click(await screen.findByTestId('row-t-8841'));
    const box = await screen.findByTestId('reply-box');
    expect((box as HTMLTextAreaElement).disabled).toBe(true);
  });

  it('refuses an empty reply before it reaches the server', async () => {
    supportApi.thread.mockResolvedValue({
      data: { ticket: { ...queueRows[0], assigned_operator_id: 'me', status: 'with_operator' }, messages: [] },
    });
    await mount();
    fireEvent.click(await screen.findByTestId('row-t-8841'));
    const send = await screen.findByTestId('act-send');
    fireEvent.click(send);
    await waitFor(() => expect(supportApi.reply).not.toHaveBeenCalled());
  });
});
