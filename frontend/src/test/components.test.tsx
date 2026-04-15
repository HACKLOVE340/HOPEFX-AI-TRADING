/**
 * Component tests — AuthGuard, Login, App routing
 * ~80 tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import React from 'react';
import { useStore } from '../store';
import AuthGuard from '../components/AuthGuard';

// Must be at module top level — vi.mock calls are hoisted by Vitest before
// any test code runs, so placing them inside describe() causes a warning.
vi.mock('../hooks/useApi', () => ({
  authApi: {
    login:            vi.fn(),
    logout:           vi.fn(),
    me:               vi.fn(),
    register:         vi.fn(),
    activateFreeTier: vi.fn(),
  },
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
  backtestApi: {
    run: vi.fn(), results: vi.fn(), list: vi.fn(),
  },
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
    upcoming:     vi.fn().mockResolvedValue({ data: [] }),
    today:        vi.fn().mockResolvedValue({ data: [] }),
    highImpact:   vi.fn().mockResolvedValue({ data: [] }),
    autoPause:    vi.fn().mockResolvedValue({ data: {} }),
    setAutoPause: vi.fn().mockResolvedValue({ data: {} }),
    fomc:         vi.fn().mockResolvedValue({ data: [] }),
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
    interceptors: {
      request:  { handlers: [{}], use: vi.fn() },
      response: { handlers: [{}], use: vi.fn() },
    },
    get:    vi.fn().mockResolvedValue({ data: {} }),
    post:   vi.fn().mockResolvedValue({ data: {} }),
    put:    vi.fn().mockResolvedValue({ data: {} }),
    patch:  vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

/**
 * Build a minimal valid JWT with an exp 1 hour in the future.
 * AuthGuard now calls isTokenExpired() so tests must supply a real-shaped token.
 */
function makeMockJwt(overrides: Record<string, unknown> = {}): string {
  const header  = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).replace(/=/g, '');
  const payload = btoa(JSON.stringify({
    sub: '1',
    type: 'access',
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...overrides,
  })).replace(/=/g, '');
  return `${header}.${payload}.sig`;
}

function renderWithRouter(ui: React.ReactElement, { initialEntries = ['/'] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      {ui}
    </MemoryRouter>
  );
}

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── AuthGuard ────────────────────────────────────────────────────────────────

describe('AuthGuard', () => {
  it('redirects to /login when not authenticated', () => {
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    useStore.getState().setAuth(makeMockJwt(), mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('does not show login page when authenticated', () => {
    useStore.getState().setAuth(makeMockJwt(), mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument();
  });

  it('shows access denied for insufficient role', () => {
    useStore.getState().setAuth(makeMockJwt(), mockUser); // trader role
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Only</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
    expect(screen.queryByText('Admin Only')).not.toBeInTheDocument();
  });

  it('allows access when role is sufficient', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'admin' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('superadmin can access admin-required routes', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'superadmin' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="admin"><div>Admin Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('user role cannot access trader-required routes', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="trader"><div>Trader Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('trader can access trader-required routes', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'trader' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="trader"><div>Trader Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Trader Content')).toBeInTheDocument();
  });

  it('renders multiple children', () => {
    useStore.getState().setAuth(makeMockJwt(), mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={
          <AuthGuard>
            <div>Child 1</div>
            <div>Child 2</div>
          </AuthGuard>
        } />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Child 1')).toBeInTheDocument();
    expect(screen.getByText('Child 2')).toBeInTheDocument();
  });

  it('access denied message mentions required role', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard requiredRole="superadmin"><div>Super</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText(/superadmin/i)).toBeInTheDocument();
  });

  it('no requiredRole allows any authenticated user', () => {
    useStore.getState().setAuth(makeMockJwt(), { ...mockUser, role: 'user' });
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Open Content</div></AuthGuard>} />
        <Route path="/login" element={<div>Login</div>} />
      </Routes>
    );
    expect(screen.getByText('Open Content')).toBeInTheDocument();
  });

  it('redirects expired token to /login', () => {
    // exp in the past → isTokenExpired returns true
    useStore.getState().setAuth(makeMockJwt({ exp: Math.floor(Date.now() / 1000) - 60 }), mockUser);
    renderWithRouter(
      <Routes>
        <Route path="/" element={<AuthGuard><div>Protected</div></AuthGuard>} />
        <Route path="/login" element={<div>Login Page</div>} />
      </Routes>
    );
    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });
});

// ─── Login page ───────────────────────────────────────────────────────────────

describe('Login page', () => {

  async function renderLogin() {
    const Login = (await import('../pages/Login')).default;
    return renderWithRouter(
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/dashboard" element={<div>Dashboard</div>} />
      </Routes>
    );
  }

  it('renders HOPEFX branding', async () => {
    await renderLogin();
    expect(screen.getByText(/HOPE/)).toBeInTheDocument();
  });

  it('renders email input', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
  });

  it('renders password input', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('renders sign in button', async () => {
    await renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows error when submitting empty form', async () => {
    await renderLogin();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/required/i)).toBeInTheDocument();
  });

  it('shows error when only email provided', async () => {
    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'user@test.com' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/required/i)).toBeInTheDocument();
  });

  it('calls authApi.login with credentials', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'tok', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'trader@hopefx.io' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith({ email: 'trader@hopefx.io', password: 'pass123' });  // pragma: allowlist secret
    });
  });

  it('stores token in store after successful login', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'my-token', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'trader@hopefx.io' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(useStore.getState().token).toBe('my-token');
    });
  });

  it('shows error message on failed login', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockRejectedValueOnce({
      response: { data: { detail: 'Invalid credentials' } },
    });

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'bad@test.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('shows generic error when no detail in response', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockRejectedValueOnce(new Error('Network error'));

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: 'user@test.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it('normalises email to lowercase before sending', async () => {
    const { authApi } = await import('../hooks/useApi');
    vi.mocked(authApi.login).mockResolvedValueOnce({
      data: { access_token: 'tok', token_type: 'bearer', user: mockUser },
    } as never);

    await renderLogin();
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: '  Trader@HopeFX.io  ' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pass' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith({ email: 'trader@hopefx.io', password: 'pass' });  // pragma: allowlist secret
    });
  });

  it('has status page link', async () => {
    await renderLogin();
    expect(screen.getByText(/system status/i)).toBeInTheDocument();
  });

  it('has support link', async () => {
    await renderLogin();
    expect(screen.getByText(/support/i)).toBeInTheDocument();
  });

  it('password input is type=password', async () => {
    await renderLogin();
    const input = screen.getByLabelText(/password/i) as HTMLInputElement;
    expect(input.type).toBe('password');
  });
});
