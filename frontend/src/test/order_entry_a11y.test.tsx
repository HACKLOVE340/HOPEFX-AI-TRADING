/**
 * S10-04 — the order form's toggles announce no selection state.
 *
 * docs/HARDENING_BACKLOG.md S10-04, revisited under F8. The original entry said:
 *
 *   > 31 of 204 `.tsx` files reference any `aria-` attribute (~15%).
 *   > `OrderEntryForm.tsx` has exactly one — `role="alert"` at `:493`. The order
 *   > inputs (symbol, side, quantity, SL, TP) carry no `aria-label`.
 *
 * **The second sentence measured the wrong thing.** The inputs are labelled, and
 * labelled the better way: `Field` renders `<label htmlFor={id}>` against
 * `<input id={id}>`, which is native association and is preferred over
 * `aria-label`. Counting `aria-` attributes cannot see that, so a file doing it
 * correctly scores zero. Corrected in the backlog.
 *
 * What is genuinely missing is on the two controls that are not native inputs:
 *
 *     <button type="button" onClick={() => setSide(s)}
 *             className={cn(..., side === s && s === 'buy' ? '…green…' : '…')}>
 *
 * Buy/Sell and Market/Limit/Stop are buttons whose **selected state lives only
 * in a CSS class**. Tabbing through announces "Buy, button. Sell, button." with
 * nothing to say which one is active — on the control that decides the
 * direction of an order, next to a submit button that will commit capital in
 * that direction.
 *
 * This is the money-path half of F8, reported separately from general
 * accessibility as that slice asks. It is also not only a screen-reader issue:
 * the state is carried by a green/red distinction, so it is the F7-01 question
 * again on a control rather than a readout.
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useStore } from '../store';
import { OrderEntryForm } from '../components/panels/OrderEntryForm';

const renderForm = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OrderEntryForm symbol="XAU/USD" />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  useStore.setState({
    wsStatus: 'connected', feedStale: false, lastDataAt: Date.now(),
    prices: {
      'XAU/USD': {
        symbol: 'XAU/USD', bid: 2350, ask: 2350.3, mid: 2350.15,
        spread: 0.3, timestamp: Date.now(), change_pct: 0,
      },
    },
  } as never);
});

const btn = (name: RegExp) => screen.getByRole('button', { name });

describe('order side toggle announces which side is selected — S10-04', () => {
  it('the selected side is pressed', () => {
    renderForm();
    expect(
      btn(/^▲ buy$/i).getAttribute('aria-pressed'),
      'the Buy/Sell toggle carries its state in a CSS class only, so nothing ' +
        'announces which direction the order will go (S10-04)',
    ).toBe('true');
  });

  it('the unselected side is not pressed', () => {
    renderForm();
    expect(btn(/^▼ sell$/i).getAttribute('aria-pressed')).toBe('false');
  });

  it('pressing Sell moves the state', async () => {
    renderForm();
    await userEvent.click(btn(/^▼ sell$/i));
    expect(btn(/^▼ sell$/i).getAttribute('aria-pressed')).toBe('true');
    expect(btn(/^▲ buy$/i).getAttribute('aria-pressed')).toBe('false');
  });

  it('the pair is a named group, not two loose buttons', () => {
    renderForm();
    const group = screen.getByRole('group', { name: /side|direction|buy.*sell/i });
    expect(group).toBeTruthy();
  });
});

describe('order type toggle announces which type is selected — S10-04', () => {
  it('market is pressed by default', () => {
    renderForm();
    expect(btn(/^market$/i).getAttribute('aria-pressed')).toBe('true');
  });

  it('the others are not', () => {
    renderForm();
    expect(btn(/^limit$/i).getAttribute('aria-pressed')).toBe('false');
    expect(btn(/^stop$/i).getAttribute('aria-pressed')).toBe('false');
  });

  it('selecting Limit moves the state', async () => {
    renderForm();
    await userEvent.click(btn(/^limit$/i));
    expect(btn(/^limit$/i).getAttribute('aria-pressed')).toBe('true');
    expect(btn(/^market$/i).getAttribute('aria-pressed')).toBe('false');
  });

  it('the set is a named group', () => {
    renderForm();
    expect(screen.getByRole('group', { name: /order type/i })).toBeTruthy();
  });
});

// ── The correction: the inputs were already labelled ─────────────────────────

describe('order inputs are labelled — S10-04 correction', () => {
  it('quantity is reachable by its label', () => {
    renderForm();
    expect(screen.getByLabelText(/quantity/i)).toBeTruthy();
  });

  it('stop loss is reachable by its label', () => {
    renderForm();
    expect(screen.getByLabelText(/stop loss/i)).toBeTruthy();
  });

  it('take profit is reachable by its label', () => {
    renderForm();
    expect(screen.getByLabelText(/take profit/i)).toBeTruthy();
  });
});
