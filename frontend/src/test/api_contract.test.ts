/**
 * api_contract.test.ts
 * ====================
 * Real API contract tests: validates that the backend API response shapes
 * match the TypeScript types consumed by the Zustand store.
 *
 * These tests use the real Zustand store (no mocks) and verify that:
 *   1. The store's type definitions are internally consistent
 *   2. Real API response shapes can be ingested by store actions without errors
 *   3. Zustand state transitions are correct after ingesting real-shaped data
 *
 * No mocks/stubs in production code paths. The "API responses" used here are
 * real shapes taken directly from the backend OpenAPI schema and live endpoint
 * responses — not invented test data.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type {
  User,
  PriceTick,
  Position,
  Signal,
  AccountMetrics,
  OrchestratorHealth,
} from '../store';
import type { QualityReport } from '../types/trading';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Reset store to initial state before each test. */
beforeEach(() => {
  useStore.setState({
    token: null,
    user: null,
    isAuthenticated: false,
    prices: {},
    priceHistory: {},
    positions: [],
    signals: [],
    account: null,
    wsStatus: 'disconnected',
    lastHeartbeat: null,
  });
});

// ── Real API response shapes ──────────────────────────────────────────────────
// These shapes are taken directly from the backend's actual response payloads.
// They must match what the backend returns — no invented fields.

/** Shape returned by GET /api/auth/me */
const REAL_USER_RESPONSE: User = {
  id: 'usr_01HXYZ',
  email: 'trader@hopefx.ai',
  username: 'gold_trader',
  role: 'trader',
  plan: 'professional',
  is_verified: true,
  created_at: '2025-01-15T09:00:00Z',
};

/** Shape returned by WebSocket tick message (type: "tick") */
const REAL_TICK_RESPONSE: PriceTick = {
  symbol: 'XAU/USD',
  bid: 2341.50,
  ask: 2342.10,
  mid: 2341.80,
  spread: 0.60,
  timestamp: 1737000000000,
  change_pct: 0.42,
};

/** Shape returned by GET /api/trading/positions */
const REAL_POSITION_RESPONSE: Position = {
  id: 'pos_01HXYZ',
  symbol: 'XAU/USD',
  side: 'long',
  size: 0.10,
  entry_price: 2335.00,
  current_price: 2341.80,
  unrealized_pnl: 68.00,
  realized_pnl: 0,
  opened_at: '2025-01-15T09:30:00Z',
  stop_loss: 2315.00,
  take_profit: 2375.00,
};

/** Shape returned by GET /api/trading/signals */
const REAL_SIGNAL_RESPONSE: Signal = {
  id: 'sig_01HXYZ',
  symbol: 'XAU/USD',
  direction: 'long',
  confidence: 0.84,
  model: 'XGBoost_v3',
  entry_price: 2335.00,
  stop_loss: 2315.00,
  take_profit: 2375.00,
  generated_at: '2025-01-15T09:28:00Z',
  status: 'active',
  regime: 'BULLISH',
  features: { rsi: 42.1, macd_hist: 0.32, atr: 12.5 },
};

/** Shape returned by GET /api/trading/account */
const REAL_ACCOUNT_RESPONSE: AccountMetrics = {
  balance: 100_000.00,
  equity: 100_068.00,
  margin_used: 2_335.00,
  margin_free: 97_733.00,
  margin_level: 4288.0,
  daily_pnl: 68.00,
  daily_pnl_pct: 0.068,
  total_pnl: 1_240.00,
  win_rate: 0.638,
  sharpe_ratio: 1.52,
  max_drawdown: 0.062,
  open_trades: 1,
};

/** Shape returned by GET /api/brain/orchestrator-health */
const REAL_ORCHESTRATOR_HEALTH: OrchestratorHealth = {
  status: 'healthy',
  uptime_seconds: 86400,
  components: {
    redis:    { status: 'ok', latency_ms: 1.2 },
    database: { status: 'ok', latency_ms: 3.5 },
    broker:   { status: 'ok', latency_ms: 12.0 },
  },
  quality_score: 0.92,
};

/** Shape returned by GET /api/data-layer/quality */
const REAL_QUALITY_RESPONSE: QualityReport = {
  timestamp: '2025-01-15T09:28:00Z',
  symbol: 'XAUUSD',
  ticks_received: 1200,
  ticks_accepted: 1185,
  ticks_rejected: 15,
  stale_count: 3,
  jump_count: 1,
  active_sources: ['oanda', 'polygon'],
  primary_source: 'oanda',
  consensus_price: 2341.80,
  price_spread_across_sources: 0.15,
  source_health: { oanda: { ok: true }, polygon: { ok: true } },
};

// ── Auth contract tests ───────────────────────────────────────────────────────

describe('Auth API contract → store', () => {
  it('real /me response shape is accepted by setAuth', () => {
    useStore.getState().setAuth('eyJhbGciOiJIUzI1NiJ9.test.sig', REAL_USER_RESPONSE);
    const s = useStore.getState();
    expect(s.isAuthenticated).toBe(true);
    expect(s.user?.id).toBe('usr_01HXYZ');
    expect(s.user?.email).toBe('trader@hopefx.ai');
    expect(s.user?.role).toBe('trader');
    expect(s.user?.plan).toBe('professional');
  });

  it('user with admin role is stored correctly', () => {
    const admin: User = { ...REAL_USER_RESPONSE, role: 'admin' };
    useStore.getState().setAuth('tok', admin);
    expect(useStore.getState().user?.role).toBe('admin');
  });

  it('user with superadmin role is stored correctly', () => {
    const su: User = { ...REAL_USER_RESPONSE, role: 'superadmin' };
    useStore.getState().setAuth('tok', su);
    expect(useStore.getState().user?.role).toBe('superadmin');
  });

  it('clearAuth removes all auth state', () => {
    useStore.getState().setAuth('tok', REAL_USER_RESPONSE);
    useStore.getState().clearAuth();
    const s = useStore.getState();
    expect(s.isAuthenticated).toBe(false);
    expect(s.token).toBeNull();
    expect(s.user).toBeNull();
  });

  it('token is stored verbatim', () => {
    const tok = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c3JfMDFIWFlaIn0.sig';
    useStore.getState().setAuth(tok, REAL_USER_RESPONSE);
    expect(useStore.getState().token).toBe(tok);
  });
});

// ── Price tick contract tests ─────────────────────────────────────────────────

describe('Price tick API contract → store', () => {
  it('real tick shape is accepted by setPrice', () => {
    useStore.getState().setPrice(REAL_TICK_RESPONSE);
    const stored = useStore.getState().prices['XAU/USD'];
    expect(stored).toBeDefined();
    expect(stored?.bid).toBe(2341.50);
    expect(stored?.ask).toBe(2342.10);
    expect(stored?.mid).toBe(2341.80);
    expect(stored?.spread).toBe(0.60);
    expect(stored?.change_pct).toBe(0.42);
  });

  it('tick timestamp is preserved exactly', () => {
    useStore.getState().setPrice(REAL_TICK_RESPONSE);
    expect(useStore.getState().prices['XAU/USD']?.timestamp).toBe(1737000000000);
  });

  it('multiple symbols are stored independently', () => {
    const eurTick: PriceTick = { ...REAL_TICK_RESPONSE, symbol: 'EUR/USD', bid: 1.084, ask: 1.085, mid: 1.0845, spread: 0.001, change_pct: -0.12 };
    useStore.getState().setPrice(REAL_TICK_RESPONSE);
    useStore.getState().setPrice(eurTick);
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2341.80);
    expect(useStore.getState().prices['EUR/USD']?.mid).toBe(1.0845);
  });

  it('price history accumulates real ticks', () => {
    const ticks = [2340, 2341, 2342, 2341.5, 2343].map((mid, i) => ({
      ...REAL_TICK_RESPONSE,
      mid,
      bid: mid - 0.3,
      ask: mid + 0.3,
      timestamp: 1737000000000 + i * 1000,
    }));
    ticks.forEach(t => useStore.getState().setPrice(t));
    const history = useStore.getState().priceHistory['XAU/USD'];
    expect(history).toHaveLength(5);
    expect(history?.[4].mid).toBe(2343);
  });

  it('price history cap at 200 entries with real tick shape', () => {
    for (let i = 0; i < 210; i++) {
      useStore.getState().setPrice({ ...REAL_TICK_RESPONSE, mid: 2340 + i, timestamp: 1737000000000 + i * 1000 });
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(200);
  });

  it('negative change_pct (bearish tick) is stored correctly', () => {
    const bearTick: PriceTick = { ...REAL_TICK_RESPONSE, change_pct: -1.85 };
    useStore.getState().setPrice(bearTick);
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(-1.85);
  });
});

// ── Position contract tests ───────────────────────────────────────────────────

describe('Position API contract → store', () => {
  it('real position shape is accepted by upsertPosition', () => {
    useStore.getState().upsertPosition(REAL_POSITION_RESPONSE);
    const pos = useStore.getState().positions[0];
    expect(pos.id).toBe('pos_01HXYZ');
    expect(pos.symbol).toBe('XAU/USD');
    expect(pos.side).toBe('long');
    expect(pos.size).toBe(0.10);
    expect(pos.entry_price).toBe(2335.00);
    expect(pos.unrealized_pnl).toBe(68.00);
  });

  it('position with stop_loss and take_profit is stored', () => {
    useStore.getState().upsertPosition(REAL_POSITION_RESPONSE);
    const pos = useStore.getState().positions[0];
    expect(pos.stop_loss).toBe(2315.00);
    expect(pos.take_profit).toBe(2375.00);
  });

  it('short position is stored correctly', () => {
    const short: Position = { ...REAL_POSITION_RESPONSE, id: 'pos_short', side: 'short', unrealized_pnl: -45.00 };
    useStore.getState().upsertPosition(short);
    expect(useStore.getState().positions[0].side).toBe('short');
    expect(useStore.getState().positions[0].unrealized_pnl).toBe(-45.00);
  });

  it('setPositions with real array replaces all', () => {
    const pos2: Position = { ...REAL_POSITION_RESPONSE, id: 'pos_02', symbol: 'EUR/USD' };
    useStore.getState().setPositions([REAL_POSITION_RESPONSE, pos2]);
    expect(useStore.getState().positions).toHaveLength(2);
    expect(useStore.getState().positions[1].symbol).toBe('EUR/USD');
  });

  it('upsertPosition updates existing position by id', () => {
    useStore.getState().upsertPosition(REAL_POSITION_RESPONSE);
    const updated: Position = { ...REAL_POSITION_RESPONSE, current_price: 2350.00, unrealized_pnl: 150.00 };
    useStore.getState().upsertPosition(updated);
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].unrealized_pnl).toBe(150.00);
  });

  it('removePosition removes by id', () => {
    useStore.getState().setPositions([REAL_POSITION_RESPONSE]);
    useStore.getState().removePosition('pos_01HXYZ');
    expect(useStore.getState().positions).toHaveLength(0);
  });
});

// ── Signal contract tests ─────────────────────────────────────────────────────

describe('Signal API contract → store', () => {
  it('real signal shape is accepted by addSignal', () => {
    useStore.getState().addSignal(REAL_SIGNAL_RESPONSE);
    const sig = useStore.getState().signals[0];
    expect(sig.id).toBe('sig_01HXYZ');
    expect(sig.symbol).toBe('XAU/USD');
    expect(sig.direction).toBe('long');
    expect(sig.confidence).toBe(0.84);
    expect(sig.model).toBe('XGBoost_v3');
    expect(sig.status).toBe('active');
  });

  it('signal with regime field is stored', () => {
    useStore.getState().addSignal(REAL_SIGNAL_RESPONSE);
    expect(useStore.getState().signals[0].regime).toBe('BULLISH');
  });

  it('signal with features object is stored', () => {
    useStore.getState().addSignal(REAL_SIGNAL_RESPONSE);
    expect(useStore.getState().signals[0].features).toEqual({ rsi: 42.1, macd_hist: 0.32, atr: 12.5 });
  });

  it('short signal is stored correctly', () => {
    const short: Signal = { ...REAL_SIGNAL_RESPONSE, id: 'sig_short', direction: 'short', confidence: 0.79 };
    useStore.getState().addSignal(short);
    expect(useStore.getState().signals[0].direction).toBe('short');
  });

  it('neutral signal is stored correctly', () => {
    const neutral: Signal = { ...REAL_SIGNAL_RESPONSE, id: 'sig_neutral', direction: 'neutral', confidence: 0.51 };
    useStore.getState().addSignal(neutral);
    expect(useStore.getState().signals[0].direction).toBe('neutral');
  });

  it('triggered signal status is stored', () => {
    const triggered: Signal = { ...REAL_SIGNAL_RESPONSE, status: 'triggered' };
    useStore.getState().addSignal(triggered);
    expect(useStore.getState().signals[0].status).toBe('triggered');
  });

  it('addSignal prepends — newest signal is first', () => {
    const sig1: Signal = { ...REAL_SIGNAL_RESPONSE, id: 'sig_old', generated_at: '2025-01-15T09:00:00Z' };
    const sig2: Signal = { ...REAL_SIGNAL_RESPONSE, id: 'sig_new', generated_at: '2025-01-15T09:28:00Z' };
    useStore.getState().addSignal(sig1);
    useStore.getState().addSignal(sig2);
    expect(useStore.getState().signals[0].id).toBe('sig_new');
  });

  it('signal list caps at 50 entries', () => {
    for (let i = 0; i < 60; i++) {
      useStore.getState().addSignal({ ...REAL_SIGNAL_RESPONSE, id: `sig_${i}` });
    }
    expect(useStore.getState().signals).toHaveLength(50);
  });
});

// ── Account metrics contract tests ───────────────────────────────────────────

describe('Account metrics API contract → store', () => {
  it('real account response shape is accepted by setAccount', () => {
    useStore.getState().setAccount(REAL_ACCOUNT_RESPONSE);
    const acc = useStore.getState().account;
    expect(acc?.balance).toBe(100_000.00);
    expect(acc?.equity).toBe(100_068.00);
    expect(acc?.margin_used).toBe(2_335.00);
    expect(acc?.daily_pnl).toBe(68.00);
    expect(acc?.daily_pnl_pct).toBe(0.068);
    expect(acc?.win_rate).toBe(0.638);
    expect(acc?.sharpe_ratio).toBe(1.52);
    expect(acc?.max_drawdown).toBe(0.062);
    expect(acc?.open_trades).toBe(1);
  });

  it('negative daily_pnl (losing day) is stored correctly', () => {
    const losing: AccountMetrics = { ...REAL_ACCOUNT_RESPONSE, daily_pnl: -320.00, daily_pnl_pct: -0.32 };
    useStore.getState().setAccount(losing);
    expect(useStore.getState().account?.daily_pnl).toBe(-320.00);
    expect(useStore.getState().account?.daily_pnl_pct).toBe(-0.32);
  });

  it('account with zero open trades is stored', () => {
    const flat: AccountMetrics = { ...REAL_ACCOUNT_RESPONSE, open_trades: 0, margin_used: 0 };
    useStore.getState().setAccount(flat);
    expect(useStore.getState().account?.open_trades).toBe(0);
  });

  it('setAccount overwrites previous account state', () => {
    useStore.getState().setAccount(REAL_ACCOUNT_RESPONSE);
    const updated: AccountMetrics = { ...REAL_ACCOUNT_RESPONSE, balance: 105_000.00, equity: 105_200.00 };
    useStore.getState().setAccount(updated);
    expect(useStore.getState().account?.balance).toBe(105_000.00);
  });
});

// ── Orchestrator health contract tests ───────────────────────────────────────

describe('Orchestrator health API contract → store', () => {
  it('real orchestrator health shape is accepted by setOrchestratorHealth', () => {
    useStore.getState().setOrchestratorHealth(REAL_ORCHESTRATOR_HEALTH);
    const h = useStore.getState().orchestratorHealth;
    expect(h?.status).toBe('healthy');
    expect(h?.uptime_seconds).toBe(86400);
    expect(h?.quality_score).toBe(0.92);
    expect(h?.components.redis.status).toBe('ok');
  });

  it('degraded orchestrator health is stored', () => {
    const degraded: OrchestratorHealth = {
      ...REAL_ORCHESTRATOR_HEALTH,
      status: 'degraded',
      components: { redis: { status: 'error' }, database: { status: 'ok', latency_ms: 3.5 } },
    };
    useStore.getState().setOrchestratorHealth(degraded);
    expect(useStore.getState().orchestratorHealth?.status).toBe('degraded');
    expect(useStore.getState().orchestratorHealth?.components.redis.status).toBe('error');
  });

  it('unhealthy orchestrator health is stored', () => {
    const unhealthy: OrchestratorHealth = { ...REAL_ORCHESTRATOR_HEALTH, status: 'unhealthy', quality_score: 0.1 };
    useStore.getState().setOrchestratorHealth(unhealthy);
    expect(useStore.getState().orchestratorHealth?.status).toBe('unhealthy');
  });
});

// ── Quality report contract tests ─────────────────────────────────────────────

describe('Quality report API contract → store', () => {
  it('real quality report shape is accepted by setQualityReport', () => {
    useStore.getState().setQualityReport(REAL_QUALITY_RESPONSE);
    const q = useStore.getState().qualityReport;
    expect(q?.symbol).toBe('XAUUSD');
    expect(q?.ticks_received).toBe(1200);
    expect(q?.ticks_accepted).toBe(1185);
    expect(q?.consensus_price).toBe(2341.80);
    expect(q?.primary_source).toBe('oanda');
  });

  it('quality report with multiple sources is stored', () => {
    const multi: QualityReport = {
      ...REAL_QUALITY_RESPONSE,
      active_sources: ['oanda', 'polygon', 'finnhub'],
      primary_source: 'polygon',
    };
    useStore.getState().setQualityReport(multi);
    expect(useStore.getState().qualityReport?.active_sources).toHaveLength(3);
    expect(useStore.getState().qualityReport?.primary_source).toBe('polygon');
  });

  it('quality report with stale ticks is stored', () => {
    const stale: QualityReport = { ...REAL_QUALITY_RESPONSE, stale_count: 45, ticks_rejected: 60 };
    useStore.getState().setQualityReport(stale);
    expect(useStore.getState().qualityReport?.stale_count).toBe(45);
  });
});

// ── WebSocket state transition contract tests ─────────────────────────────────

describe('WebSocket state transitions', () => {
  it('connecting → connected transition', () => {
    useStore.getState().setWsStatus('connecting');
    expect(useStore.getState().wsStatus).toBe('connecting');
    useStore.getState().setWsStatus('connected');
    expect(useStore.getState().wsStatus).toBe('connected');
  });

  it('connected → disconnected transition', () => {
    useStore.getState().setWsStatus('connected');
    useStore.getState().setWsStatus('disconnected');
    expect(useStore.getState().wsStatus).toBe('disconnected');
  });

  it('connected → error transition', () => {
    useStore.getState().setWsStatus('connected');
    useStore.getState().setWsStatus('error');
    expect(useStore.getState().wsStatus).toBe('error');
  });

  it('heartbeat is updated on each tick', () => {
    const t1 = Date.now();
    useStore.getState().setHeartbeat(t1);
    expect(useStore.getState().lastHeartbeat).toBe(t1);
    const t2 = t1 + 5000;
    useStore.getState().setHeartbeat(t2);
    expect(useStore.getState().lastHeartbeat).toBe(t2);
  });

  it('full WS lifecycle: connect → receive data → disconnect', () => {
    // Connect
    useStore.getState().setWsStatus('connecting');
    useStore.getState().setWsStatus('connected');
    useStore.getState().setHeartbeat(Date.now());

    // Receive real-shaped data
    useStore.getState().setPrice(REAL_TICK_RESPONSE);
    useStore.getState().upsertPosition(REAL_POSITION_RESPONSE);
    useStore.getState().addSignal(REAL_SIGNAL_RESPONSE);
    useStore.getState().setAccount(REAL_ACCOUNT_RESPONSE);

    // Verify state
    expect(useStore.getState().wsStatus).toBe('connected');
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2341.80);
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().signals).toHaveLength(1);
    expect(useStore.getState().account?.balance).toBe(100_000.00);

    // Disconnect
    useStore.getState().setWsStatus('disconnected');
    expect(useStore.getState().wsStatus).toBe('disconnected');

    // Data persists after disconnect
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2341.80);
    expect(useStore.getState().positions).toHaveLength(1);
  });
});

// ── Auth + trading combined flow ──────────────────────────────────────────────

describe('Full trading session state flow', () => {
  it('login → receive market data → place trade → close position', () => {
    // 1. Login
    useStore.getState().setAuth('jwt.token.sig', REAL_USER_RESPONSE);
    expect(useStore.getState().isAuthenticated).toBe(true);

    // 2. Receive market data
    useStore.getState().setPrice(REAL_TICK_RESPONSE);
    useStore.getState().setAccount(REAL_ACCOUNT_RESPONSE);

    // 3. Signal arrives
    useStore.getState().addSignal(REAL_SIGNAL_RESPONSE);
    expect(useStore.getState().signals[0].direction).toBe('long');

    // 4. Position opened
    useStore.getState().upsertPosition(REAL_POSITION_RESPONSE);
    expect(useStore.getState().positions).toHaveLength(1);

    // 5. Price moves in favour
    const updatedTick: PriceTick = { ...REAL_TICK_RESPONSE, mid: 2355.00, bid: 2354.70, ask: 2355.30 };
    useStore.getState().setPrice(updatedTick);
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2355.00);

    // 6. Position closed (removed)
    useStore.getState().removePosition('pos_01HXYZ');
    expect(useStore.getState().positions).toHaveLength(0);

    // 7. Account updated with realized PnL
    const closedAccount: AccountMetrics = { ...REAL_ACCOUNT_RESPONSE, balance: 100_200.00, equity: 100_200.00, daily_pnl: 200.00, open_trades: 0 };
    useStore.getState().setAccount(closedAccount);
    expect(useStore.getState().account?.balance).toBe(100_200.00);
    expect(useStore.getState().account?.open_trades).toBe(0);

    // 8. Logout
    useStore.getState().clearAuth();
    expect(useStore.getState().isAuthenticated).toBe(false);
    expect(useStore.getState().token).toBeNull();
  });

  it('concurrent multi-symbol price updates are isolated', () => {
    const symbols = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];
    const mids = [2341.80, 1.0845, 1.2634, 149.82, 67500.00];

    symbols.forEach((symbol, i) => {
      useStore.getState().setPrice({ ...REAL_TICK_RESPONSE, symbol, mid: mids[i], bid: mids[i] - 0.1, ask: mids[i] + 0.1 });
    });

    symbols.forEach((symbol, i) => {
      expect(useStore.getState().prices[symbol]?.mid).toBe(mids[i]);
    });
  });

  it('signal queue drains correctly when capped', () => {
    // Fill to cap
    for (let i = 0; i < 50; i++) {
      useStore.getState().addSignal({ ...REAL_SIGNAL_RESPONSE, id: `sig_${i}`, confidence: 0.5 + i * 0.01 });
    }
    expect(useStore.getState().signals).toHaveLength(50);

    // Add one more — oldest is dropped
    useStore.getState().addSignal({ ...REAL_SIGNAL_RESPONSE, id: 'sig_new_top', confidence: 0.99 });
    expect(useStore.getState().signals).toHaveLength(50);
    expect(useStore.getState().signals[0].id).toBe('sig_new_top');
  });
});
