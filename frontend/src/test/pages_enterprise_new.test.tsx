/**
 * Tests for the four new enterprise/public pages:
 *   PricingPage, ResearchPage, TeamsPage, ReplayPage
 *
 * Uses real component rendering with mocked API calls.
 * No synthetic data — all mock responses mirror the real API contract.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';
import * as useApiModule from '../hooks/useApi';

// ── Global mocks ──────────────────────────────────────────────────────────────

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({ send: vi.fn() })),
}));

vi.mock('../hooks/useApi', () => ({
  api: {
    get:    vi.fn(),
    post:   vi.fn(),
    patch:  vi.fn(),
    delete: vi.fn(),
  },
  researchApi: {
    listNotebooks:  vi.fn().mockResolvedValue({ data: { notebooks: [], total: 0 } }),
    createNotebook: vi.fn().mockResolvedValue({ data: { notebook_id: 'nb-1', title: 'Test', status: 'draft', symbol: 'XAUUSD', timeframe: 'H1', template: 'technical', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' } }),
    runNotebook:    vi.fn().mockResolvedValue({ data: { notebook_id: 'nb-1', status: 'completed', results: { summary: 'Bullish bias', signals: [], charts: [], metrics: { sharpe: 1.5 }, generated_at: '2026-01-01T00:00:00Z' } } }),
    deleteNotebook: vi.fn().mockResolvedValue({ data: {} }),
    getTemplates:   vi.fn().mockResolvedValue({ data: { templates: [{ id: 'technical', name: 'Technical Analysis', description: 'TA-based', category: 'analysis', required_inputs: ['symbol', 'timeframe'] }] } }),
  },
  teamsApi: {
    list:           vi.fn().mockResolvedValue({ data: { teams: [], total: 0 } }),
    create:         vi.fn().mockResolvedValue({ data: { team_id: 't-1', name: 'Alpha Team', description: '', owner_id: 'u-1', member_count: 1, status: 'active', created_at: '2026-01-01T00:00:00Z' } }),
    get:            vi.fn().mockResolvedValue({ data: { team_id: 't-1', name: 'Alpha Team', description: '', owner_id: 'u-1', member_count: 1, status: 'active', created_at: '2026-01-01T00:00:00Z', members: [] } }),
    getPerformance: vi.fn().mockResolvedValue({ data: { total_pnl: 1250.50, win_rate: 0.62, total_trades: 45, sharpe: 1.8, max_drawdown_pct: 4.2, period: '30d' } }),
    invite:         vi.fn().mockResolvedValue({ data: {} }),
    removeMember:   vi.fn().mockResolvedValue({ data: {} }),
    delete:         vi.fn().mockResolvedValue({ data: {} }),
  },
  replayApi: {
    listSessions:   vi.fn().mockResolvedValue({ data: { sessions: [] } }),
    createSession:  vi.fn().mockResolvedValue({ data: { session_id: 'r-1', symbol: 'XAUUSD', timeframe: 'H1', start_date: '2024-01-01', end_date: '2024-06-30', current_bar: 0, total_bars: 1000, status: 'created', current_price: 2050.0, equity: 10000, pnl: 0, trades: [], bars: [] } }),
    stepSession:    vi.fn().mockResolvedValue({ data: { session_id: 'r-1', current_bar: 1, total_bars: 1000, status: 'running', current_price: 2051.5, equity: 10000, pnl: 0, trades: [], bars: [] } }),
    runSession:     vi.fn().mockResolvedValue({ data: { session_id: 'r-1', current_bar: 11, total_bars: 1000, status: 'running', current_price: 2055.0, equity: 10000, pnl: 0, trades: [], bars: [] } }),
    deleteSession:  vi.fn().mockResolvedValue({ data: {} }),
  },
  whitelabelApi: {
    listTenants:  vi.fn().mockResolvedValue({ data: { tenants: [], total: 0 } }),
    listFeatures: vi.fn().mockResolvedValue({ data: { features: ['custom_branding', 'api_access'] } }),
  },
  pricingApi: {
    getPlans: vi.fn().mockResolvedValue({ data: { plans: [
      { id: 'free',         name: 'Free',         price_usd_monthly: 0,     price_usd_annual: 0,      commission_rate: 0.010, features: ['paper_trading'],                                      limits: { signals_per_day: 5,   backtests_per_month: 3,  live_accounts: 0, max_strategies: 1,  max_brokers: 1  } },
      { id: 'starter',      name: 'Starter',      price_usd_monthly: 1800,  price_usd_annual: 18000,  commission_rate: 0.005, features: ['paper_trading', 'live_trading'],                      limits: { signals_per_day: 20,  backtests_per_month: 10, live_accounts: 1, max_strategies: 3,  max_brokers: 1  } },
      { id: 'professional', name: 'Professional', price_usd_monthly: 4500,  price_usd_annual: 45000,  commission_rate: 0.003, features: ['paper_trading', 'live_trading', 'api_access'],        limits: { signals_per_day: 100, backtests_per_month: 50, live_accounts: 3, max_strategies: 7,  max_brokers: 3  } },
      { id: 'enterprise',   name: 'Enterprise',   price_usd_monthly: 7500,  price_usd_annual: 75000,  commission_rate: 0.002, features: ['paper_trading', 'live_trading', 'white_label'],       limits: { signals_per_day: -1,  backtests_per_month: -1, live_accounts: -1, max_strategies: -1, max_brokers: -1 } },
      { id: 'elite',        name: 'Elite',        price_usd_monthly: 10000, price_usd_annual: 100000, commission_rate: 0.001, features: ['paper_trading', 'live_trading', 'dedicated_support'], limits: { signals_per_day: -1,  backtests_per_month: -1, live_accounts: -1, max_strategies: -1, max_brokers: -1 } },
    ] } }),
    getFaq: vi.fn().mockResolvedValue({ data: { faqs: [
      { question: 'Can I cancel anytime?', answer: 'Yes, cancel anytime.' },
      { question: 'Is there a free trial?', answer: 'Yes, 14-day free trial.' },
    ] } }),
    getCurrentSubscription: vi.fn().mockResolvedValue({ data: { plan: 'free', tier: 'free', status: 'active' } }),
    upgrade: vi.fn().mockResolvedValue({ data: { success: true } }),
  },
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQC() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

function wrap(element: React.ReactElement, path = '/') {
  const qc = makeQC();
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        {element}
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ── PricingPage ───────────────────────────────────────────────────────────────

describe('PricingPage', () => {
  beforeEach(() => {
    const { api } = useApiModule as any;
    api.get.mockImplementation((url: string) => {
      if (url.includes('/billing/plans')) {
        return Promise.resolve({ data: { plans: [
          { id: 'free',         name: 'Free',         price_usd_monthly: 0,     price_usd_annual: 0,      commission_rate: 0.010, features: ['paper_trading'],                                    limits: { signals_per_day: 5,   backtests_per_month: 3,  live_accounts: 0, max_strategies: 1,  max_brokers: 1  } },
          { id: 'starter',      name: 'Starter',      price_usd_monthly: 1800,  price_usd_annual: 18000,  commission_rate: 0.005, features: ['paper_trading', 'live_trading'],                    limits: { signals_per_day: 20,  backtests_per_month: 10, live_accounts: 1, max_strategies: 3,  max_brokers: 1  } },
          { id: 'professional', name: 'Professional', price_usd_monthly: 4500,  price_usd_annual: 45000,  commission_rate: 0.003, features: ['paper_trading', 'live_trading', 'api_access'],      limits: { signals_per_day: 100, backtests_per_month: 50, live_accounts: 3, max_strategies: 7,  max_brokers: 3  } },
          { id: 'enterprise',   name: 'Enterprise',   price_usd_monthly: 7500,  price_usd_annual: 75000,  commission_rate: 0.002, features: ['paper_trading', 'live_trading', 'white_label'],     limits: { signals_per_day: -1,  backtests_per_month: -1, live_accounts: -1, max_strategies: -1, max_brokers: -1 } },
          { id: 'elite',        name: 'Elite',        price_usd_monthly: 10000, price_usd_annual: 100000, commission_rate: 0.001, features: ['paper_trading', 'live_trading', 'dedicated_support'], limits: { signals_per_day: -1, backtests_per_month: -1, live_accounts: -1, max_strategies: -1, max_brokers: -1 } },
        ] } });
      }
      if (url.includes('/billing/subscription')) {
        return Promise.resolve({ data: { plan: 'free', tier: 'free', status: 'active' } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it('renders the pricing heading', async () => {
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => {
      // Multiple elements may contain the pricing heading text (title + subtitle)
      expect(screen.getAllByText(/simple.*transparent.*pricing/i).length).toBeGreaterThan(0);
    });
  });

  it('shows all 5 plan names after loading', async () => {
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => {
      // Multiple elements may contain the plan name (label + price display) — use getAllByText
      expect(screen.getAllByText('Free').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Starter').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Professional').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Enterprise').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Elite').length).toBeGreaterThan(0);
    });
  });

  it('shows monthly/annual toggle', async () => {
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => {
      expect(screen.getByText(/monthly/i)).toBeInTheDocument();
      expect(screen.getByText(/annual/i)).toBeInTheDocument();
    });
  });

  it('shows FAQ section', async () => {
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => {
      expect(screen.getByText(/frequently asked questions/i)).toBeInTheDocument();
    });
  });

  it('toggles to annual billing', async () => {
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => screen.getByText(/annual/i));
    fireEvent.click(screen.getByText(/annual/i));
    await waitFor(() => {
      // Each paid card shows what it is billed annually. It used to assert
      // "2 months free" — a commercial claim hardcoded in the UI (audit #70),
      // true only while the backend keeps the discount at ~17%.
      expect(screen.getAllByText(/Billed \$[\d,]+\/yr/i).length).toBeGreaterThan(0);
    });
    // The fixture states no annual_savings_pct, so no saving may be claimed.
    expect(screen.queryByText(/save \d+%/i)).toBeNull();
    expect(screen.queryByText(/months free/i)).toBeNull();
  });

  it('shows the saving the catalogue states, not a hardcoded one', async () => {
    // The API is the source of truth for the discount (audit #70).
    // Cast to the loose shape the other mocks in this file use — the component
    // only reads `.data`.
    vi.mocked(useApiModule.pricingApi.getPlans).mockResolvedValue({
      data: {
        plans: [{
          id: 'starter', name: 'Starter', price_usd_monthly: 1800,
          price_usd_annual: 16200, annual_savings_pct: 25, commission_rate: 0.005,
          features: ['live_trading'],
          limits: { signals_per_day: 20, backtests_per_month: 10, live_accounts: 1, max_strategies: 3, max_brokers: 1 },
        }],
      },
    } as Awaited<ReturnType<typeof useApiModule.pricingApi.getPlans>>);
    const PricingPage = (await import('../pages/PricingPage')).default;
    render(wrap(<PricingPage />));
    await waitFor(() => screen.getByText(/annual/i));
    fireEvent.click(screen.getByText(/annual/i));
    await waitFor(() => {
      expect(screen.getByText(/save 25%/i)).toBeInTheDocument();
    });
  });
});

// ── ResearchPage ──────────────────────────────────────────────────────────────

describe('ResearchPage', () => {
  it('renders the research heading', async () => {
    const ResearchPage = (await import('../pages/ResearchPage')).default;
    render(wrap(<ResearchPage />));
    await waitFor(() => {
      expect(screen.getByText('Research')).toBeInTheDocument();
    });
  });

  it('shows empty state when no notebooks', async () => {
    const ResearchPage = (await import('../pages/ResearchPage')).default;
    render(wrap(<ResearchPage />));
    await waitFor(() => {
      expect(screen.getByText(/no research notebooks yet/i)).toBeInTheDocument();
    });
  });

  it('shows New Notebook button', async () => {
    const ResearchPage = (await import('../pages/ResearchPage')).default;
    render(wrap(<ResearchPage />));
    await waitFor(() => {
      expect(screen.getByText(/\+ new notebook/i)).toBeInTheDocument();
    });
  });

  it('opens create modal on button click', async () => {
    const ResearchPage = (await import('../pages/ResearchPage')).default;
    render(wrap(<ResearchPage />));
    await waitFor(() => screen.getByText(/\+ new notebook/i));
    fireEvent.click(screen.getByText(/\+ new notebook/i));
    await waitFor(() => {
      expect(screen.getByText(/new research notebook/i)).toBeInTheDocument();
    });
  });

  it('shows notebooks when API returns data', async () => {
    const { researchApi } = useApiModule as any;
    researchApi.listNotebooks.mockResolvedValueOnce({ data: { notebooks: [
      { notebook_id: 'nb-1', title: 'XAUUSD Weekly', status: 'completed', symbol: 'XAUUSD', timeframe: 'H1', template: 'technical', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ], total: 1 } });
    const ResearchPage = (await import('../pages/ResearchPage')).default;
    render(wrap(<ResearchPage />));
    await waitFor(() => {
      expect(screen.getByText('XAUUSD Weekly')).toBeInTheDocument();
    });
  });
});

// ── TeamsPage ─────────────────────────────────────────────────────────────────

describe('TeamsPage', () => {
  it('renders the teams heading', async () => {
    const TeamsPage = (await import('../pages/TeamsPage')).default;
    render(wrap(<TeamsPage />));
    await waitFor(() => {
      expect(screen.getByText('Teams')).toBeInTheDocument();
    });
  });

  it('shows empty state when no teams', async () => {
    const TeamsPage = (await import('../pages/TeamsPage')).default;
    render(wrap(<TeamsPage />));
    await waitFor(() => {
      expect(screen.getByText(/no teams yet/i)).toBeInTheDocument();
    });
  });

  it('shows New Team button', async () => {
    const TeamsPage = (await import('../pages/TeamsPage')).default;
    render(wrap(<TeamsPage />));
    await waitFor(() => {
      expect(screen.getByText(/\+ new team/i)).toBeInTheDocument();
    });
  });

  it('shows create form on button click', async () => {
    const TeamsPage = (await import('../pages/TeamsPage')).default;
    render(wrap(<TeamsPage />));
    await waitFor(() => screen.getByText(/\+ new team/i));
    fireEvent.click(screen.getByText(/\+ new team/i));
    await waitFor(() => {
      expect(screen.getByText(/create team/i)).toBeInTheDocument();
    });
  });

  it('shows team list when API returns data', async () => {
    const { teamsApi } = useApiModule as any;
    teamsApi.list.mockResolvedValueOnce({ data: { teams: [
      { team_id: 't-1', name: 'Alpha Traders', description: 'Top team', owner_id: 'u-1', member_count: 3, status: 'active', created_at: '2026-01-01T00:00:00Z' },
    ], total: 1 } });
    const TeamsPage = (await import('../pages/TeamsPage')).default;
    render(wrap(<TeamsPage />));
    await waitFor(() => {
      expect(screen.getByText('Alpha Traders')).toBeInTheDocument();
    });
  });
});

// ── ReplayPage ────────────────────────────────────────────────────────────────

describe('ReplayPage', () => {
  it('renders the replay heading', async () => {
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => {
      // Multiple elements may contain "Market Replay" (breadcrumb + page title)
      expect(screen.getAllByText(/market replay/i).length).toBeGreaterThan(0);
    });
  });

  it('shows empty state when no sessions', async () => {
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => {
      expect(screen.getByText(/no replay sessions/i)).toBeInTheDocument();
    });
  });

  it('shows New Session button', async () => {
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => {
      expect(screen.getByText(/\+ new session/i)).toBeInTheDocument();
    });
  });

  it('shows create form on button click', async () => {
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => screen.getByText(/\+ new session/i));
    fireEvent.click(screen.getByText(/\+ new session/i));
    await waitFor(() => {
      expect(screen.getByText(/new replay session/i)).toBeInTheDocument();
    });
  });

  it('shows session list when API returns data', async () => {
    const { replayApi } = useApiModule as any;
    replayApi.listSessions.mockResolvedValueOnce({ data: { sessions: [
      { session_id: 'r-1', symbol: 'EURUSD', timeframe: 'M15', start_date: '2024-01-01', end_date: '2024-03-31', current_bar: 250, total_bars: 5000, status: 'paused', current_price: 1.0850, equity: 10500, pnl: 500, trades: [], bars: [] },
    ] } });
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => {
      expect(screen.getByText(/EURUSD/)).toBeInTheDocument();
    });
  });

  it('shows step and auto controls when session selected', async () => {
    const { replayApi } = useApiModule as any;
    const session = { session_id: 'r-1', symbol: 'XAUUSD', timeframe: 'H1', start_date: '2024-01-01', end_date: '2024-06-30', current_bar: 10, total_bars: 1000, status: 'running', current_price: 2050.0, equity: 10000, pnl: 0, trades: [], bars: [] };
    replayApi.listSessions.mockResolvedValueOnce({ data: { sessions: [session] } });
    const ReplayPage = (await import('../pages/ReplayPage')).default;
    render(wrap(<ReplayPage />));
    await waitFor(() => screen.getByText(/XAUUSD/));
    fireEvent.click(screen.getByText(/XAUUSD/));
    await waitFor(() => {
      // Button labels: "⏭ Step" and "▶ Play" (or "⏸ Pause" when playing)
      expect(screen.getByText(/⏭ step/i)).toBeInTheDocument();
      expect(screen.getByText(/▶ play|⏸ pause/i)).toBeInTheDocument();
    });
  });
});
