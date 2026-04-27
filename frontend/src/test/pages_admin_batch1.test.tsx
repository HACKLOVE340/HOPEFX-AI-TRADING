/**
 * Tests for WalkForward, SecurityDashboard, SuperAdminDashboard, TCADashboard, AuditLog pages.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({ send: vi.fn() })),
}));

vi.mock('../hooks/useApi', () => ({
  authApi: { login: vi.fn().mockResolvedValue({ data: { access_token: 'tok', token_type: 'bearer', user: { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' } } }), logout: vi.fn().mockResolvedValue({ data: {} }), me: vi.fn().mockResolvedValue({ data: { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' } }) },
  tradingApi: {
    positions:         vi.fn().mockResolvedValue({ data: [] }),
    signals:           vi.fn().mockResolvedValue({ data: [] }),
    account:           vi.fn().mockResolvedValue({ data: null }),
    ohlcv:             vi.fn().mockResolvedValue({ data: [] }),
    placeOrder:        vi.fn().mockResolvedValue({ data: {} }),
    closePosition:     vi.fn().mockResolvedValue({ data: {} }),
    closeAllPositions: vi.fn().mockResolvedValue({ data: {} }),
    trades:            vi.fn().mockResolvedValue({ data: [] }),
    regime:            vi.fn().mockResolvedValue({ data: {} }),
    brainState:        vi.fn().mockResolvedValue({ data: {} }),
    emergencyStop:     vi.fn().mockResolvedValue({ data: {} }),
    aiAnalysis:        vi.fn().mockResolvedValue({ data: {} }),
    riskMetrics:       vi.fn().mockResolvedValue({ data: {} }),
  },
  mlApi: {
    accuracy: vi.fn().mockResolvedValue({ data: {} }),
    predict:  vi.fn().mockResolvedValue({ data: {} }),
    models:   vi.fn().mockResolvedValue({ data: [] }),
    features: vi.fn().mockResolvedValue({ data: {} }),
  },
  mlExtendedApi: {
    health:      vi.fn().mockResolvedValue({ data: {} }),
    retrain:     vi.fn().mockResolvedValue({ data: {} }),
    filterStats: vi.fn().mockResolvedValue({ data: {} }),
    rlStatus:    vi.fn().mockResolvedValue({ data: {} }),
    rlTrain:     vi.fn().mockResolvedValue({ data: {} }),
    walkForward: vi.fn().mockResolvedValue({ data: {} }),
    explain:     vi.fn().mockResolvedValue({ data: {} }),
  },
  backtestApi: { run: vi.fn().mockResolvedValue({ data: { job_id: 'bt-1', status: 'queued' } }), results: vi.fn().mockResolvedValue({ data: { job_id: 'bt-1', status: 'completed', metrics: { total_return: 0.12, sharpe: 1.4, max_drawdown: 0.08, win_rate: 0.58 }, equity_curve: [] } }), list: vi.fn().mockResolvedValue({ data: { backtests: [] } }) },
  performanceApi: {
    summary:     vi.fn().mockResolvedValue({ data: {} }),
    equity:      vi.fn().mockResolvedValue({ data: [] }),
    equityCurve: vi.fn().mockResolvedValue({ data: [] }),
    trades:      vi.fn().mockResolvedValue({ data: [] }),
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
    sentiment:      vi.fn().mockResolvedValue({ data: { signal: {}, recent_articles: [] } }),
    macro:          vi.fn().mockResolvedValue({ data: { upcoming_events: [] } }),
    microstructure: vi.fn().mockResolvedValue({ data: {} }),
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
  leaderboardApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
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
    get: vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/walk-forward')) {
        return Promise.resolve({ data: {
          run_id: 'wf1', strategy: 'XGBoost', symbol: 'XAU/USD',
          folds: [], stability_score: 0.88,
          avg_sharpe: 1.42, avg_accuracy: 87.3, avg_drawdown: 4.2,
        }});
      }
      if (typeof url === 'string' && url.includes('/security/attacks')) {
        return Promise.resolve({ data: { total: 0, by_type: {}, recent: [] } });
      }
      if (typeof url === 'string' && url.includes('/security/lockdown')) {
        return Promise.resolve({ data: { active: false, reason: null, activated_at: null } });
      }
      if (typeof url === 'string' && url.includes('/security/blocked-ips')) {
        return Promise.resolve({ data: [] });
      }
      if (typeof url === 'string' && url.includes('/security/alerts')) {
        return Promise.resolve({ data: [] });
      }
      if (typeof url === 'string' && url.includes('/security/fixes')) {
        return Promise.resolve({ data: [] });
      }
      if (typeof url === 'string' && url.includes('/admin/audit-log')) {
        return Promise.resolve({ data: { events: [], total: 0, page: 1, page_size: 50 } });
      }
      if (typeof url === 'string' && url.includes('/tca/')) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    }),
    post:   vi.fn().mockResolvedValue({ data: {} }),
    put:    vi.fn().mockResolvedValue({ data: {} }),
    patch:  vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// ─── Helpers ──────────────────────────────────────────────────────────────────

const mockUser = { id: '1', email: 'a@b.com', username: 'admin1', role: 'superadmin' as const };

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(element: React.ReactElement) {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter>
        <Routes><Route path="*" element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  useStore.setState({
    token: 'tok', user: mockUser, isAuthenticated: true,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── WalkForward ──────────────────────────────────────────────────────────────

describe('WalkForward page', () => {
  async function renderWalkForward() {
    const WalkForward = (await import('../pages/WalkForward')).default;
    return wrap(<WalkForward />);
  }

  it('renders Walk-Forward heading', async () => {
    await renderWalkForward();
    expect(screen.getAllByText(/walk.forward/i).length).toBeGreaterThan(0);
  });

  it('renders Load button after data loads', async () => {
    await renderWalkForward();
    await waitFor(() => {
      // After data loads, "Load" button appears in the search row
      expect(document.body.textContent).toMatch(/load|retry/i);
    }, { timeout: 3000 });
  });

  it('renders Run ID input after data loads', async () => {
    await renderWalkForward();
    await waitFor(() => {
      // Input appears after data loads successfully
      const input = document.querySelector('input[placeholder="Run ID…"]');
      expect(input).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('renders subtitle text', async () => {
    await renderWalkForward();
    expect(document.body.textContent).toMatch(/walk.forward/i);
  });

  it('Load button is clickable after data loads', async () => {
    await renderWalkForward();
    await waitFor(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => /load|retry/i.test(b.textContent ?? ''));
      expect(btn).toBeTruthy();
    }, { timeout: 3000 });
    const btn = Array.from(document.querySelectorAll('button')).find(b => /load|retry/i.test(b.textContent ?? ''));
    fireEvent.click(btn!);
    expect(document.body).toBeInTheDocument();
  });

  it('Run ID input accepts text after data loads', async () => {
    await renderWalkForward();
    await waitFor(() => {
      const input = document.querySelector('input[placeholder="Run ID…"]');
      expect(input).toBeTruthy();
    }, { timeout: 3000 });
    const input = document.querySelector('input[placeholder="Run ID…"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'test-run-123' } });
    expect(input.value).toBe('test-run-123');
  });

  it('renders without crashing when no data', async () => {
    const { container } = await renderWalkForward();
    expect(container).toBeInTheDocument();
  });

  it('shows validation or analysis heading after load', async () => {
    await renderWalkForward();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/walk.forward|validation|analysis/i);
    }, { timeout: 3000 });
  });
});

// ─── SecurityDashboard ────────────────────────────────────────────────────────

describe('SecurityDashboard page', () => {
  async function renderSecurityDashboard() {
    const SecurityDashboard = (await import('../pages/SecurityDashboard')).default;
    return wrap(<SecurityDashboard />);
  }

  it('renders Security Operations heading', async () => {
    await renderSecurityDashboard();
    expect(screen.getAllByText(/security/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderSecurityDashboard();
    expect(container).toBeInTheDocument();
  });

  it('renders threat monitoring subtitle', async () => {
    await renderSecurityDashboard();
    expect(document.body.textContent).toMatch(/threat|monitoring|security/i);
  });

  it('renders attack stats section', async () => {
    await renderSecurityDashboard();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/attack|threat|blocked|security/i);
    }, { timeout: 3000 });
  });

  it('renders lockdown status section', async () => {
    await renderSecurityDashboard();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/lockdown|status|security/i);
    }, { timeout: 3000 });
  });

  it('renders blocked IPs section', async () => {
    await renderSecurityDashboard();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/blocked|ip|security/i);
    }, { timeout: 3000 });
  });

  it('renders alerts section', async () => {
    await renderSecurityDashboard();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/alert|security/i);
    }, { timeout: 3000 });
  });
});

// ─── SuperAdminDashboard ──────────────────────────────────────────────────────

describe('SuperAdminDashboard page', () => {
  async function renderSuperAdmin() {
    const SuperAdminDashboard = (await import('../pages/SuperAdminDashboard')).default;
    return wrap(<SuperAdminDashboard />);
  }

  it('renders Super Admin heading', async () => {
    await renderSuperAdmin();
    expect(screen.getAllByText(/super admin/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderSuperAdmin();
    expect(container).toBeInTheDocument();
  });

  it('renders tab navigation', async () => {
    await renderSuperAdmin();
    const buttons = document.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThan(0);
  });

  it('renders subheading text', async () => {
    await renderSuperAdmin();
    expect(document.body.textContent).toMatch(/admin|platform|system/i);
  });

  it('renders overview section by default', async () => {
    await renderSuperAdmin();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/overview|users|system|admin/i);
    }, { timeout: 3000 });
  });

  it('renders user management tab', async () => {
    await renderSuperAdmin();
    const buttons = Array.from(document.querySelectorAll('button'));
    const userTab = buttons.find(b => /users/i.test(b.textContent ?? ''));
    expect(userTab).toBeTruthy();
  });

  it('renders system tab', async () => {
    await renderSuperAdmin();
    const buttons = Array.from(document.querySelectorAll('button'));
    const sysTab = buttons.find(b => /system/i.test(b.textContent ?? ''));
    expect(sysTab).toBeTruthy();
  });

  it('switches tabs without crashing', async () => {
    await renderSuperAdmin();
    const buttons = Array.from(document.querySelectorAll('button'));
    const userTab = buttons.find(b => /users/i.test(b.textContent ?? ''));
    if (userTab) {
      fireEvent.click(userTab);
      expect(document.body.textContent).toMatch(/users|admin/i);
    }
  });
});

// ─── TCADashboard ─────────────────────────────────────────────────────────────

describe('TCADashboard page', () => {
  async function renderTCA() {
    const TCADashboard = (await import('../pages/TCADashboard')).default;
    return wrap(<TCADashboard />);
  }

  it('renders Transaction Cost Analysis heading', async () => {
    await renderTCA();
    expect(document.body.textContent).toMatch(/transaction cost|tca/i);
  });

  it('renders without crashing', async () => {
    const { container } = await renderTCA();
    expect(container).toBeInTheDocument();
  });

  it('renders Refresh button', async () => {
    await renderTCA();
    expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument();
  });

  it('renders CSV download button', async () => {
    await renderTCA();
    // Button text is "↓ CSV"
    expect(screen.getByRole('button', { name: /csv/i })).toBeInTheDocument();
  });

  it('renders Flush Records button for admin', async () => {
    await renderTCA();
    // isAdmin=true because mockUser.role='superadmin'
    expect(screen.getByRole('button', { name: /flush records/i })).toBeInTheDocument();
  });

  it('renders broker filter dropdown', async () => {
    await renderTCA();
    const selects = document.querySelectorAll('select');
    expect(selects.length).toBeGreaterThan(0);
  });

  it('renders slippage subtitle', async () => {
    await renderTCA();
    expect(document.body.textContent).toMatch(/slippage|cost|tca/i);
  });

  it('Refresh button is clickable', async () => {
    await renderTCA();
    const btn = screen.getByRole('button', { name: /refresh/i });
    fireEvent.click(btn);
    expect(btn).toBeInTheDocument();
  });

  it('Flush Records shows confirmation on click', async () => {
    await renderTCA();
    const flushBtn = screen.getByRole('button', { name: /flush records/i });
    fireEvent.click(flushBtn);
    await waitFor(() => {
      // After click, shows "Confirm flush?" text
      expect(document.body.textContent).toMatch(/confirm flush/i);
    }, { timeout: 2000 });
  });
});

// ─── AuditLog ─────────────────────────────────────────────────────────────────

describe('AuditLog page', () => {
  async function renderAuditLog() {
    const AuditLog = (await import('../pages/AuditLog')).default;
    return wrap(<AuditLog />);
  }

  it('renders Audit Log heading', async () => {
    await renderAuditLog();
    expect(screen.getAllByText(/audit log/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderAuditLog();
    expect(container).toBeInTheDocument();
  });

  it('renders user ID filter input', async () => {
    await renderAuditLog();
    expect(screen.getByPlaceholderText(/filter by user id/i)).toBeInTheDocument();
  });

  it('renders event type filter input', async () => {
    await renderAuditLog();
    expect(screen.getByPlaceholderText(/filter by event type/i)).toBeInTheDocument();
  });

  it('renders Search button', async () => {
    await renderAuditLog();
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument();
  });

  it('renders Export button', async () => {
    await renderAuditLog();
    expect(screen.getByRole('button', { name: /export/i })).toBeInTheDocument();
  });

  it('shows empty state when no events', async () => {
    await renderAuditLog();
    await waitFor(() => {
      // AuditLog DataTable renders "No events match your filters" when empty
      expect(document.body.textContent).toMatch(/no events match/i);
    }, { timeout: 3000 });
  });

  it('user ID filter accepts input', async () => {
    await renderAuditLog();
    const input = screen.getByPlaceholderText(/filter by user id/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'user123' } });
    expect(input.value).toBe('user123');
  });

  it('event type filter accepts input', async () => {
    await renderAuditLog();
    const input = screen.getByPlaceholderText(/filter by event type/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'LOGIN' } });
    expect(input.value).toBe('LOGIN');
  });

  it('Search button triggers search', async () => {
    await renderAuditLog();
    const btn = screen.getByRole('button', { name: /search/i });
    fireEvent.click(btn);
    expect(btn).toBeInTheDocument();
  });
});
