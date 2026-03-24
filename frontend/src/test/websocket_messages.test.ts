/**
 * WebSocket message parsing and routing tests.
 * ~80 tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type { PriceTick, Position, Signal, AccountMetrics } from '../store';

// Simulate the message handler logic from useWebSocket
function handleMessage(raw: string) {
  let msg: { type: string; data?: unknown };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return;
    msg = parsed;
  } catch {
    return;
  }

  const store = useStore.getState();
  switch (msg.type) {
    case 'price_tick':
      store.setPrice(msg.data as PriceTick);
      break;
    case 'position_update':
      store.upsertPosition(msg.data as Position);
      break;
    case 'position_close':
      store.removePosition((msg.data as { id: string }).id);
      break;
    case 'signal':
      store.addSignal(msg.data as Signal);
      break;
    case 'account_update':
      store.setAccount(msg.data as AccountMetrics);
      break;
    case 'heartbeat':
      store.setHeartbeat(Date.now());
      break;
    default:
      break;
  }
}

const makeTick = (): PriceTick => ({
  symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
  spread: 0.2, timestamp: Date.now(), change_pct: 0.5,
});

const makePos = (): Position => ({
  id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
  entry_price: 2340, current_price: 2350, unrealized_pnl: 100,
  realized_pnl: 0, opened_at: new Date().toISOString(),
});

const makeSig = (): Signal => ({
  id: 's1', symbol: 'XAU/USD', direction: 'long', confidence: 0.85,
  model: 'XGBoost', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
  generated_at: new Date().toISOString(), status: 'active',
});

const makeAcc = (): AccountMetrics => ({
  balance: 100_000, equity: 102_000, margin_used: 4_000, margin_free: 96_000,
  margin_level: 2550, daily_pnl: 500, daily_pnl_pct: 0.5, total_pnl: 2_000,
  win_rate: 0.65, sharpe_ratio: 1.8, max_drawdown: 0.04, open_trades: 2,
});

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── price_tick ───────────────────────────────────────────────────────────────

describe('price_tick messages', () => {
  it('updates price in store', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2340.0);
  });

  it('updates price history', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(1);
  });

  it('multiple ticks accumulate history', () => {
    for (let i = 0; i < 5; i++) {
      handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 + i } }));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(5);
  });

  it('latest price is most recent tick', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 } }));
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2345 } }));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2345);
  });

  it('different symbols stored separately', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), symbol: 'EUR/USD', mid: 1.085 } }));
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), symbol: 'GBP/USD', mid: 1.27 } }));
    expect(useStore.getState().prices['EUR/USD']?.mid).toBe(1.085);
    expect(useStore.getState().prices['GBP/USD']?.mid).toBe(1.27);
  });

  it('bid/ask stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(tick.bid).toBe(2339.9);
    expect(tick.ask).toBe(2340.1);
  });

  it('change_pct stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), change_pct: -1.5 } }));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(-1.5);
  });
});

// ─── position_update ──────────────────────────────────────────────────────────

describe('position_update messages', () => {
  it('adds new position', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    expect(useStore.getState().positions).toHaveLength(1);
  });

  it('updates existing position', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), unrealized_pnl: 500 } }));
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].unrealized_pnl).toBe(500);
  });

  it('multiple different positions', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), id: 'p2', symbol: 'EUR/USD' } }));
    expect(useStore.getState().positions).toHaveLength(2);
  });

  it('position side is stored', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), side: 'short' } }));
    expect(useStore.getState().positions[0].side).toBe('short');
  });
});

// ─── position_close ───────────────────────────────────────────────────────────

describe('position_close messages', () => {
  it('removes position by id', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    expect(useStore.getState().positions).toHaveLength(0);
  });

  it('removes correct position when multiple exist', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), id: 'p2' } }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].id).toBe('p2');
  });

  it('close non-existent id is safe', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p999' } }));
    expect(useStore.getState().positions).toHaveLength(1);
  });
});

// ─── signal ───────────────────────────────────────────────────────────────────

describe('signal messages', () => {
  it('adds signal to store', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: makeSig() }));
    expect(useStore.getState().signals).toHaveLength(1);
  });

  it('signal is prepended', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: 's1', model: 'first' } }));
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: 's2', model: 'second' } }));
    expect(useStore.getState().signals[0].model).toBe('second');
  });

  it('signal confidence stored', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), confidence: 0.92 } }));
    expect(useStore.getState().signals[0].confidence).toBe(0.92);
  });

  it('signal direction stored', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), direction: 'short' } }));
    expect(useStore.getState().signals[0].direction).toBe('short');
  });

  it('10 signals stored', () => {
    for (let i = 0; i < 10; i++) {
      handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: String(i) } }));
    }
    expect(useStore.getState().signals).toHaveLength(10);
  });
});

// ─── account_update ───────────────────────────────────────────────────────────

describe('account_update messages', () => {
  it('sets account in store', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.balance).toBe(100_000);
  });

  it('overwrites previous account', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    handleMessage(JSON.stringify({ type: 'account_update', data: { ...makeAcc(), balance: 200_000 } }));
    expect(useStore.getState().account?.balance).toBe(200_000);
  });

  it('equity stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.equity).toBe(102_000);
  });

  it('win_rate stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.win_rate).toBe(0.65);
  });
});

// ─── heartbeat ────────────────────────────────────────────────────────────────

describe('heartbeat messages', () => {
  it('updates lastHeartbeat', () => {
    const before = Date.now();
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const after = Date.now();
    const hb = useStore.getState().lastHeartbeat!;
    expect(hb).toBeGreaterThanOrEqual(before);
    expect(hb).toBeLessThanOrEqual(after);
  });

  it('multiple heartbeats update timestamp', () => {
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const first = useStore.getState().lastHeartbeat;
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const second = useStore.getState().lastHeartbeat;
    expect(second).toBeGreaterThanOrEqual(first!);
  });
});

// ─── Invalid messages ─────────────────────────────────────────────────────────

describe('invalid messages', () => {
  it('invalid JSON does not throw', () => {
    expect(() => handleMessage('not json')).not.toThrow();
  });

  it('empty string does not throw', () => {
    expect(() => handleMessage('')).not.toThrow();
  });

  it('unknown type does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ type: 'unknown_type', data: {} }))).not.toThrow();
  });

  it('missing type does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ data: {} }))).not.toThrow();
  });

  it('null message does not throw', () => {
    expect(() => handleMessage(JSON.stringify(null))).not.toThrow();
  });

  it('store state unchanged after invalid message', () => {
    handleMessage('garbage');
    expect(useStore.getState().prices).toEqual({});
    expect(useStore.getState().positions).toEqual([]);
  });

  it('error type does not modify store', () => {
    handleMessage(JSON.stringify({ type: 'error', data: { message: 'server error' } }));
    expect(useStore.getState().prices).toEqual({});
  });
});

// ─── Message sequence ─────────────────────────────────────────────────────────

describe('message sequences', () => {
  it('full trading session sequence', () => {
    // 1. Connect → account update
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    // 2. Price ticks
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    // 3. Signal generated
    handleMessage(JSON.stringify({ type: 'signal', data: makeSig() }));
    // 4. Position opened
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    // 5. Price update
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2360 } }));
    // 6. Position closed
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    // 7. Account updated
    handleMessage(JSON.stringify({ type: 'account_update', data: { ...makeAcc(), total_pnl: 2200 } }));

    expect(useStore.getState().account?.total_pnl).toBe(2200);
    expect(useStore.getState().positions).toHaveLength(0);
    expect(useStore.getState().signals).toHaveLength(1);
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2360);
  });

  it('rapid price ticks followed by position update', () => {
    for (let i = 0; i < 20; i++) {
      handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 + i } }));
    }
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(20);
    expect(useStore.getState().positions).toHaveLength(1);
  });
});
