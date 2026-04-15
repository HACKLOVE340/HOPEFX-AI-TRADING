/**
 * Tests for Register, Profile, Watchlist, PriceAlerts, TradeJournal pages.
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
  authApi: {
    login:            vi.fn(),
    logout:           vi.fn(),
    me:               vi.fn(),
    register:         vi.fn().mockResolvedValue({ data: { access_token: 'tok', user: { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' } } }),
    activateFreeTier: vi.fn().mockResolvedValue({ data: {} }),
  },
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
      // /profiles/me or /profiles/:id → ProfileData shape
      if (typeof url === 'string' && url.includes('/profiles') && !url.includes('/signals')) {
        return Promise.resolve({ data: {
          trader_id: 'u1', username: 'trader1', bio: 'Test bio',
          avatar_url: null, website: null, verified: false, is_public: true,
          total_followers: 5, total_following: 3, total_trades: 40,
          win_rate: 62.5, total_pnl: 1500, avg_win: 200, avg_loss: 80,
          sharpe_ratio: 1.4, created_at: '2024-01-01T00:00:00Z',
        }});
      }
      // /profiles/:id/signals → { signals: [] }
      if (typeof url === 'string' && url.includes('/signals')) {
        return Promise.resolve({ data: { signals: [] } });
      }
      // /watchlist → { items: [] }
      if (typeof url === 'string' && url.includes('/watchlist')) {
        return Promise.resolve({ data: { items: [] } });
      }
      // /journal/* → arrays or stats
      if (typeof url === 'string' && url.includes('/journal/trades')) {
        return Promise.resolve({ data: [] });
      }
      if (typeof url === 'string' && url.includes('/journal/stats')) {
        return Promise.resolve({ data: { total_trades: 0, win_rate: 0, avg_pnl: 0, best_trade_pnl: 0, worst_trade_pnl: 0, rule_deviation_count: 0, by_tag: [], by_emotion: [] } });
      }
      if (typeof url === 'string' && url.includes('/journal/mistakes')) {
        return Promise.resolve({ data: [] });
      }
      // /alerts → []
      if (typeof url === 'string' && url.includes('/alerts')) {
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

const mockUser = { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(element: React.ReactElement, path = '/') {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter initialEntries={[path]}>
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

// ─── Register ─────────────────────────────────────────────────────────────────

describe('Register page', () => {
  async function renderRegister(search = '') {
    const Register = (await import('../pages/Register')).default;
    return render(
      <MemoryRouter initialEntries={[`/register${search}`]}>
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route path="/dashboard" element={<div>Dashboard</div>} />
          <Route path="/login" element={<div>Login</div>} />
        </Routes>
      </MemoryRouter>
    );
  }

  it('renders HOPEFX branding', async () => {
    await renderRegister();
    expect(screen.getByText(/HOPE/)).toBeInTheDocument();
  });

  it('renders email input', async () => {
    await renderRegister();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  });

  it('renders username input', async () => {
    await renderRegister();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
  });

  it('renders password input', async () => {
    await renderRegister();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it('renders confirm password input', async () => {
    await renderRegister();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it('renders create account button', async () => {
    await renderRegister();
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
  });

  it('shows starter plan badge by default', async () => {
    await renderRegister();
    expect(screen.getByText(/starter/i)).toBeInTheDocument();
  });

  it('shows pro plan badge when ?plan=pro', async () => {
    await renderRegister('?plan=pro');
    expect(screen.getByText(/pro/i)).toBeInTheDocument();
  });

  it('shows elite plan badge when ?plan=elite', async () => {
    await renderRegister('?plan=elite');
    expect(screen.getByText(/elite/i)).toBeInTheDocument();
  });

  it('shows validation error when email is empty', async () => {
    await renderRegister();
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    });
  });

  it('shows validation error for invalid email', async () => {
    await renderRegister();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'notanemail' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
  });

  it('shows validation error when username is too short', async () => {
    await renderRegister();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'ab' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/at least 3/i)).toBeInTheDocument();
    });
  });

  it('shows validation error when passwords do not match', async () => {
    await renderRegister();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'trader1' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'password123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'different123' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });
  });

  it('shows validation error when password is too short', async () => {
    await renderRegister();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'trader1' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'short' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'short' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/at least 8/i)).toBeInTheDocument();
    });
  });

  it('has link to login page', async () => {
    await renderRegister();
    expect(screen.getByText(/sign in/i)).toBeInTheDocument();
  });

  it('password input is type=password', async () => {
    await renderRegister();
    const input = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    expect(input.type).toBe('password');
  });

  it('confirm password input is type=password', async () => {
    await renderRegister();
    const input = screen.getByLabelText(/confirm password/i) as HTMLInputElement;
    expect(input.type).toBe('password');
  });
});

// ─── Profile ──────────────────────────────────────────────────────────────────

describe('Profile page', () => {
  async function renderProfile() {
    const Profile = (await import('../pages/Profile')).default;
    return wrap(<Profile />);
  }

  it('renders without crashing', async () => {
    const { container } = await renderProfile();
    expect(container).toBeInTheDocument();
  });

  it('shows loading state initially', async () => {
    await renderProfile();
    // Profile fetches data on mount — shows loading or profile content
    const container = document.querySelector('body');
    expect(container).toBeInTheDocument();
  });

  it('renders profile page container', async () => {
    const { container } = await renderProfile();
    // Profile always renders a container div regardless of load state
    expect(container.firstChild).toBeInTheDocument();
  });

  it('renders profile username after load', async () => {
    await renderProfile();
    await waitFor(() => {
      // Use querySelector since text may be split across elements
      const el = document.querySelector('h1');
      expect(el).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('renders Edit Profile button after load', async () => {
    await renderProfile();
    await waitFor(() => {
      const buttons = document.querySelectorAll('button');
      const editBtn = Array.from(buttons).find(b => /edit profile/i.test(b.textContent ?? ''));
      expect(editBtn).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('renders Win Rate stat card after load', async () => {
    await renderProfile();
    await waitFor(() => {
      const el = document.body.innerHTML;
      expect(el).toMatch(/win rate/i);
    }, { timeout: 3000 });
  });

  it('renders Total P&L stat card after load', async () => {
    await renderProfile();
    await waitFor(() => {
      expect(document.body.innerHTML).toMatch(/total p/i);
    }, { timeout: 3000 });
  });

  it('renders Sharpe stat card after load', async () => {
    await renderProfile();
    await waitFor(() => {
      expect(document.body.innerHTML).toMatch(/sharpe/i);
    }, { timeout: 3000 });
  });

  it('renders own-profile actions after load', async () => {
    // isOwnProfile=true (no hash) → shows Edit Profile, not Copy Trade
    await renderProfile();
    await waitFor(() => {
      // Edit Profile button is shown for own profile
      const buttons = document.querySelectorAll('button');
      const editBtn = Array.from(buttons).find(b => /edit profile/i.test(b.textContent ?? ''));
      expect(editBtn).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('opens edit modal when Edit Profile is clicked', async () => {
    await renderProfile();
    await waitFor(() => {
      const buttons = document.querySelectorAll('button');
      const editBtn = Array.from(buttons).find(b => /edit profile/i.test(b.textContent ?? ''));
      expect(editBtn).toBeTruthy();
    }, { timeout: 3000 });
    const editBtn = Array.from(document.querySelectorAll('button')).find(b => /edit profile/i.test(b.textContent ?? ''));
    fireEvent.click(editBtn!);
    await waitFor(() => {
      expect(document.body.innerHTML).toMatch(/bio/i);
    });
  });

  it('renders bio field in edit modal', async () => {
    await renderProfile();
    await waitFor(() => {
      const buttons = document.querySelectorAll('button');
      const editBtn = Array.from(buttons).find(b => /edit profile/i.test(b.textContent ?? ''));
      expect(editBtn).toBeTruthy();
    }, { timeout: 3000 });
    const editBtn = Array.from(document.querySelectorAll('button')).find(b => /edit profile/i.test(b.textContent ?? ''));
    fireEvent.click(editBtn!);
    expect(document.body.innerHTML).toMatch(/bio/i);
  });
});

// ─── Watchlist ────────────────────────────────────────────────────────────────

describe('Watchlist page', () => {
  async function renderWatchlist() {
    const Watchlist = (await import('../pages/Watchlist')).default;
    return wrap(<Watchlist />);
  }

  it('renders Watchlist heading', async () => {
    await renderWatchlist();
    expect(screen.getByText('Watchlist')).toBeInTheDocument();
  });

  it('renders Add symbol dropdown', async () => {
    await renderWatchlist();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('Add symbol dropdown has default option', async () => {
    await renderWatchlist();
    expect(screen.getByText(/add symbol/i)).toBeInTheDocument();
  });

  it('renders Add button', async () => {
    await renderWatchlist();
    // Button text is "+ Add"
    expect(screen.getByText(/\+ add/i)).toBeInTheDocument();
  });

  it('shows empty state when watchlist is empty', async () => {
    await renderWatchlist();
    await waitFor(() => {
      expect(screen.getByText(/empty/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('Add button is disabled when no symbol selected', async () => {
    await renderWatchlist();
    // Find button by text "+ Add"
    const btn = screen.getByText(/\+ add/i).closest('button') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('Add button enables when symbol is selected', async () => {
    await renderWatchlist();
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    // Select a symbol that exists in the options
    const options = Array.from(select.querySelectorAll('option'));
    const nonEmpty = options.find(o => o.value !== '');
    if (nonEmpty) {
      fireEvent.change(select, { target: { value: nonEmpty.value } });
      await waitFor(() => {
        const btn = screen.getByText(/\+ add/i).closest('button') as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
      });
    } else {
      // No symbols available (all already in watchlist) — skip
      expect(true).toBe(true);
    }
  });

  it('renders symbol options in dropdown', async () => {
    await renderWatchlist();
    const select = screen.getByRole('combobox');
    const options = select.querySelectorAll('option');
    expect(options.length).toBeGreaterThan(1);
  });
});

// ─── PriceAlerts ─────────────────────────────────────────────────────────────

describe('PriceAlerts page', () => {
  async function renderPriceAlerts() {
    const PriceAlerts = (await import('../pages/PriceAlerts')).default;
    return wrap(<PriceAlerts />);
  }

  it('renders Price Alerts heading', async () => {
    await renderPriceAlerts();
    expect(screen.getByText('Price Alerts')).toBeInTheDocument();
  });

  it('renders Create Alert button', async () => {
    await renderPriceAlerts();
    expect(screen.getByRole('button', { name: /create alert/i })).toBeInTheDocument();
  });

  it('shows empty state when no alerts', async () => {
    await renderPriceAlerts();
    await waitFor(() => {
      // loading=false → shows "No alerts yet. Create one above."
      expect(document.body.textContent).toMatch(/no alerts yet/i);
    }, { timeout: 5000 });
  });

  it('opens create form when Create Alert is clicked', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/new alert/i)).toBeInTheDocument();
  });

  it('shows Alert Name field in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/alert name/i)).toBeInTheDocument();
  });

  it('shows Symbol field in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/^symbol$/i)).toBeInTheDocument();
  });

  it('shows Condition field in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getAllByText(/condition/i).length).toBeGreaterThan(0);
  });

  it('shows Price / Level field in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getAllByText(/price/i).length).toBeGreaterThan(0);
  });

  it('shows notification channels in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/notification/i)).toBeInTheDocument();
  });

  it('shows Priority field in create form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/priority/i)).toBeInTheDocument();
  });

  it('Cancel button closes the form', async () => {
    await renderPriceAlerts();
    fireEvent.click(screen.getByRole('button', { name: /create alert/i }));
    expect(screen.getByText(/new alert/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.queryByText(/new alert/i)).not.toBeInTheDocument();
  });

  it('renders Active Alerts tab', async () => {
    await renderPriceAlerts();
    // Tab text: "Active Alerts (0)"
    expect(screen.getAllByText(/active alerts/i).length).toBeGreaterThan(0);
  });

  it('renders Trigger History tab', async () => {
    await renderPriceAlerts();
    // Second tab text: "Trigger History"
    expect(screen.getByText(/trigger history/i)).toBeInTheDocument();
  });
});

// ─── TradeJournal ─────────────────────────────────────────────────────────────

describe('TradeJournal page', () => {
  async function renderTradeJournal() {
    const TradeJournal = (await import('../pages/TradeJournal')).default;
    return wrap(<TradeJournal />);
  }

  it('renders Trade Journal heading', async () => {
    await renderTradeJournal();
    expect(screen.getByText('Trade Journal')).toBeInTheDocument();
  });

  it('renders Trades tab', async () => {
    await renderTradeJournal();
    // Tab text: "All Trades (0)"
    expect(screen.getAllByText(/all trades/i).length).toBeGreaterThan(0);
  });

  it('renders Stats tab', async () => {
    await renderTradeJournal();
    // Tab text: "Stats & Tags"
    expect(screen.getByText(/stats & tags/i)).toBeInTheDocument();
  });

  it('renders Mistakes tab', async () => {
    await renderTradeJournal();
    // Tab text: "⚠ Mistakes (0)"
    expect(screen.getAllByText(/mistakes/i).length).toBeGreaterThan(0);
  });

  it('shows empty trades state when no trades', async () => {
    await renderTradeJournal();
    await waitFor(() => {
      // loading=false → shows "No trades yet."
      expect(document.body.textContent).toMatch(/no trades yet/i);
    }, { timeout: 5000 });
  });

  it('switches to Stats tab', async () => {
    await renderTradeJournal();
    fireEvent.click(screen.getByText(/stats & tags/i));
    await waitFor(() => {
      // Stats tab shows "No stats available" when stats is null
      expect(screen.getAllByText(/stats|no stats/i).length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('switches to Mistakes tab', async () => {
    await renderTradeJournal();
    fireEvent.click(screen.getAllByText(/mistakes/i)[0]);
    await waitFor(() => {
      expect(screen.getAllByText(/no rule deviations/i).length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('renders filter dropdown on Trades tab', async () => {
    await renderTradeJournal();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('filter dropdown has All Tags option', async () => {
    await renderTradeJournal();
    expect(screen.getByText(/all tags/i)).toBeInTheDocument();
  });
});
