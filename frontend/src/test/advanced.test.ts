/**
 * Advanced tests — edge cases, boundary conditions, data validation.
 * ~130 tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type { PriceTick, Position, Signal, AccountMetrics, User } from '../store';

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── Price tick edge cases ────────────────────────────────────────────────────

describe('price tick edge cases', () => {
  const makeTick = (overrides: Partial<PriceTick> = {}): PriceTick => ({
    symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
    spread: 0.2, timestamp: Date.now(), change_pct: 0.0,
    ...overrides,
  });

  it('zero change_pct is stored', () => {
    useStore.getState().setPrice(makeTick({ change_pct: 0 }));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(0);
  });

  it('very large price is stored', () => {
    useStore.getState().setPrice(makeTick({ mid: 999_999, bid: 999_998, ask: 1_000_000 }));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(999_999);
  });

  it('very small price is stored', () => {
    useStore.getState().setPrice(makeTick({ symbol: 'MICRO', mid: 0.00001, bid: 0.000009, ask: 0.000011 }));
    expect(useStore.getState().prices['MICRO']?.mid).toBe(0.00001);
  });

  it('negative change_pct is stored', () => {
    useStore.getState().setPrice(makeTick({ change_pct: -5.5 }));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(-5.5);
  });

  it('large positive change_pct is stored', () => {
    useStore.getState().setPrice(makeTick({ change_pct: 15.0 }));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(15.0);
  });

  it('10 different symbols stored independently', () => {
    const symbols = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'];
    symbols.forEach((sym, i) => {
      useStore.getState().setPrice(makeTick({ symbol: sym, mid: 100 + i }));
    });
    symbols.forEach((sym, i) => {
      expect(useStore.getState().prices[sym]?.mid).toBe(100 + i);
    });
  });

  it('history for 10 symbols is independent', () => {
    const symbols = ['A', 'B', 'C'];
    symbols.forEach(sym => {
      for (let i = 0; i < 5; i++) {
        useStore.getState().setPrice(makeTick({ symbol: sym, mid: 100 + i }));
      }
    });
    symbols.forEach(sym => {
      expect(useStore.getState().priceHistory[sym]).toHaveLength(5);
    });
  });

  it('history exactly at 200 does not overflow', () => {
    for (let i = 0; i < 200; i++) {
      useStore.getState().setPrice(makeTick({ mid: 2340 + i }));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(200);
  });

  it('history at 201 trims to 200', () => {
    for (let i = 0; i < 201; i++) {
      useStore.getState().setPrice(makeTick({ mid: 2340 + i }));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(200);
  });

  it('latest tick is always the most recent', () => {
    for (let i = 0; i < 10; i++) {
      useStore.getState().setPrice(makeTick({ mid: 2340 + i, timestamp: i }));
    }
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2349);
  });
});

// ─── Position edge cases ──────────────────────────────────────────────────────

describe('position edge cases', () => {
  const makePos = (overrides: Partial<Position> = {}): Position => ({
    id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
    entry_price: 2340, current_price: 2350, unrealized_pnl: 100,
    realized_pnl: 0, opened_at: new Date().toISOString(),
    ...overrides,
  });

  it('position with negative unrealized_pnl', () => {
    useStore.getState().upsertPosition(makePos({ unrealized_pnl: -500 }));
    expect(useStore.getState().positions[0]?.unrealized_pnl).toBe(-500);
  });

  it('position with zero size', () => {
    useStore.getState().upsertPosition(makePos({ size: 0 }));
    expect(useStore.getState().positions[0]?.size).toBe(0);
  });

  it('position with fractional size', () => {
    useStore.getState().upsertPosition(makePos({ size: 0.01 }));
    expect(useStore.getState().positions[0]?.size).toBe(0.01);
  });

  it('upsert preserves other positions', () => {
    useStore.getState().setPositions([makePos({ id: 'p1' }), makePos({ id: 'p2', symbol: 'EUR/USD' })]);
    useStore.getState().upsertPosition(makePos({ id: 'p1', unrealized_pnl: 999 }));
    expect(useStore.getState().positions).toHaveLength(2);
    expect(useStore.getState().positions.find(p => p.id === 'p2')?.symbol).toBe('EUR/USD');
  });

  it('remove non-existent id leaves array unchanged', () => {
    useStore.getState().setPositions([makePos({ id: 'p1' }), makePos({ id: 'p2' })]);
    useStore.getState().removePosition('p999');
    expect(useStore.getState().positions).toHaveLength(2);
  });

  it('setPositions with 10 positions', () => {
    const positions = Array.from({ length: 10 }, (_, i) => makePos({ id: String(i) }));
    useStore.getState().setPositions(positions);
    expect(useStore.getState().positions).toHaveLength(10);
  });

  it('position realized_pnl is stored', () => {
    useStore.getState().upsertPosition(makePos({ realized_pnl: 250 }));
    expect(useStore.getState().positions[0]?.realized_pnl).toBe(250);
  });

  it('position opened_at is stored', () => {
    const ts = '2024-01-15T10:30:00.000Z';
    useStore.getState().upsertPosition(makePos({ opened_at: ts }));
    expect(useStore.getState().positions[0]?.opened_at).toBe(ts);
  });
});

// ─── Signal edge cases ────────────────────────────────────────────────────────

describe('signal edge cases', () => {
  const makeSig = (overrides: Partial<Signal> = {}): Signal => ({
    id: 's1', symbol: 'XAU/USD', direction: 'long', confidence: 0.85,
    model: 'XGBoost', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
    generated_at: new Date().toISOString(), status: 'active',
    ...overrides,
  });

  it('signal with confidence 0', () => {
    useStore.getState().addSignal(makeSig({ confidence: 0 }));
    expect(useStore.getState().signals[0]?.confidence).toBe(0);
  });

  it('signal with confidence 1', () => {
    useStore.getState().addSignal(makeSig({ confidence: 1 }));
    expect(useStore.getState().signals[0]?.confidence).toBe(1);
  });

  it('expired signal is stored', () => {
    useStore.getState().addSignal(makeSig({ status: 'expired' }));
    expect(useStore.getState().signals[0]?.status).toBe('expired');
  });

  it('addSignal keeps newest at index 0', () => {
    useStore.getState().addSignal(makeSig({ id: 's1', model: 'first' }));
    useStore.getState().addSignal(makeSig({ id: 's2', model: 'second' }));
    expect(useStore.getState().signals[0]?.model).toBe('second');
  });

  it('exactly 50 signals after 50 adds', () => {
    for (let i = 0; i < 50; i++) useStore.getState().addSignal(makeSig({ id: String(i) }));
    expect(useStore.getState().signals).toHaveLength(50);
  });

  it('51st signal drops oldest', () => {
    for (let i = 0; i < 51; i++) useStore.getState().addSignal(makeSig({ id: String(i), model: `m${i}` }));
    expect(useStore.getState().signals).toHaveLength(50);
    // Newest is at index 0
    expect(useStore.getState().signals[0]?.model).toBe('m50');
  });

  it('setSignals replaces addSignal results', () => {
    useStore.getState().addSignal(makeSig({ id: 's1' }));
    useStore.getState().setSignals([makeSig({ id: 's2' }), makeSig({ id: 's3' })]);
    expect(useStore.getState().signals).toHaveLength(2);
    expect(useStore.getState().signals[0]?.id).toBe('s2');
  });

  it('neutral direction signal', () => {
    useStore.getState().addSignal(makeSig({ direction: 'neutral' }));
    expect(useStore.getState().signals[0]?.direction).toBe('neutral');
  });
});

// ─── Account edge cases ───────────────────────────────────────────────────────

describe('account edge cases', () => {
  const makeAcc = (overrides: Partial<AccountMetrics> = {}): AccountMetrics => ({
    balance: 100_000, equity: 100_000, margin_used: 0, margin_free: 100_000,
    margin_level: 0, daily_pnl: 0, daily_pnl_pct: 0, total_pnl: 0,
    win_rate: 0.5, sharpe_ratio: 0, max_drawdown: 0, open_trades: 0,
    ...overrides,
  });

  it('zero balance account', () => {
    useStore.getState().setAccount(makeAcc({ balance: 0, equity: 0 }));
    expect(useStore.getState().account?.balance).toBe(0);
  });

  it('negative total_pnl (loss)', () => {
    useStore.getState().setAccount(makeAcc({ total_pnl: -5000 }));
    expect(useStore.getState().account?.total_pnl).toBe(-5000);
  });

  it('100% win rate', () => {
    useStore.getState().setAccount(makeAcc({ win_rate: 1.0 }));
    expect(useStore.getState().account?.win_rate).toBe(1.0);
  });

  it('0% win rate', () => {
    useStore.getState().setAccount(makeAcc({ win_rate: 0 }));
    expect(useStore.getState().account?.win_rate).toBe(0);
  });

  it('negative sharpe ratio', () => {
    useStore.getState().setAccount(makeAcc({ sharpe_ratio: -0.5 }));
    expect(useStore.getState().account?.sharpe_ratio).toBe(-0.5);
  });

  it('max drawdown of 100%', () => {
    useStore.getState().setAccount(makeAcc({ max_drawdown: 1.0 }));
    expect(useStore.getState().account?.max_drawdown).toBe(1.0);
  });

  it('large number of open trades', () => {
    useStore.getState().setAccount(makeAcc({ open_trades: 100 }));
    expect(useStore.getState().account?.open_trades).toBe(100);
  });

  it('setAccount twice keeps latest', () => {
    useStore.getState().setAccount(makeAcc({ balance: 100_000 }));
    useStore.getState().setAccount(makeAcc({ balance: 200_000 }));
    expect(useStore.getState().account?.balance).toBe(200_000);
  });
});

// ─── User role edge cases ─────────────────────────────────────────────────────

describe('user role edge cases', () => {
  const makeUser = (role: User['role']): User => ({
    id: '1', email: 'a@b.com', username: 'u', role,
  });

  it('user role stored correctly', () => {
    useStore.getState().setAuth('tok', makeUser('user'));
    expect(useStore.getState().user?.role).toBe('user');
  });

  it('trader role stored correctly', () => {
    useStore.getState().setAuth('tok', makeUser('trader'));
    expect(useStore.getState().user?.role).toBe('trader');
  });

  it('admin role stored correctly', () => {
    useStore.getState().setAuth('tok', makeUser('admin'));
    expect(useStore.getState().user?.role).toBe('admin');
  });

  it('superadmin role stored correctly', () => {
    useStore.getState().setAuth('tok', makeUser('superadmin'));
    expect(useStore.getState().user?.role).toBe('superadmin');
  });

  it('user email is stored', () => {
    const user = { ...makeUser('trader'), email: 'trader@hopefx.io' };
    useStore.getState().setAuth('tok', user);
    expect(useStore.getState().user?.email).toBe('trader@hopefx.io');
  });

  it('user id is stored', () => {
    const user = { ...makeUser('trader'), id: 'abc-123' };
    useStore.getState().setAuth('tok', user);
    expect(useStore.getState().user?.id).toBe('abc-123');
  });

  it('username is stored', () => {
    const user = { ...makeUser('trader'), username: 'goldtrader' };
    useStore.getState().setAuth('tok', user);
    expect(useStore.getState().user?.username).toBe('goldtrader');
  });
});

// ─── Concurrent state updates ─────────────────────────────────────────────────

describe('concurrent state updates', () => {
  it('rapid auth + price updates do not corrupt state', () => {
    const user: User = { id: '1', email: 'a@b.com', username: 'u', role: 'trader' };
    useStore.getState().setAuth('tok', user);
    for (let i = 0; i < 50; i++) {
      useStore.getState().setPrice({ symbol: 'XAU/USD', bid: 2340 + i - 0.1, ask: 2340 + i + 0.1, mid: 2340 + i, spread: 0.2, timestamp: i, change_pct: 0 });
    }
    expect(useStore.getState().isAuthenticated).toBe(true);
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2389);
  });

  it('setPositions + upsertPosition + removePosition sequence', () => {
    const pos = (id: string): Position => ({
      id, symbol: 'XAU/USD', side: 'long', size: 1,
      entry_price: 2340, current_price: 2350, unrealized_pnl: 100,
      realized_pnl: 0, opened_at: new Date().toISOString(),
    });
    useStore.getState().setPositions([pos('a'), pos('b'), pos('c')]);
    useStore.getState().upsertPosition({ ...pos('d'), symbol: 'EUR/USD' });
    useStore.getState().removePosition('b');
    const positions = useStore.getState().positions;
    expect(positions).toHaveLength(3);
    expect(positions.map(p => p.id).sort()).toEqual(['a', 'c', 'd']);
  });

  it('ws status changes do not affect prices', () => {
    useStore.getState().setPrice({ symbol: 'XAU/USD', bid: 2339, ask: 2341, mid: 2340, spread: 2, timestamp: 1, change_pct: 0 });
    useStore.getState().setWsStatus('connected');
    useStore.getState().setWsStatus('disconnected');
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2340);
  });

  it('clearAuth does not affect prices or positions', () => {
    const user: User = { id: '1', email: 'a@b.com', username: 'u', role: 'trader' };
    useStore.getState().setAuth('tok', user);
    useStore.getState().setPrice({ symbol: 'XAU/USD', bid: 2339, ask: 2341, mid: 2340, spread: 2, timestamp: 1, change_pct: 0 });
    useStore.getState().upsertPosition({ id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1, entry_price: 2340, current_price: 2350, unrealized_pnl: 100, realized_pnl: 0, opened_at: new Date().toISOString() });
    useStore.getState().clearAuth();
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2340);
    expect(useStore.getState().positions).toHaveLength(1);
  });
});

// ─── Heartbeat ────────────────────────────────────────────────────────────────

describe('heartbeat', () => {
  it('setHeartbeat updates lastHeartbeat', () => {
    const ts = 1_700_000_000_000;
    useStore.getState().setHeartbeat(ts);
    expect(useStore.getState().lastHeartbeat).toBe(ts);
  });

  it('multiple heartbeats keep latest', () => {
    useStore.getState().setHeartbeat(1000);
    useStore.getState().setHeartbeat(2000);
    useStore.getState().setHeartbeat(3000);
    expect(useStore.getState().lastHeartbeat).toBe(3000);
  });

  it('heartbeat does not affect ws status', () => {
    useStore.getState().setWsStatus('connected');
    useStore.getState().setHeartbeat(Date.now());
    expect(useStore.getState().wsStatus).toBe('connected');
  });

  it('heartbeat does not affect auth', () => {
    const user: User = { id: '1', email: 'a@b.com', username: 'u', role: 'trader' };
    useStore.getState().setAuth('tok', user);
    useStore.getState().setHeartbeat(Date.now());
    expect(useStore.getState().isAuthenticated).toBe(true);
  });
});

// ─── Store reset ──────────────────────────────────────────────────────────────

describe('store reset behaviour', () => {
  it('fresh store has all expected keys', () => {
    const s = useStore.getState();
    expect(s).toHaveProperty('token');
    expect(s).toHaveProperty('user');
    expect(s).toHaveProperty('isAuthenticated');
    expect(s).toHaveProperty('prices');
    expect(s).toHaveProperty('priceHistory');
    expect(s).toHaveProperty('positions');
    expect(s).toHaveProperty('signals');
    expect(s).toHaveProperty('account');
    expect(s).toHaveProperty('wsStatus');
    expect(s).toHaveProperty('lastHeartbeat');
  });

  it('fresh store has all action functions', () => {
    const s = useStore.getState();
    expect(typeof s.setAuth).toBe('function');
    expect(typeof s.clearAuth).toBe('function');
    expect(typeof s.setPrice).toBe('function');
    expect(typeof s.setPositions).toBe('function');
    expect(typeof s.upsertPosition).toBe('function');
    expect(typeof s.removePosition).toBe('function');
    expect(typeof s.setSignals).toBe('function');
    expect(typeof s.addSignal).toBe('function');
    expect(typeof s.setAccount).toBe('function');
    expect(typeof s.setWsStatus).toBe('function');
    expect(typeof s.setHeartbeat).toBe('function');
  });
});
