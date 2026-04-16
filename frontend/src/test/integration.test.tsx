/**
 * Integration tests — store + components working together.
 * ~80 tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';
import type { PriceTick, Position, Signal, AccountMetrics } from '../store';
import * as useApiModule from '../hooks/useApi';

/** Build a minimal valid JWT with exp 1 hour in the future. */
function makeMockJwt(overrides: Record<string, unknown> = {}): string {
  const header  = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).replace(/=/g, '');
  const payload = btoa(JSON.stringify({
    sub: '1', type: 'access',
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...overrides,
  })).replace(/=/g, '');
  return `${header}.${payload}.sig`;
}

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({ send: vi.fn() })),
}));
vi.mock('../hooks/useApi', () => ({
  tradingApi: {
    positions:         vi.fn().mockResolvedValue({ data: { positions: [] } }),
    signals:           vi.fn().mockResolvedValue({ data: { signals: [] } }),
    account:           vi.fn().mockResolvedValue({ data: null }),
    ohlcv:             vi.fn().mockResolvedValue({ data: [] }),
    placeOrder:        vi.fn().mockResolvedValue({ data: {} }),
    closePosition:     vi.fn().mockResolvedValue({ data: {} }),
    closeAllPositions: vi.fn().mockResolvedValue({ data: {} }),
    trades:            vi.fn().mockResolvedValue({ data: { trades: [] } }),
    regime:            vi.fn().mockResolvedValue({ data: { regime: 'BULLISH', confidence: 0.82, volatility: 'LOW', trend: 'UP' } }),
    brainState:        vi.fn().mockResolvedValue({ data: { status: 'active', mode: 'live', active_strategies: ['momentum'] } }),
    emergencyStop:     vi.fn().mockResolvedValue({ data: {} }),
    aiAnalysis:        vi.fn().mockResolvedValue({ data: { direction: 'long', confidence: 0.78, reasoning: 'Bullish momentum' } }),
    riskMetrics:       vi.fn().mockResolvedValue({ data: {} }),
  },
  mlApi: {
    accuracy: vi.fn().mockResolvedValue({ data: { models: [] } }),
    predict:  vi.fn().mockResolvedValue({ data: {} }),
    models:   vi.fn().mockResolvedValue({ data: [] }),
    features: vi.fn().mockResolvedValue({ data: { features: [] } }),
  },
  mlExtendedApi: {
    health:      vi.fn().mockResolvedValue({ data: { status: 'ok', model_loaded: true } }),
    retrain:     vi.fn().mockResolvedValue({ data: {} }),
    filterStats: vi.fn().mockResolvedValue({ data: {} }),
    rlStatus:    vi.fn().mockResolvedValue({ data: {} }),
    rlTrain:     vi.fn().mockResolvedValue({ data: {} }),
    walkForward: vi.fn().mockResolvedValue({ data: {} }),
    explain:     vi.fn().mockResolvedValue({ data: {} }),
  },
  // authApi.me must return a resolved Promise — AuthGuard calls .me().then(...)
  // on every mount to sync the role from the server.
  authApi: {
    login:  vi.fn(),
    logout: vi.fn().mockResolvedValue({ data: {} }),
    me:     vi.fn().mockResolvedValue({ data: { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' } }),
  },
  backtestApi: { run: vi.fn().mockResolvedValue({ data: { job_id: 'bt-1', status: 'queued' } }), results: vi.fn().mockResolvedValue({ data: { job_id: 'bt-1', status: 'completed', metrics: { total_return: 0.12, sharpe: 1.4, max_drawdown: 0.08, win_rate: 0.58 }, equity_curve: [] } }), list: vi.fn().mockResolvedValue({ data: { backtests: [] } }) },
  performanceApi: {
    summary:     vi.fn().mockResolvedValue({ data: {} }),
    equity:      vi.fn().mockResolvedValue({ data: { curve: [] } }),
    equityCurve: vi.fn().mockResolvedValue({ data: [] }),
    trades:      vi.fn().mockResolvedValue({ data: { trades: [] } }),
    weekly:      vi.fn().mockResolvedValue({ data: {} }),
    weeklyList:  vi.fn().mockResolvedValue({ data: [] }),
  },
  signalsApi: {
    active:    vi.fn().mockResolvedValue({ data: [] }),
    latest:    vi.fn().mockResolvedValue({ data: [] }),
    history:   vi.fn().mockResolvedValue({ data: [] }),
    summary:   vi.fn().mockResolvedValue({ data: {} }),
    analytics: vi.fn().mockResolvedValue({ data: {} }),
    generate:  vi.fn().mockResolvedValue({ data: {} }),
    setAlert:  vi.fn().mockResolvedValue({ data: {} }),
  },
  dataLayerApi: {
    health:         vi.fn().mockResolvedValue({ data: {} }),
    tick:           vi.fn().mockResolvedValue({ data: {} }),
    sentiment:      vi.fn().mockResolvedValue({ data: { signal: { news_sentiment_score: 0, news_sentiment_momentum: 0, news_article_count_1h: 0, news_bullish_ratio: 0.5 }, recent_articles: [] } }),
    macro:          vi.fn().mockResolvedValue({ data: { calendar_features: {}, macro_features: {}, is_blackout: false, impact_score: 0, upcoming_events: [] } }),
    microstructure: vi.fn().mockResolvedValue({ data: { snapshot: null, features: {} } }),
    quality:        vi.fn().mockResolvedValue({ data: {} }),
    lineage:        vi.fn().mockResolvedValue({ data: [] }),
    feeds:          vi.fn().mockResolvedValue({ data: [] }),
  },
  calendarApi: {
    upcoming:    vi.fn().mockResolvedValue({ data: [] }),
    today:       vi.fn().mockResolvedValue({ data: [] }),
    highImpact:  vi.fn().mockResolvedValue({ data: [] }),
    autoPause:   vi.fn().mockResolvedValue({ data: {} }),
    setAutoPause: vi.fn().mockResolvedValue({ data: {} }),
    fomc:        vi.fn().mockResolvedValue({ data: [] }),
  },
  correlationApi: {
    matrix: vi.fn().mockResolvedValue({ data: { matrix: {}, symbols: [] } }),
    cot:    vi.fn().mockResolvedValue({ data: {} }),
  },
  walkForwardApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
    get:  vi.fn().mockResolvedValue({ data: {} }),
    run:  vi.fn().mockResolvedValue({ data: {} }),
  },
  leaderboardApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
  },
  accountsApi: {
    listSubAccounts:  vi.fn().mockResolvedValue({ data: [] }),
    createSubAccount: vi.fn().mockResolvedValue({ data: {} }),
    updateSubAccount: vi.fn().mockResolvedValue({ data: {} }),
    deleteSubAccount: vi.fn().mockResolvedValue({ data: {} }),
    listTeams:        vi.fn().mockResolvedValue({ data: [] }),
    createTeam:       vi.fn().mockResolvedValue({ data: {} }),
    inviteMember:     vi.fn().mockResolvedValue({ data: {} }),
    updateMember:     vi.fn().mockResolvedValue({ data: {} }),
    removeMember:     vi.fn().mockResolvedValue({ data: {} }),
  },
  auditApi: {
    list:   vi.fn().mockResolvedValue({ data: [] }),
    export: vi.fn().mockResolvedValue({ data: new Blob() }),
  },
  superadminApi: {
    overview:          vi.fn().mockResolvedValue({ data: {
      system_health: 'healthy', uptime_pct: 99.9, engine_status: 'running',
      total_users: 1000, active_users_24h: 50, new_users_7d: 10,
      revenue_mtd: 50000, revenue_currency: 'USD', total_trades_today: 200,
      open_positions: 5, active_sessions: 30, ml_model_accuracy: 87.5,
      signals_generated_today: 120,
    } }),
    users:             vi.fn().mockResolvedValue({ data: [] }),
    systemMetrics:     vi.fn().mockResolvedValue({ data: {} }),
    jobs:              vi.fn().mockResolvedValue({ data: [] }),
    apiKeyAudit:       vi.fn().mockResolvedValue({ data: [] }),
    revokeApiKey:      vi.fn().mockResolvedValue({ data: {} }),
    infraHealth:       vi.fn().mockResolvedValue({ data: { status: 'ok', services: [] } }),
    cacheStats:        vi.fn().mockResolvedValue({ data: { hit_rate: 0.95, memory_used: 128 } }),
    dbStats:           vi.fn().mockResolvedValue({ data: { connections: 5, query_time_ms: 2 } }),
    queueStats:        vi.fn().mockResolvedValue({ data: { queues: [] } }),
    flushCache:        vi.fn().mockResolvedValue({ data: {} }),
    mlStatus:          vi.fn().mockResolvedValue({ data: {} }),
    mlModels:          vi.fn().mockResolvedValue({ data: [] }),
    engineStatus:      vi.fn().mockResolvedValue({ data: {} }),
    revenueStats:      vi.fn().mockResolvedValue({ data: {} }),
    subscriptionStats: vi.fn().mockResolvedValue({ data: {} }),
    securityEvents:    vi.fn().mockResolvedValue({ data: [] }),
    blockedIPs:        vi.fn().mockResolvedValue({ data: [] }),
    activeSessions:    vi.fn().mockResolvedValue({ data: [] }),
    logs:              vi.fn().mockResolvedValue({ data: [] }),
    featureFlags:      vi.fn().mockResolvedValue({ data: [] }),
    auditLog:          vi.fn().mockResolvedValue({ data: [] }),
    brokerHealth:      vi.fn().mockResolvedValue({ data: [] }),
    tcaMetrics:        vi.fn().mockResolvedValue({ data: [] }),
    kycQueue:          vi.fn().mockResolvedValue({ data: [] }),
    amlAlerts:         vi.fn().mockResolvedValue({ data: [] }),
    circuitBreakers:   vi.fn().mockResolvedValue({ data: [] }),
    varMetrics:        vi.fn().mockResolvedValue({ data: {} }),
    tenants:           vi.fn().mockResolvedValue({ data: [] }),
  },
  api: {
    defaults: { baseURL: '/api', timeout: 15000, headers: { 'Content-Type': 'application/json' } },
    interceptors: { request: { handlers: [{}], use: vi.fn() }, response: { handlers: [{}], use: vi.fn() } },
    get:    vi.fn().mockResolvedValue({ data: {} }),
    post:   vi.fn().mockResolvedValue({ data: {} }),
    put:    vi.fn().mockResolvedValue({ data: {} }),
    patch:  vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function wrap(element: React.ReactElement) {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Routes><Route path="*" element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

beforeEach(() => {
  useStore.setState({
    token: 'tok', user: mockUser, isAuthenticated: true,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── Store → Dashboard integration ───────────────────────────────────────────

describe('store → Dashboard integration', () => {
  async function getDashboard() {
    const Dashboard = (await import('../pages/Dashboard')).default;
    return Dashboard;
  }

  it('account balance updates reactively', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setAccount({
        balance: 250_000, equity: 255_000, margin_used: 5_000, margin_free: 245_000,
        margin_level: 5100, daily_pnl: 1000, daily_pnl_pct: 0.4, total_pnl: 5_000,
        win_rate: 0.70, sharpe_ratio: 2.1, max_drawdown: 0.02, open_trades: 3,
      });
    });

    expect(screen.getByText('$250,000.00')).toBeInTheDocument();
  });

  it('positions table updates when store changes', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setPositions([{
        id: 'p1', symbol: 'GBP/USD', side: 'short', size: 10_000,
        entry_price: 1.27, current_price: 1.265, unrealized_pnl: 50,
        realized_pnl: 0, opened_at: new Date().toISOString(),
      }]);
    });

    // Symbol appears in ticker + positions table — use getAllByText
    expect(screen.getAllByText('GBP/USD').length).toBeGreaterThan(0);
  });

  it('signals panel updates when store changes', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setSignals([{
        id: 's1', symbol: 'USD/JPY', direction: 'short', confidence: 0.78,
        model: 'LightGBM', entry_price: 149.5, stop_loss: 150.2, take_profit: 148.0,
        generated_at: new Date().toISOString(), status: 'active',
      }]);
    });

    // USD/JPY appears in ticker + signal card
    expect(screen.getAllByText('USD/JPY').length).toBeGreaterThan(0);
    expect(screen.getByText('LightGBM')).toBeInTheDocument();
  });

  it('win rate displays correctly from store', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setAccount({
        balance: 100_000, equity: 101_000, margin_used: 0, margin_free: 100_000,
        margin_level: 0, daily_pnl: 0, daily_pnl_pct: 0, total_pnl: 1_000,
        win_rate: 0.72, sharpe_ratio: 1.5, max_drawdown: 0.03, open_trades: 0,
      });
    });

    // Win rate appears in stat card and possibly signal confidence bar — use getAllByText
    expect(screen.getAllByText('72.0%').length).toBeGreaterThan(0);
  });

  it('multiple positions render correctly', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setPositions([
        { id: 'p1', symbol: 'XAU/USD', side: 'long',  size: 1, entry_price: 2340, current_price: 2360, unrealized_pnl: 200, realized_pnl: 0, opened_at: new Date().toISOString() },
        { id: 'p2', symbol: 'EUR/USD', side: 'short', size: 10_000, entry_price: 1.085, current_price: 1.082, unrealized_pnl: 30, realized_pnl: 0, opened_at: new Date().toISOString() },
      ]);
    });

    // Symbols appear in ticker + positions table
    expect(screen.getAllByText('XAU/USD').length).toBeGreaterThan(0);
    expect(screen.getAllByText('EUR/USD').length).toBeGreaterThan(0);
  });

  it('multiple signals render correctly', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setSignals([
        { id: 's1', symbol: 'XAU/USD', direction: 'long',  confidence: 0.87, model: 'XGBoost', entry_price: 2341, stop_loss: 2320, take_profit: 2380, generated_at: new Date().toISOString(), status: 'active' },
        { id: 's2', symbol: 'EUR/USD', direction: 'short', confidence: 0.72, model: 'RF',      entry_price: 1.085, stop_loss: 1.088, take_profit: 1.081, generated_at: new Date().toISOString(), status: 'active' },
      ]);
    });

    expect(screen.getByText('XGBoost')).toBeInTheDocument();
    expect(screen.getByText('RF')).toBeInTheDocument();
  });

  it('WS status badge reflects store state', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => { useStore.getState().setWsStatus('connected'); });
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('WS disconnected shows Disconnected', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => { useStore.getState().setWsStatus('disconnected'); });
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('WS connecting shows Connecting', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => { useStore.getState().setWsStatus('connecting'); });
    expect(screen.getByText('Connecting')).toBeInTheDocument();
  });
});

// ─── Auth flow integration ────────────────────────────────────────────────────

describe('auth flow integration', () => {
  // Before each auth test, update authApi.me to echo back whatever user the
  // test sets in the store. This prevents AuthGuard's role-sync from
  // overwriting the role the test intentionally configured.
  beforeEach(() => {
    vi.mocked(useApiModule.authApi.me).mockImplementation(() =>
      Promise.resolve({ data: useStore.getState().user ?? { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' } }) as never
    );
  });

  it('AuthGuard blocks unauthenticated access', async () => {
    useStore.setState({ ...useStore.getState(), isAuthenticated: false, token: null, user: null });
    const AuthGuard = (await import('../components/AuthGuard')).default;
    render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<AuthGuard><div>Secret</div></AuthGuard>} />
          <Route path="/login" element={<div>Login</div>} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.queryByText('Secret')).not.toBeInTheDocument();
    expect(screen.getByText('Login')).toBeInTheDocument();
  });

  it('AuthGuard allows authenticated access', async () => {
    const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };
    useStore.getState().setAuth(makeMockJwt(), mockUser);
    const AuthGuard = (await import('../components/AuthGuard')).default;
    render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<AuthGuard><div>Secret</div></AuthGuard>} />
          <Route path="/login" element={<div>Login</div>} />
        </Routes>
      </MemoryRouter>
    );
    // AuthGuard shows a spinner while syncing role from /api/auth/me.
    // Wait for the spinner to resolve before asserting content.
    await waitFor(() => expect(screen.getByText('Secret')).toBeInTheDocument());
  });

  it('clearAuth causes re-render to login', async () => {
    const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };
    useStore.getState().setAuth(makeMockJwt(), mockUser);
    const AuthGuard = (await import('../components/AuthGuard')).default;
    const { rerender } = render(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
          <Route path="/login" element={<div>Login</div>} />
        </Routes>
      </MemoryRouter>
    );

    // Wait past the role-sync spinner before asserting
    await waitFor(() => expect(screen.getByText('Protected')).toBeInTheDocument());

    act(() => { useStore.getState().clearAuth(); });

    rerender(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
          <Route path="/login" element={<div>Login</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });
});

// ─── Price ticker integration ─────────────────────────────────────────────────

describe('price ticker integration', () => {
  async function getDashboard() {
    const Dashboard = (await import('../pages/Dashboard')).default;
    return Dashboard;
  }

  it('shows — when no price data', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
  });

  it('shows price when tick arrives', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setPrice({
        symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
        spread: 0.2, timestamp: Date.now(), change_pct: 0.5,
      });
    });

    // Price is formatted as "2,340.00" with locale formatting
    expect(screen.getAllByText(/2[,.]?340/).length).toBeGreaterThan(0);
  });

  it('shows change_pct when tick arrives', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setPrice({
        symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
        spread: 0.2, timestamp: Date.now(), change_pct: 1.23,
      });
    });

    expect(screen.getByText('+1.23%')).toBeInTheDocument();
  });

  it('shows negative change_pct correctly', async () => {
    const Dashboard = await getDashboard();
    wrap(<Dashboard />);

    act(() => {
      useStore.getState().setPrice({
        symbol: 'EUR/USD', bid: 1.0849, ask: 1.0851, mid: 1.0850,
        spread: 0.0002, timestamp: Date.now(), change_pct: -0.45,
      });
    });

    expect(screen.getByText('-0.45%')).toBeInTheDocument();
  });
});

// ─── Store persistence ────────────────────────────────────────────────────────

describe('store state management', () => {
  it('multiple rapid price updates are handled', () => {
    for (let i = 0; i < 100; i++) {
      useStore.getState().setPrice({
        symbol: 'XAU/USD', bid: 2340 + i - 0.1, ask: 2340 + i + 0.1,
        mid: 2340 + i, spread: 0.2, timestamp: Date.now(), change_pct: 0,
      });
    }
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2439);
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(100);
  });

  it('position upsert then remove leaves empty array', () => {
    useStore.getState().upsertPosition({
      id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
      entry_price: 2340, current_price: 2360, unrealized_pnl: 200,
      realized_pnl: 0, opened_at: new Date().toISOString(),
    });
    useStore.getState().removePosition('p1');
    expect(useStore.getState().positions).toHaveLength(0);
  });

  it('50 signals cap is enforced', () => {
    for (let i = 0; i < 60; i++) {
      useStore.getState().addSignal({
        id: String(i), symbol: 'XAU/USD', direction: 'long', confidence: 0.8,
        model: 'XGB', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
        generated_at: new Date().toISOString(), status: 'active',
      });
    }
    expect(useStore.getState().signals).toHaveLength(50);
  });

  it('auth state is consistent after setAuth + clearAuth cycle', () => {
    useStore.getState().setAuth('tok', mockUser);
    expect(useStore.getState().isAuthenticated).toBe(true);
    useStore.getState().clearAuth();
    expect(useStore.getState().isAuthenticated).toBe(false);
    expect(useStore.getState().token).toBeNull();
    expect(useStore.getState().user).toBeNull();
  });

  it('ws status transitions are valid', () => {
    const statuses = ['connecting', 'connected', 'disconnected', 'error'] as const;
    for (const s of statuses) {
      useStore.getState().setWsStatus(s);
      expect(useStore.getState().wsStatus).toBe(s);
    }
  });
});
