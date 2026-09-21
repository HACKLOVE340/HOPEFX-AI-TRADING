/**
 * F2-02 — one resolver slot for a dialog that can be asked twice.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F2: *"can it double-submit?"*
 *
 * `ConfirmDialog.tsx:72`
 *
 *     const confirm = useCallback((opts) => {
 *       setState({ open: true, opts });
 *       return new Promise<boolean>(resolve => { resolverRef.current = resolve; });
 *     }, []);
 *
 * `resolverRef` is a single slot. A second `confirm()` overwrites the first
 * resolver, and the first promise is then **never settled** — not resolved
 * false, not rejected. Every caller of this hook awaits it:
 *
 *     const ok = await confirm({ … });
 *     if (!ok) return;
 *     setSubmitting(true);          ← OrderEntryForm.tsx:328
 *
 * so the orphaned caller is suspended forever, before it ever sets its busy
 * flag. Its `finally` never runs. A form whose submit button is disabled while
 * a confirmation is pending stays disabled for the life of the page, and the
 * user's only recovery is a reload.
 *
 * It does not fire two orders — the surviving resolver belongs to the second
 * call, so exactly one action proceeds. But which one proceeds is the *second*
 * request while the dialog may be describing the first, and a promise that
 * never settles is not a design, it is an omission.
 *
 * A single-slot resolver is the same shape as every other defect in this
 * codebase: it works for the case someone had in mind and fails silently
 * outside it. The fix settles the displaced promise `false` — refusing is
 * always the safe answer for a confirmation nobody is looking at any more.
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ConfirmDialogProvider, useConfirm } from '../components/ConfirmDialog';

/** Exposes `confirm` so a test can call it directly, twice, without a form. */
const Harness: React.FC<{ onReady: (c: ReturnType<typeof useConfirm>) => void }> = ({ onReady }) => {
  const confirm = useConfirm();
  React.useEffect(() => { onReady(confirm); }, [confirm, onReady]);
  return null;
};

const mount = () => {
  let confirmFn: ReturnType<typeof useConfirm> = async () => false;
  render(
    <ConfirmDialogProvider>
      <Harness onReady={(c) => { confirmFn = c; }} />
    </ConfirmDialogProvider>,
  );
  return () => confirmFn;
};

describe('useConfirm — overlapping calls (F2-02)', () => {
  it('resolves a single confirmation normally', async () => {
    const getConfirm = mount();
    let result: boolean | undefined;
    act(() => { void getConfirm()({ title: 'First?' }).then((r) => { result = r; }); });

    await screen.findByText('First?');
    await userEvent.click(screen.getByRole('button', { name: /confirm|yes|ok/i }));
    await waitFor(() => expect(result).toBe(true));
  });

  it('settles a displaced confirmation instead of abandoning it', async () => {
    const getConfirm = mount();
    const settled: string[] = [];

    act(() => {
      void getConfirm()({ title: 'First?' }).then(() => settled.push('first'));
    });
    await screen.findByText('First?');

    act(() => {
      void getConfirm()({ title: 'Second?' }).then(() => settled.push('second'));
    });
    await screen.findByText('Second?');

    // The first promise must settle. Left unsettled, its caller — a submit
    // handler — is suspended forever with its busy flag never cleared.
    await waitFor(() => expect(settled).toContain('first'));
  });

  it('settles the displaced confirmation as a refusal', async () => {
    const getConfirm = mount();
    let first: boolean | undefined;

    act(() => { void getConfirm()({ title: 'First?' }).then((r) => { first = r; }); });
    await screen.findByText('First?');
    act(() => { void getConfirm()({ title: 'Second?' }); });
    await screen.findByText('Second?');

    // Nobody is looking at the first dialog any more. The only safe answer to a
    // confirmation nobody saw is no.
    await waitFor(() => expect(first).toBe(false));
  });

  it('confirming the second does not also confirm the first', async () => {
    const getConfirm = mount();
    let first: boolean | undefined;
    let second: boolean | undefined;

    act(() => { void getConfirm()({ title: 'First?' }).then((r) => { first = r; }); });
    await screen.findByText('First?');
    act(() => { void getConfirm()({ title: 'Second?' }).then((r) => { second = r; }); });
    await screen.findByText('Second?');

    await userEvent.click(screen.getByRole('button', { name: /confirm|yes|ok/i }));

    await waitFor(() => expect(second).toBe(true));
    expect(first, 'one click approved two different actions').toBe(false);
  });
});

// ── What this means for the form that commits capital ────────────────────────

/**
 * The reason F2-02 matters: `OrderEntryForm` sets its `submitting` flag *after*
 * awaiting the confirmation (`OrderEntryForm.tsx:328`), so the submit button is
 * live for the whole time the dialog is open. The backdrop blocks the mouse,
 * but focus is not trapped — Enter still submits the form behind it.
 *
 * With one resolver slot that produced a hung handler. With the fix, the
 * displaced handler returns at `if (!ok) return;` and exactly one order goes
 * out. This pins that, so the guard cannot regress into a double-submit.
 */
describe('OrderEntryForm — a second submit does not place a second order (F2-02)', () => {
  it('places exactly one order when submitted twice before confirming', async () => {
    const placeOrder = vi.fn(async () => ({ data: { ok: true } }));
    vi.resetModules();
    vi.doMock('../hooks/useApi', async () => {
      const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
      return { ...actual, tradingApi: { ...(actual.tradingApi as object), placeOrder } };
    });

    const { OrderEntryForm } = await import('../components/panels/OrderEntryForm');
    const { useStore } = await import('../store');
    const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query');
    // Import the provider from the SAME module graph as the form. After
    // `resetModules` the form gets a fresh `ConfirmDialog` module with a fresh
    // React context; pairing it with the top-level import gives a provider the
    // form cannot see, `useConfirm` falls back to its always-refuse stub, and
    // the test passes having exercised nothing.
    const { ConfirmDialogProvider: Provider } = await import('../components/ConfirmDialog');

    useStore.setState({
      wsStatus: 'connected', feedStale: false, lastDataAt: Date.now(),
      prices: {
        'XAU/USD': {
          symbol: 'XAU/USD', bid: 2350, ask: 2350.3, mid: 2350.15,
          spread: 0.3, timestamp: Date.now(), change_pct: 0,
        },
      },
    } as never);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <Provider>
          <OrderEntryForm />
        </Provider>
      </QueryClientProvider>,
    );

    const form = container.querySelector('form');
    expect(form, 'order form not rendered').toBeTruthy();

    // Two submits before anyone confirms — the Enter-key path.
    const fire = () => act(async () => { fireEvent.submit(form!); });
    await fire();
    await fire();

    // No escape hatch: if the dialog never opened, this test proves nothing and
    // must say so rather than pass quietly.
    const dialog = await screen.findByRole('dialog');
    const confirmBtn = within(dialog).getByRole('button', { name: /^(buy|sell)$/i });
    await userEvent.click(confirmBtn);

    await waitFor(() => expect(placeOrder).toHaveBeenCalled());
    expect(
      placeOrder.mock.calls.length,
      'two orders went out from one confirmation',
    ).toBe(1);
  });
});
