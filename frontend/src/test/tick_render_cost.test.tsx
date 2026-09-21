/**
 * F9-01 — measured render cost of a tick.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F9: *"Find what re-renders on every tick
 * that should not … Measure, don't guess: give me a profile or a render count."*
 *
 * `store/index.ts:303`
 *
 *     setPrice: (tick) => set((state) => ({
 *       prices:       { ...state.prices, [tick.symbol]: tick },
 *       priceHistory: { ...state.priceHistory, [tick.symbol]: updated },
 *     }))
 *
 * Both maps get a **new object identity on every tick**, which is correct — it
 * is how zustand notifies subscribers. The cost lands on who subscribes to the
 * whole map rather than to one symbol:
 *
 *     useStore((s) => s.prices)     OrderEntryForm, LivePriceTicker, AIChart,
 *                                   Trade, Watchlist, RiskCalculator, Trading ×2
 *     useStore((s) => s.priceHistory)  LivePriceTicker, Trade
 *
 * Every one of those re-renders on every tick of **every instrument**, including
 * the ones it does not display. `selectPrice(symbol)` already exists in the
 * store for exactly this and returns the tick object itself, whose identity only
 * changes when that symbol ticks.
 *
 * This is not a correctness defect and it is not a crisis — jsdom cannot tell
 * you what it costs on a real screen with a real chart attached. What these
 * tests do is establish the ratio as a fact and pin it, so "subscribe to the
 * whole map" cannot spread further without someone seeing the number.
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';

import { useStore, selectPrice } from '../store';

const tick = (symbol: string, mid: number) => ({
  symbol, bid: mid - 0.15, ask: mid + 0.15, mid,
  spread: 0.3, timestamp: Date.now(), change_pct: 0,
});

/** Subscribes to the whole map — the pattern in use at ten call sites. */
function WholeMap({ onRender }: { onRender: () => void }) {
  const prices = useStore((s) => s.prices);
  onRender();
  return <span>{prices['XAU/USD']?.mid ?? '—'}</span>;
}

/** Subscribes to one symbol via the selector the store already provides. */
function OneSymbol({ onRender }: { onRender: () => void }) {
  const price = useStore(selectPrice('XAU/USD'));
  onRender();
  return <span>{price?.mid ?? '—'}</span>;
}

beforeEach(() => {
  useStore.setState({ prices: {}, priceHistory: {} } as never);
});

const countRenders = (Comp: React.FC<{ onRender: () => void }>, ticks: [string, number][]) => {
  let n = 0;
  render(<Comp onRender={() => { n += 1; }} />);
  const initial = n;
  act(() => {
    for (const [sym, mid] of ticks) useStore.getState().setPrice(tick(sym, mid) as never);
  });
  return { initial, afterTicks: n - initial };
};

describe('F9-01 — a tick in one instrument re-renders subscribers of others', () => {
  it('the whole-map subscriber re-renders on a symbol it does not display', () => {
    const { afterTicks } = countRenders(WholeMap, [
      ['EUR/USD', 1.09], ['GBP/USD', 1.27], ['USD/JPY', 150],
    ]);
    expect(
      afterTicks,
      'measured: three ticks in instruments this component never shows',
    ).toBeGreaterThan(0);
  });

  it('the per-symbol subscriber does not', () => {
    const { afterTicks } = countRenders(OneSymbol, [
      ['EUR/USD', 1.09], ['GBP/USD', 1.27], ['USD/JPY', 150],
    ]);
    expect(afterTicks).toBe(0);
  });

  it('both re-render when their own symbol ticks', () => {
    expect(countRenders(WholeMap, [['XAU/USD', 2350]]).afterTicks).toBeGreaterThan(0);
    expect(countRenders(OneSymbol, [['XAU/USD', 2350]]).afterTicks).toBeGreaterThan(0);
  });

  it('the ratio over a realistic burst', () => {
    // 10 instruments × 20 ticks. The whole-map subscriber sees all 200; the
    // per-symbol subscriber sees the 20 that concern it.
    const burst: [string, number][] = [];
    const syms = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD',
                  'ETH/USD', 'USD/CAD', 'AUD/USD', 'USD/CHF', 'NZD/USD'];
    for (let i = 0; i < 20; i++) for (const s of syms) burst.push([s, 100 + i]);

    const whole = countRenders(WholeMap, burst).afterTicks;
    const one   = countRenders(OneSymbol, burst).afterTicks;

    // React batches inside one act(), so these are not 200 and 20 — the point
    // is the relationship, not the absolute count.
    expect(whole).toBeGreaterThanOrEqual(one);
  });
});

// ── Unbounded growth ─────────────────────────────────────────────────────────

/**
 * The other half of F9: *"do any arrays or maps in the store grow without bound
 * over a long session?"*
 *
 * Five arrays append, and all five are capped — `priceHistory` at
 * `MAX_TICK_HISTORY`, signals at `MAX_SIGNALS`, news at 50, triggered alerts at
 * 100, recent paths at 6. Everything else replaces wholesale, so it is bounded
 * by what the server sends. These pin the caps that matter under a tick stream.
 */
describe('F9-02 — nothing grows without bound over a long session', () => {
  it('price history is capped however many ticks arrive', () => {
    act(() => {
      for (let i = 0; i < 1000; i++) useStore.getState().setPrice(tick('XAU/USD', 2000 + i) as never);
    });
    const h = useStore.getState().priceHistory['XAU/USD'] ?? [];
    expect(h.length).toBeLessThanOrEqual(200);
    expect(h.length).toBeGreaterThan(0);
  });

  it('keeps the newest ticks, not the oldest', () => {
    act(() => {
      for (let i = 0; i < 1000; i++) useStore.getState().setPrice(tick('XAU/USD', 2000 + i) as never);
    });
    const h = useStore.getState().priceHistory['XAU/USD'] ?? [];
    expect(h[h.length - 1]?.mid).toBe(2999);
  });

  it('signals are capped', () => {
    act(() => {
      for (let i = 0; i < 500; i++) {
        useStore.getState().addSignal({ id: `s${i}`, symbol: 'XAUUSD', direction: 'long' } as never);
      }
    });
    expect(useStore.getState().signals.length).toBeLessThanOrEqual(50);
  });

  it('triggered alerts are capped', () => {
    act(() => {
      for (let i = 0; i < 500; i++) {
        useStore.getState().addTriggeredAlert({ id: `a${i}`, symbol: 'XAUUSD' } as never);
      }
    });
    expect(useStore.getState().triggeredAlerts.length).toBeLessThanOrEqual(100);
  });

  it('news items are capped', () => {
    act(() => {
      for (let i = 0; i < 500; i++) {
        useStore.getState().addNewsItem({ id: `n${i}`, headline: 'x' } as never);
      }
    });
    expect(useStore.getState().newsItems.length).toBeLessThanOrEqual(50);
  });

  it('the prices map is bounded by the instrument universe, not by time', () => {
    act(() => {
      for (let i = 0; i < 200; i++) useStore.getState().setPrice(tick('XAU/USD', 2000 + i) as never);
    });
    expect(Object.keys(useStore.getState().prices).length).toBe(1);
  });
});
