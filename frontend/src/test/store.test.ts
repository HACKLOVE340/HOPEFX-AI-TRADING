/**
 * Zustand store tests — covers all slices and selectors.
 * ~120 tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type { User, PriceTick, Position, Signal, AccountMetrics } from '../store';

// Reset store between tests
beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── Auth slice ───────────────────────────────────────────────────────────────

describe('auth slice', () => {
  const mockUser: User = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' };

  it('starts unauthenticated', () => {
    const s = useStore.getState();
    expect(s.isAuthenticated).toBe(false);
    expect(s.token).toBeNull();
    expect(s.user).toBeNull();
  });

  it('setAuth stores token and user', () => {
    useStore.getState().setAuth('tok123', mockUser);
    const s = useStore.getState();
    expect(s.isAuthenticated).toBe(true);
    expect(s.token).toBe('tok123');
    expect(s.user).toEqual(mockUser);
  });

  it('clearAuth resets all auth fields', () => {
    useStore.getState().setAuth('tok123', mockUser);
    useStore.getState().clearAuth();
    const s = useStore.getState();
    expect(s.isAuthenticated).toBe(false);
    expect(s.token).toBeNull();
    expect(s.user).toBeNull();
  });

  it('setAuth with admin role', () => {
    const admin: User = { ...mockUser, role: 'admin' };
    useStore.getState().setAuth('admin-tok', admin);
    expect(useStore.getState().user?.role).toBe('admin');
  });

  it('setAuth with superadmin role', () => {
    const su: User = { ...mockUser, role: 'superadmin' };
    useStore.getState().setAuth('su-tok', su);
    expect(useStore.getState().user?.role).toBe('superadmin');
  });

  it('multiple setAuth calls overwrite previous', () => {
    useStore.getState().setAuth('tok1', mockUser);
    const user2: User = { ...mockUser, id: '2', username: 'trader2' };
    useStore.getState().setAuth('tok2', user2);
    expect(useStore.getState().token).toBe('tok2');
    expect(useStore.getState().user?.username).toBe('trader2');
  });

  it('clearAuth after no setAuth is safe', () => {
    expect(() => useStore.getState().clearAuth()).not.toThrow();
  });
});

// ─── Price slice ──────────────────────────────────────────────────────────────

describe('price slice', () => {
  const tick = (symbol: string, mid: number, change = 0.5): PriceTick => ({
    symbol, bid: mid - 0.1, ask: mid + 0.1, mid, spread: 0.2,
    timestamp: Date.now(), change_pct: change,
  });

  it('starts with empty prices', () => {
    expect(useStore.getState().prices).toEqual({});
  });

  it('setPrice stores a tick', () => {
    useStore.getState().setPrice(tick('XAU/USD', 2340));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2340);
  });

  it('setPrice updates existing symbol', () => {
    useStore.getState().setPrice(tick('XAU/USD', 2340));
    useStore.getState().setPrice(tick('XAU/USD', 2345));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2345);
  });

  it('setPrice stores multiple symbols independently', () => {
    useStore.getState().setPrice(tick('XAU/USD', 2340));
    useStore.getState().setPrice(tick('EUR/USD', 1.085));
    const prices = useStore.getState().prices;
    expect(prices['XAU/USD']?.mid).toBe(2340);
    expect(prices['EUR/USD']?.mid).toBe(1.085);
  });

  it('price history accumulates ticks', () => {
    for (let i = 0; i < 5; i++) {
      useStore.getState().setPrice(tick('XAU/USD', 2340 + i));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(5);
  });

  it('price history caps at 200 entries', () => {
    for (let i = 0; i < 250; i++) {
      useStore.getState().setPrice(tick('XAU/USD', 2340 + i));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(200);
  });

  it('price history keeps most recent ticks', () => {
    for (let i = 0; i < 210; i++) {
      useStore.getState().setPrice(tick('XAU/USD', 2340 + i));
    }
    const history = useStore.getState().priceHistory['XAU/USD']!;
    expect(history[history.length - 1].mid).toBe(2340 + 209);
  });

  it('price history is per-symbol', () => {
    useStore.getState().setPrice(tick('XAU/USD', 2340));
    useStore.getState().setPrice(tick('EUR/USD', 1.085));
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(1);
    expect(useStore.getState().priceHistory['EUR/USD']).toHaveLength(1);
  });

  it('tick stores bid/ask/spread correctly', () => {
    const t = tick('XAU/USD', 2340);
    useStore.getState().setPrice(t);
    const stored = useStore.getState().prices['XAU/USD']!;
    expect(stored.bid).toBe(t.bid);
    expect(stored.ask).toBe(t.ask);
    expect(stored.spread).toBe(t.spread);
  });

  it('tick stores timestamp', () => {
    const t = tick('XAU/USD', 2340);
    useStore.getState().setPrice(t);
    expect(useStore.getState().prices['XAU/USD']?.timestamp).toBe(t.timestamp);
  });

  it('negative change_pct stored correctly', () => {
    useStore.getState().setPrice(tick('XAU/USD', 2340, -1.2));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(-1.2);
  });
});

// ─── Position slice ───────────────────────────────────────────────────────────

describe('position slice', () => {
  const pos = (id: string, symbol = 'XAU/USD'): Position => ({
    id, symbol, side: 'long', size: 1, entry_price: 2340, current_price: 2350,
    unrealized_pnl: 100, realized_pnl: 0, opened_at: new Date().toISOString(),
  });

  it('starts with empty positions', () => {
    expect(useStore.getState().positions).toEqual([]);
  });

  it('setPositions replaces all', () => {
    useStore.getState().setPositions([pos('1'), pos('2')]);
    expect(useStore.getState().positions).toHaveLength(2);
  });

  it('setPositions with empty array clears', () => {
    useStore.getState().setPositions([pos('1')]);
    useStore.getState().setPositions([]);
    expect(useStore.getState().positions).toHaveLength(0);
  });

  it('upsertPosition adds new position', () => {
    useStore.getState().upsertPosition(pos('1'));
    expect(useStore.getState().positions).toHaveLength(1);
  });

  it('upsertPosition updates existing position', () => {
    useStore.getState().upsertPosition(pos('1'));
    const updated = { ...pos('1'), unrealized_pnl: 500 };
    useStore.getState().upsertPosition(updated);
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].unrealized_pnl).toBe(500);
  });

  it('upsertPosition adds multiple positions', () => {
    useStore.getState().upsertPosition(pos('1'));
    useStore.getState().upsertPosition(pos('2'));
    expect(useStore.getState().positions).toHaveLength(2);
  });

  it('removePosition removes by id', () => {
    useStore.getState().setPositions([pos('1'), pos('2')]);
    useStore.getState().removePosition('1');
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].id).toBe('2');
  });

  it('removePosition with unknown id is safe', () => {
    useStore.getState().setPositions([pos('1')]);
    useStore.getState().removePosition('999');
    expect(useStore.getState().positions).toHaveLength(1);
  });

  it('position side can be short', () => {
    const short = { ...pos('1'), side: 'short' as const };
    useStore.getState().upsertPosition(short);
    expect(useStore.getState().positions[0].side).toBe('short');
  });
});

// ─── Signal slice ─────────────────────────────────────────────────────────────

describe('signal slice', () => {
  const sig = (id: string): Signal => ({
    id, symbol: 'XAU/USD', direction: 'long', confidence: 0.85,
    model: 'XGBoost', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
    generated_at: new Date().toISOString(), status: 'active',
  });

  it('starts with empty signals', () => {
    expect(useStore.getState().signals).toEqual([]);
  });

  it('setSignals replaces all', () => {
    useStore.getState().setSignals([sig('1'), sig('2')]);
    expect(useStore.getState().signals).toHaveLength(2);
  });

  it('addSignal prepends to list', () => {
    useStore.getState().setSignals([sig('1')]);
    useStore.getState().addSignal(sig('2'));
    expect(useStore.getState().signals[0].id).toBe('2');
  });

  it('addSignal caps at 50', () => {
    for (let i = 0; i < 60; i++) useStore.getState().addSignal(sig(String(i)));
    expect(useStore.getState().signals).toHaveLength(50);
  });

  it('signal direction can be short', () => {
    useStore.getState().addSignal({ ...sig('1'), direction: 'short' });
    expect(useStore.getState().signals[0].direction).toBe('short');
  });

  it('signal direction can be neutral', () => {
    useStore.getState().addSignal({ ...sig('1'), direction: 'neutral' });
    expect(useStore.getState().signals[0].direction).toBe('neutral');
  });

  it('signal status can be triggered', () => {
    useStore.getState().addSignal({ ...sig('1'), status: 'triggered' });
    expect(useStore.getState().signals[0].status).toBe('triggered');
  });

  it('setSignals with empty array clears', () => {
    useStore.getState().setSignals([sig('1')]);
    useStore.getState().setSignals([]);
    expect(useStore.getState().signals).toHaveLength(0);
  });
});

// ─── Account slice ────────────────────────────────────────────────────────────

describe('account slice', () => {
  const acc: AccountMetrics = {
    balance: 100_000, equity: 102_000, margin_used: 4_000, margin_free: 98_000,
    margin_level: 2550, daily_pnl: 500, daily_pnl_pct: 0.5, total_pnl: 2_000,
    win_rate: 0.65, sharpe_ratio: 1.8, max_drawdown: 0.04, open_trades: 2,
  };

  it('starts with null account', () => {
    expect(useStore.getState().account).toBeNull();
  });

  it('setAccount stores metrics', () => {
    useStore.getState().setAccount(acc);
    expect(useStore.getState().account).toEqual(acc);
  });

  it('setAccount overwrites previous', () => {
    useStore.getState().setAccount(acc);
    useStore.getState().setAccount({ ...acc, balance: 200_000 });
    expect(useStore.getState().account?.balance).toBe(200_000);
  });

  it('negative daily_pnl stored correctly', () => {
    useStore.getState().setAccount({ ...acc, daily_pnl: -300, daily_pnl_pct: -0.3 });
    expect(useStore.getState().account?.daily_pnl).toBe(-300);
  });
});

// ─── WebSocket slice ──────────────────────────────────────────────────────────

describe('ws slice', () => {
  it('starts disconnected', () => {
    expect(useStore.getState().wsStatus).toBe('disconnected');
  });

  it('setWsStatus updates status', () => {
    useStore.getState().setWsStatus('connected');
    expect(useStore.getState().wsStatus).toBe('connected');
  });

  it('setWsStatus to error', () => {
    useStore.getState().setWsStatus('error');
    expect(useStore.getState().wsStatus).toBe('error');
  });

  it('setWsStatus to connecting', () => {
    useStore.getState().setWsStatus('connecting');
    expect(useStore.getState().wsStatus).toBe('connecting');
  });

  it('setHeartbeat stores timestamp', () => {
    const ts = Date.now();
    useStore.getState().setHeartbeat(ts);
    expect(useStore.getState().lastHeartbeat).toBe(ts);
  });

  it('lastHeartbeat starts null', () => {
    expect(useStore.getState().lastHeartbeat).toBeNull();
  });
});

// ─── Selectors ────────────────────────────────────────────────────────────────

import {
  selectToken, selectIsAuth, selectPositions, selectSignals,
  selectAccount, selectWsStatus, selectPrice, selectPriceHistory,
} from '../store';

describe('selectors', () => {
  it('selectToken returns token', () => {
    useStore.getState().setAuth('tok', { id: '1', email: 'a@b.com', username: 'u', role: 'user' });
    expect(selectToken(useStore.getState())).toBe('tok');
  });

  it('selectToken returns null when not authenticated', () => {
    expect(selectToken(useStore.getState())).toBeNull();
  });

  it('selectIsAuth returns false initially', () => {
    expect(selectIsAuth(useStore.getState())).toBe(false);
  });

  it('selectIsAuth returns true after setAuth', () => {
    useStore.getState().setAuth('tok', { id: '1', email: 'a@b.com', username: 'u', role: 'user' });
    expect(selectIsAuth(useStore.getState())).toBe(true);
  });

  it('selectPositions returns empty array initially', () => {
    expect(selectPositions(useStore.getState())).toEqual([]);
  });

  it('selectSignals returns empty array initially', () => {
    expect(selectSignals(useStore.getState())).toEqual([]);
  });

  it('selectAccount returns null initially', () => {
    expect(selectAccount(useStore.getState())).toBeNull();
  });

  it('selectWsStatus returns disconnected initially', () => {
    expect(selectWsStatus(useStore.getState())).toBe('disconnected');
  });

  it('selectPrice returns undefined for unknown symbol', () => {
    expect(selectPrice('UNKNOWN')(useStore.getState())).toBeUndefined();
  });

  it('selectPriceHistory returns empty array for unknown symbol', () => {
    expect(selectPriceHistory('UNKNOWN')(useStore.getState())).toEqual([]);
  });

  it('selectPrice returns tick after setPrice', () => {
    useStore.getState().setPrice({ symbol: 'XAU/USD', bid: 2339, ask: 2341, mid: 2340, spread: 2, timestamp: 1, change_pct: 0 });
    expect(selectPrice('XAU/USD')(useStore.getState())?.mid).toBe(2340);
  });

  it('selectPriceHistory returns history after ticks', () => {
    useStore.getState().setPrice({ symbol: 'XAU/USD', bid: 2339, ask: 2341, mid: 2340, spread: 2, timestamp: 1, change_pct: 0 });
    expect(selectPriceHistory('XAU/USD')(useStore.getState())).toHaveLength(1);
  });
});

// ─── UI preferences slice ─────────────────────────────────────────────────────

describe('ui slice — favorites', () => {
  beforeEach(() => {
    useStore.setState({ favorites: [], collapsedGroups: [], recentPaths: [] });
  });

  it('starts with no favorites', () => {
    expect(useStore.getState().favorites).toEqual([]);
  });

  it('toggleFavorite pins a path', () => {
    useStore.getState().toggleFavorite('/trade');
    expect(useStore.getState().favorites).toEqual(['/trade']);
  });

  it('toggleFavorite unpins an already-pinned path', () => {
    useStore.getState().toggleFavorite('/trade');
    useStore.getState().toggleFavorite('/trade');
    expect(useStore.getState().favorites).toEqual([]);
  });

  it('keeps multiple favorites in insertion order', () => {
    useStore.getState().toggleFavorite('/trade');
    useStore.getState().toggleFavorite('/portfolio');
    expect(useStore.getState().favorites).toEqual(['/trade', '/portfolio']);
  });

  it('removes only the targeted favorite', () => {
    useStore.getState().toggleFavorite('/trade');
    useStore.getState().toggleFavorite('/portfolio');
    useStore.getState().toggleFavorite('/trade');
    expect(useStore.getState().favorites).toEqual(['/portfolio']);
  });
});

describe('ui slice — collapsed groups', () => {
  beforeEach(() => {
    useStore.setState({ favorites: [], collapsedGroups: [], recentPaths: [] });
  });

  it('toggleGroup collapses then expands a group', () => {
    useStore.getState().toggleGroup('analytics');
    expect(useStore.getState().collapsedGroups).toContain('analytics');
    useStore.getState().toggleGroup('analytics');
    expect(useStore.getState().collapsedGroups).not.toContain('analytics');
  });
});

describe('ui slice — recent paths', () => {
  beforeEach(() => {
    useStore.setState({ favorites: [], collapsedGroups: [], recentPaths: [] });
  });

  it('pushRecentPath prepends the newest path', () => {
    useStore.getState().pushRecentPath('/trade');
    useStore.getState().pushRecentPath('/portfolio');
    expect(useStore.getState().recentPaths[0]).toBe('/portfolio');
  });

  it('de-duplicates and moves a repeat visit to the front', () => {
    useStore.getState().pushRecentPath('/trade');
    useStore.getState().pushRecentPath('/portfolio');
    useStore.getState().pushRecentPath('/trade');
    expect(useStore.getState().recentPaths).toEqual(['/trade', '/portfolio']);
  });

  it('is a no-op when the newest path is pushed again', () => {
    useStore.getState().pushRecentPath('/trade');
    const before = useStore.getState().recentPaths;
    useStore.getState().pushRecentPath('/trade');
    expect(useStore.getState().recentPaths).toBe(before);
  });

  it('caps the list at 6 entries', () => {
    for (const p of ['/a', '/b', '/c', '/d', '/e', '/f', '/g', '/h']) {
      useStore.getState().pushRecentPath(p);
    }
    expect(useStore.getState().recentPaths).toHaveLength(6);
    expect(useStore.getState().recentPaths[0]).toBe('/h');
  });
});
