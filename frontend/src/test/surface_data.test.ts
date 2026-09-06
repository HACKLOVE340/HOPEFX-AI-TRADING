/**
 * Surfaces read live data, or say they have none.
 *
 * §22: "Metrics must be connected to real telemetry when the backend exists.
 * Avoid fake 'live' values in production." Everything here already flows over
 * the WebSocket the platform has run for months — prices with history,
 * positions, the risk snapshot, news. A surface that ignored it in favour of a
 * plausible-looking constant would be exactly the defect that rule exists for,
 * and this repository has shipped that defect before.
 *
 * The other half matters as much: **an empty source says so.** "No positions
 * open" and "awaiting a data source" are different facts, and a surface that
 * renders them identically has told the operator nothing.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import { surfaceData } from '../hub/surfaceData';

beforeEach(() => {
  useStore.setState({
    prices: {}, priceHistory: {}, positions: [], newsItems: [],
    riskSnapshot: undefined, account: undefined,
  } as never);
});

describe('the gold chart', () => {
  it('draws the real price history when there is one', () => {
    useStore.setState({ priceHistory: { 'XAU/USD': [2380, 2385, 2391] } } as never);
    const d = surfaceData({ kind: 'chart', key: 'gold-chart' });
    expect(d.points).toEqual([2380, 2385, 2391]);
    expect(d.empty).toBe(false);
  });

  it('says it has no history rather than drawing a shape from nothing', () => {
    const d = surfaceData({ kind: 'chart', key: 'gold-chart' });
    expect(d.empty).toBe(true);
    expect(d.note).toMatch(/no price history|not arrived|waiting/i);
  });
});

describe('open positions', () => {
  it('lists what is actually open', () => {
    useStore.setState({
      positions: [
        { id: '1', symbol: 'XAUUSD', size: 0.4, side: 'long', entry_price: 2380, current_price: 2391, unrealized_pnl: 182 },
      ],
    } as never);
    const d = surfaceData({ kind: 'table', key: 'positions' });
    const flat = JSON.stringify(d.rows);
    expect(flat).toMatch(/XAUUSD/);
    // The P&L field is `unrealized_pnl`, not `pnl`. Reaching for the wrong one
    // renders an em-dash on every row forever — a panel that looks like it has
    // no data when it has plenty. The type checker caught it; this pins it.
    expect(flat).toMatch(/\+182/);
    expect(d.empty).toBe(false);
  });

  it('distinguishes "no positions" from "no data"', () => {
    // Both render as an empty table if nobody draws the distinction, and they
    // mean opposite things to a trader.
    const d = surfaceData({ kind: 'table', key: 'positions' });
    expect(d.empty).toBe(true);
    expect(d.note).toMatch(/no open positions/i);
  });
});

describe('risk', () => {
  it('reads the live risk snapshot', () => {
    useStore.setState({
      riskSnapshot: { daily_loss_pct: 2.1, max_drawdown_pct: 4.6, open_risk_pct: 1.2, kill_switch_active: false },
    } as never);
    const d = surfaceData({ kind: 'table', key: 'risk' });
    expect(JSON.stringify(d.rows)).toMatch(/4\.6/);
  });

  it('reports the kill switch in words, not only as a boolean', () => {
    useStore.setState({ riskSnapshot: { kill_switch_active: true } } as never);
    const d = surfaceData({ kind: 'table', key: 'risk' });
    expect(JSON.stringify(d.rows).toLowerCase()).toMatch(/tripped|active|engaged/);
  });

  it('says risk has not been measured rather than showing zeros', () => {
    // Zero drawdown and unmeasured drawdown look identical as a number and are
    // opposite as a fact.
    const d = surfaceData({ kind: 'table', key: 'risk' });
    expect(d.empty).toBe(true);
    expect(d.note).toMatch(/not been measured|no risk data/i);
  });
});

describe('news', () => {
  it('shows the headlines that arrived over the feed', () => {
    useStore.setState({ newsItems: [{ headline: 'Gold holds range', ts: 1 }] } as never);
    const d = surfaceData({ kind: 'news', key: 'news' });
    expect(d.items).toContain('Gold holds range');
  });

  it('says the feed is quiet rather than inventing a headline', () => {
    const d = surfaceData({ kind: 'news', key: 'news' });
    expect(d.empty).toBe(true);
    expect(d.items).toEqual([]);
  });
});

describe('surfaces with no binding yet', () => {
  it('are honest that nothing is wired, not that nothing exists', () => {
    const d = surfaceData({ kind: 'simulation', key: 'whatever' });
    expect(d.empty).toBe(true);
    expect(d.note).toMatch(/connected|source/i);
    expect(d.note).toMatch(/later phase|not yet/i);
  });
});
