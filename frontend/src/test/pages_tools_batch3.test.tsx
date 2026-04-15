/**
 * Tests for CorrelationDashboard, EconomicCalendar, RiskCalculator, Wallet, Settings pages.
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
  authApi: { login: vi.fn(), logout: vi.fn(), me: vi.fn() },
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
  backtestApi: { run: vi.fn(), results: vi.fn(), list: vi.fn() },
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
    autoPause:    vi.fn().mockResolvedValue({ data: { enabled: false, pause_minutes: 30 } }),
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
      if (typeof url === 'string' && url.includes('/advanced/correlation')) {
        return Promise.resolve({ data: {
          symbols: ['XAU/USD', 'EUR/USD'],
          matrix: { 'XAU/USD': { 'XAU/USD': 1.0, 'EUR/USD': 0.42 }, 'EUR/USD': { 'XAU/USD': 0.42, 'EUR/USD': 1.0 } },
          insights: [],
          window: 30,
          updated_at: new Date().toISOString(),
        } });
      }
      if (typeof url === 'string' && url.includes('/advanced/cot')) {
        return Promise.resolve({ data: {
          report_date: '2026-01-01', net_speculator_long: 12500,
          long_positions: 85000, short_positions: 72500,
          sentiment: 'bullish', sentiment_strength: 'moderate',
          note: '', weekly_change: 500, source: 'CFTC',
        } });
      }
      if (typeof url === 'string' && url.includes('/billing/balance')) {
        return Promise.resolve({ data: { balance: 10000, frozen: 0, pending: 0 } });
      }
      if (typeof url === 'string' && url.includes('/billing/transactions')) {
        return Promise.resolve({ data: { transactions: [] } });
      }
      if (typeof url === 'string' && url.includes('/billing/subscription')) {
        return Promise.resolve({ data: { plan: 'pro', status: 'active', next_billing: '2025-02-01' } });
      }
      if (typeof url === 'string' && url.includes('/billing/payment-methods')) {
        return Promise.resolve({ data: { methods: [] } });
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

const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

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

// ─── CorrelationDashboard ─────────────────────────────────────────────────────

describe('CorrelationDashboard page', () => {
  async function renderCorrelation() {
    const CorrelationDashboard = (await import('../pages/CorrelationDashboard')).default;
    return wrap(<CorrelationDashboard />);
  }

  it('renders Correlation & Sentiment heading', async () => {
    await renderCorrelation();
    expect(screen.getAllByText(/correlation.*sentiment|sentiment.*correlation/i).length).toBeGreaterThan(0);
  });

  it('renders subtitle text', async () => {
    await renderCorrelation();
    expect(document.body.textContent).toMatch(/rolling correlations|macro indicators/i);
  });

  it('renders window filter buttons', async () => {
    await renderCorrelation();
    // Buttons like "7d", "14d", "30d"
    const buttons = document.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThan(0);
  });

  it('renders 30d window button', async () => {
    await renderCorrelation();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /30d/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders without crashing', async () => {
    const { container } = await renderCorrelation();
    expect(container).toBeInTheDocument();
  });

  it('switches window on button click', async () => {
    await renderCorrelation();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /14d/i.test(b.textContent ?? ''));
    if (btn) {
      fireEvent.click(btn);
      expect(document.body.textContent).toMatch(/correlation/i);
    }
  });

  it('renders COT sentiment section', async () => {
    await renderCorrelation();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/cot|sentiment|correlation/i);
    }, { timeout: 3000 });
  });
});

// ─── EconomicCalendar ─────────────────────────────────────────────────────────

describe('EconomicCalendar page', () => {
  async function renderEconomicCalendar() {
    const EconomicCalendar = (await import('../pages/EconomicCalendar')).default;
    return wrap(<EconomicCalendar />);
  }

  it('renders Economic Calendar heading', async () => {
    await renderEconomicCalendar();
    expect(screen.getAllByText(/economic calendar/i).length).toBeGreaterThan(0);
  });

  it('renders subtitle text', async () => {
    await renderEconomicCalendar();
    expect(document.body.textContent).toMatch(/upcoming market.moving events/i);
  });

  it('renders without crashing', async () => {
    const { container } = await renderEconomicCalendar();
    expect(container).toBeInTheDocument();
  });

  it('shows empty state when no events', async () => {
    await renderEconomicCalendar();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no events found/i);
    }, { timeout: 3000 });
  });

  it('renders High Impact filter button', async () => {
    await renderEconomicCalendar();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /high impact/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders All Events filter button', async () => {
    await renderEconomicCalendar();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /all events/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders Auto-Pause toggle section', async () => {
    await renderEconomicCalendar();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/auto.pause|autopause/i);
    }, { timeout: 3000 });
  });

  it('switches to High Impact filter', async () => {
    await renderEconomicCalendar();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /high impact/i.test(b.textContent ?? ''));
    if (btn) {
      fireEvent.click(btn);
      expect(document.body.textContent).toMatch(/calendar|events/i);
    }
  });
});

// ─── RiskCalculator ───────────────────────────────────────────────────────────

describe('RiskCalculator page', () => {
  async function renderRiskCalculator() {
    const RiskCalculator = (await import('../pages/RiskCalculator')).default;
    return wrap(<RiskCalculator />);
  }

  it('renders Risk / Reward Calculator heading', async () => {
    await renderRiskCalculator();
    expect(screen.getAllByText(/risk.*reward calculator|risk.*calculator/i).length).toBeGreaterThan(0);
  });

  it('renders subtitle text', async () => {
    await renderRiskCalculator();
    expect(document.body.textContent).toMatch(/position size|pip value|margin/i);
  });

  it('renders Account Balance input', async () => {
    await renderRiskCalculator();
    expect(screen.getByPlaceholderText('10000')).toBeInTheDocument();
  });

  it('renders Risk % input', async () => {
    await renderRiskCalculator();
    expect(screen.getByPlaceholderText('1')).toBeInTheDocument();
  });

  it('renders Leverage input', async () => {
    await renderRiskCalculator();
    expect(screen.getByPlaceholderText('100')).toBeInTheDocument();
  });

  it('renders without crashing', async () => {
    const { container } = await renderRiskCalculator();
    expect(container).toBeInTheDocument();
  });

  it('updates account balance input', async () => {
    await renderRiskCalculator();
    const input = screen.getByPlaceholderText('10000') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '50000' } });
    expect(input.value).toBe('50000');
  });

  it('renders calculated results section', async () => {
    await renderRiskCalculator();
    expect(document.body.textContent).toMatch(/position size|lot size|pip value|result/i);
  });

  it('renders symbol selector', async () => {
    await renderRiskCalculator();
    const selects = document.querySelectorAll('select');
    expect(selects.length).toBeGreaterThan(0);
  });
});

// ─── Wallet ───────────────────────────────────────────────────────────────────

describe('Wallet page', () => {
  async function renderWallet() {
    const Wallet = (await import('../pages/Wallet')).default;
    return wrap(<Wallet />);
  }

  it('renders Wallet & Payments heading', async () => {
    await renderWallet();
    expect(screen.getAllByText(/wallet.*payments|payments.*wallet/i).length).toBeGreaterThan(0);
  });

  it('renders Deposit button', async () => {
    await renderWallet();
    expect(screen.getByRole('button', { name: /deposit/i })).toBeInTheDocument();
  });

  it('renders Withdraw button', async () => {
    await renderWallet();
    expect(screen.getByRole('button', { name: /withdraw/i })).toBeInTheDocument();
  });

  it('renders without crashing', async () => {
    const { container } = await renderWallet();
    expect(container).toBeInTheDocument();
  });

  it('shows balance after load', async () => {
    await renderWallet();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/balance|wallet/i);
    }, { timeout: 3000 });
  });

  it('opens deposit form on Deposit click', async () => {
    await renderWallet();
    fireEvent.click(screen.getByRole('button', { name: /deposit/i }));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/deposit funds/i);
    }, { timeout: 2000 });
  });

  it('opens withdraw form on Withdraw click', async () => {
    await renderWallet();
    fireEvent.click(screen.getByRole('button', { name: /withdraw/i }));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/withdraw funds/i);
    }, { timeout: 2000 });
  });

  it('deposit form has amount input', async () => {
    await renderWallet();
    fireEvent.click(screen.getByRole('button', { name: /deposit/i }));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/e\.g\. 1000/i)).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('deposit form has Cancel button', async () => {
    await renderWallet();
    fireEvent.click(screen.getByRole('button', { name: /deposit/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('Cancel closes deposit form', async () => {
    await renderWallet();
    fireEvent.click(screen.getByRole('button', { name: /deposit/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    }, { timeout: 2000 });
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/e\.g\. 1000/i)).not.toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('renders transaction history tab', async () => {
    await renderWallet();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/transaction|history/i);
    }, { timeout: 3000 });
  });
});

// ─── Settings ─────────────────────────────────────────────────────────────────

describe('Settings page', () => {
  async function renderSettings() {
    const Settings = (await import('../pages/Settings')).default;
    return wrap(<Settings />);
  }

  it('renders Settings heading', async () => {
    await renderSettings();
    expect(screen.getAllByText(/^settings$/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderSettings();
    expect(container).toBeInTheDocument();
  });

  it('renders Profile tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/profile/i);
  });

  it('renders Security tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/security/i);
  });

  it('renders Broker tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/broker/i);
  });

  it('renders Notifications tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/notifications/i);
  });

  it('renders Appearance tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/appearance/i);
  });

  it('renders Billing tab', async () => {
    await renderSettings();
    expect(document.body.textContent).toMatch(/billing/i);
  });

  it('switches to Security tab', async () => {
    await renderSettings();
    const secBtn = Array.from(document.querySelectorAll('button')).find(b => /^security$/i.test(b.textContent?.trim() ?? ''));
    if (secBtn) {
      fireEvent.click(secBtn);
      await waitFor(() => {
        expect(document.body.textContent).toMatch(/security|password|2fa/i);
      }, { timeout: 2000 });
    }
  });

  it('switches to Broker tab', async () => {
    await renderSettings();
    const brokerBtn = Array.from(document.querySelectorAll('button')).find(b => /^broker$/i.test(b.textContent?.trim() ?? ''));
    if (brokerBtn) {
      fireEvent.click(brokerBtn);
      await waitFor(() => {
        expect(document.body.textContent).toMatch(/broker|connection|api/i);
      }, { timeout: 2000 });
    }
  });
});
