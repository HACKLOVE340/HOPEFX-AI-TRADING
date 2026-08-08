/**
 * S10-03 — a confirmation must state the magnitude, not just the action.
 *
 * docs/HARDENING_BACKLOG.md S10-03.
 *
 * There were two close-all confirmations with different wording and different
 * information — the duplication pattern from S13-01, where every duplicated
 * pair in this codebase had already produced a defect:
 *
 *   Trade.tsx:473        "This will market-close every open position
 *                         immediately. This cannot be undone."
 *                         → no count, no exposure, no P&L
 *
 *   PositionsTable:282   "Close all N open position(s)? This cannot be undone."
 *                         → count only
 *
 * "Every open position" is a category, not a quantity. A trader confirming it
 * is agreeing to something they cannot check: they are not told how many
 * positions, how much notional, or — the number that actually matters — what
 * P&L they are about to realise. Closing three winners and closing three
 * losers read identically.
 *
 * `describeCloseAll()` builds one summary both call sites use.
 */

import { describe, it, expect } from 'vitest';
import { describeCloseAll } from '../lib/utils';

const pos = (over: Partial<Record<string, unknown>> = {}) => ({
  id: 'p1',
  symbol: 'XAUUSD',
  side: 'long',
  quantity: 1,
  entry_price: 2350,
  current_price: 2360,
  unrealized_pnl: 10,
  ...over,
});

describe('describeCloseAll — S10-03', () => {
  it('states how many positions', () => {
    const s = describeCloseAll([pos(), pos({ id: 'p2' })] as never);
    expect(s).toMatch(/\b2\b/);
  });

  it('states the P&L that will be realised', () => {
    const s = describeCloseAll([
      pos({ unrealized_pnl: 125.5 }),
      pos({ id: 'p2', unrealized_pnl: -40.25 }),
    ] as never);
    // Net +85.25 — the number the trader is actually agreeing to.
    expect(s).toMatch(/85\.25/);
  });

  it('makes a loss unmistakable rather than just signed', () => {
    const s = describeCloseAll([pos({ unrealized_pnl: -300 })] as never);
    expect(s).toMatch(/300/);
    expect(s.toLowerCase()).toMatch(/loss|-/);
  });

  it('distinguishes closing winners from closing losers', () => {
    const winners = describeCloseAll([pos({ unrealized_pnl: 500 })] as never);
    const losers = describeCloseAll([pos({ unrealized_pnl: -500 })] as never);
    expect(winners).not.toBe(losers);
  });

  it('names the symbols when there are few enough to read', () => {
    const s = describeCloseAll([
      pos({ symbol: 'XAUUSD' }),
      pos({ id: 'p2', symbol: 'EURUSD' }),
    ] as never);
    expect(s).toContain('XAUUSD');
    expect(s).toContain('EURUSD');
  });

  it('does not print an unreadable wall of symbols for many positions', () => {
    const many = Array.from({ length: 12 }, (_, i) => pos({ id: `p${i}`, symbol: `SYM${i}` }));
    const s = describeCloseAll(many as never);
    expect(s).toMatch(/\b12\b/);
    expect(s.length).toBeLessThan(240);
  });

  it('says so plainly when there is nothing to close', () => {
    expect(describeCloseAll([] as never).toLowerCase()).toMatch(/no open position/);
  });

  it('survives positions with missing P&L rather than inventing a total', () => {
    const s = describeCloseAll([
      pos({ unrealized_pnl: undefined }),
      pos({ id: 'p2', unrealized_pnl: 50 }),
    ] as never);
    expect(s).toBeTruthy();
    expect(s).not.toMatch(/NaN|undefined/);
  });
});
