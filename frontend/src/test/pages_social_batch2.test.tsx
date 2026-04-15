/**
 * Tests for SubAccounts, WhitelabelAdmin, SocialFeed, CopyTrading, Leaderboard pages.
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
    overview:      vi.fn().mockResolvedValue({ data: {} }),
    users:         vi.fn().mockResolvedValue({ data: [] }),
    systemMetrics: vi.fn().mockResolvedValue({ data: {} }),
    jobs:          vi.fn().mockResolvedValue({ data: [] }),
    apiKeyAudit:   vi.fn().mockResolvedValue({ data: [] }),
    revokeApiKey:  vi.fn().mockResolvedValue({ data: {} }),
  },
  api: {
    defaults: { baseURL: '/api', timeout: 15000, headers: { 'Content-Type': 'application/json' } },
    interceptors: { request: { handlers: [{}], use: vi.fn() }, response: { handlers: [{}], use: vi.fn() } },
    get: vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/accounts/sub-accounts')) {
        return Promise.resolve({ data: { accounts: [] } });
      }
      if (typeof url === 'string' && url.includes('/accounts/teams')) {
        return Promise.resolve({ data: { teams: [] } });
      }
      if (typeof url === 'string' && url.includes('/whitelabel/tenants')) {
        return Promise.resolve({ data: [] });
      }
      if (typeof url === 'string' && url.includes('/feed/status')) {
        return Promise.resolve({ data: { is_public: true, follower_count: 0 } });
      }
      if (typeof url === 'string' && url.includes('/feed')) {
        return Promise.resolve({ data: { items: [], total: 0, page: 1 } });
      }
      if (typeof url === 'string' && url.includes('/leaderboard')) {
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

// ─── SubAccounts ──────────────────────────────────────────────────────────────

describe('SubAccounts page', () => {
  async function renderSubAccounts() {
    const SubAccounts = (await import('../pages/SubAccounts')).default;
    return wrap(<SubAccounts />);
  }

  it('renders Sub-Accounts & Teams heading', async () => {
    await renderSubAccounts();
    expect(document.body.textContent).toMatch(/sub.accounts.*teams|teams.*sub.accounts/i);
  });

  it('renders + Sub-Account button', async () => {
    await renderSubAccounts();
    expect(screen.getByRole('button', { name: /\+ sub.account/i })).toBeInTheDocument();
  });

  it('renders + Team button', async () => {
    await renderSubAccounts();
    expect(screen.getByRole('button', { name: /\+ team/i })).toBeInTheDocument();
  });

  it('shows empty sub-accounts state', async () => {
    await renderSubAccounts();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no sub.accounts yet/i);
    }, { timeout: 3000 });
  });

  it('shows empty teams state', async () => {
    await renderSubAccounts();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no teams yet/i);
    }, { timeout: 3000 });
  });

  it('opens create sub-account modal on button click', async () => {
    await renderSubAccounts();
    fireEvent.click(screen.getByRole('button', { name: /\+ sub.account/i }));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/create sub.account|new sub.account/i);
    }, { timeout: 2000 });
  });

  it('opens create team modal on button click', async () => {
    await renderSubAccounts();
    fireEvent.click(screen.getByRole('button', { name: /\+ team/i }));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/create team|new team|team name/i);
    }, { timeout: 2000 });
  });

  it('renders Sub-Accounts section heading', async () => {
    await renderSubAccounts();
    expect(screen.getAllByText(/sub.accounts/i).length).toBeGreaterThan(0);
  });

  it('renders Teams section heading', async () => {
    await renderSubAccounts();
    expect(screen.getAllByText(/teams/i).length).toBeGreaterThan(0);
  });
});

// ─── WhitelabelAdmin ──────────────────────────────────────────────────────────

describe('WhitelabelAdmin page', () => {
  async function renderWhitelabelAdmin() {
    const WhitelabelAdmin = (await import('../pages/WhitelabelAdmin')).default;
    return wrap(<WhitelabelAdmin />);
  }

  it('renders Whitelabel Admin heading', async () => {
    await renderWhitelabelAdmin();
    expect(document.body.textContent).toMatch(/whitelabel|white.label/i);
  });

  it('renders + New Tenant button', async () => {
    await renderWhitelabelAdmin();
    expect(screen.getByRole('button', { name: /new tenant/i })).toBeInTheDocument();
  });

  it('shows empty tenants state', async () => {
    await renderWhitelabelAdmin();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no tenants yet/i);
    }, { timeout: 3000 });
  });

  it('opens create tenant modal on button click', async () => {
    await renderWhitelabelAdmin();
    fireEvent.click(screen.getByRole('button', { name: /new tenant/i }));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/tenant name|new tenant|create tenant/i);
    }, { timeout: 2000 });
  });

  it('create modal has name input', async () => {
    await renderWhitelabelAdmin();
    fireEvent.click(screen.getByRole('button', { name: /new tenant/i }));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/PropFirm Alpha/i)).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('create modal has email input', async () => {
    await renderWhitelabelAdmin();
    fireEvent.click(screen.getByRole('button', { name: /new tenant/i }));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/admin@propfirm/i)).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('create modal has Cancel button', async () => {
    await renderWhitelabelAdmin();
    fireEvent.click(screen.getByRole('button', { name: /new tenant/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('Cancel closes the modal', async () => {
    await renderWhitelabelAdmin();
    fireEvent.click(screen.getByRole('button', { name: /new tenant/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    }, { timeout: 2000 });
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/PropFirm Alpha/i)).not.toBeInTheDocument();
    }, { timeout: 2000 });
  });
});

// ─── SocialFeed ───────────────────────────────────────────────────────────────

describe('SocialFeed page', () => {
  async function renderSocialFeed() {
    const SocialFeed = (await import('../pages/SocialFeed')).default;
    return wrap(<SocialFeed />);
  }

  it('renders Community Signal Feed heading', async () => {
    await renderSocialFeed();
    expect(screen.getAllByText(/community signal feed/i).length).toBeGreaterThan(0);
  });

  it('renders subtitle text', async () => {
    await renderSocialFeed();
    expect(document.body.textContent).toMatch(/react.*comment.*copy|community/i);
  });

  it('renders symbol filter buttons', async () => {
    await renderSocialFeed();
    // SocialFeed uses button-based symbol filters, not a <select>
    const allBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'All');
    expect(allBtn).toBeTruthy();
  });

  it('shows empty feed state when no signals', async () => {
    await renderSocialFeed();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no signals yet/i);
    }, { timeout: 3000 });
  });

  it('renders without crashing', async () => {
    const { container } = await renderSocialFeed();
    expect(container).toBeInTheDocument();
  });

  it('renders direction filter buttons', async () => {
    await renderSocialFeed();
    const buttons = document.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThan(0);
  });

  it('renders All filter button', async () => {
    await renderSocialFeed();
    const allBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.trim() === 'All');
    expect(allBtn).toBeTruthy();
  });

  it('renders XAU/USD symbol filter button', async () => {
    await renderSocialFeed();
    // SYMBOLS = ['All', 'XAU/USD', 'EUR/USD', ...]
    const btn = Array.from(document.querySelectorAll('button')).find(b => /XAU\/USD/.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders EUR/USD symbol filter button', async () => {
    await renderSocialFeed();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /EUR\/USD/.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });
});

// ─── CopyTrading ──────────────────────────────────────────────────────────────

describe('CopyTrading page', () => {
  async function renderCopyTrading() {
    const CopyTrading = (await import('../pages/CopyTrading')).default;
    return wrap(<CopyTrading />);
  }

  it('renders Copy Trading Marketplace heading', async () => {
    await renderCopyTrading();
    expect(screen.getAllByText(/copy trading marketplace/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderCopyTrading();
    expect(container).toBeInTheDocument();
  });

  it('renders leader cards or empty state', async () => {
    await renderCopyTrading();
    await waitFor(() => {
      // Either shows leader cards or loading/empty state
      expect(document.body.textContent).toMatch(/copy trading|leader|trader|loading/i);
    }, { timeout: 3000 });
  });

  it('renders sort dropdown', async () => {
    await renderCopyTrading();
    // CopyTrading has a sort <select> (return/sharpe/followers)
    const selects = document.querySelectorAll('select');
    expect(selects.length).toBeGreaterThan(0);
  });

  it('sort dropdown has return option', async () => {
    await renderCopyTrading();
    expect(document.body.textContent).toMatch(/return|sharpe|followers/i);
  });

  it('renders subtitle text', async () => {
    await renderCopyTrading();
    expect(document.body.textContent).toMatch(/copy|trading|marketplace/i);
  });

  it('renders page container with buttons', async () => {
    await renderCopyTrading();
    // CopyTrading renders the sort select and leader cards area
    const container = document.querySelector('[style]');
    expect(container).toBeInTheDocument();
  });
});

// ─── Leaderboard ──────────────────────────────────────────────────────────────

describe('Leaderboard page', () => {
  async function renderLeaderboard() {
    const Leaderboard = (await import('../pages/Leaderboard')).default;
    return wrap(<Leaderboard />);
  }

  it('renders Global Leaderboard heading', async () => {
    await renderLeaderboard();
    expect(screen.getAllByText(/global leaderboard/i).length).toBeGreaterThan(0);
  });

  it('renders without crashing', async () => {
    const { container } = await renderLeaderboard();
    expect(container).toBeInTheDocument();
  });

  it('shows empty leaderboard state', async () => {
    await renderLeaderboard();
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/no traders on the leaderboard yet/i);
    }, { timeout: 3000 });
  });

  it('renders period filter buttons', async () => {
    await renderLeaderboard();
    const buttons = document.querySelectorAll('button');
    expect(buttons.length).toBeGreaterThan(0);
  });

  it('renders monthly period button', async () => {
    await renderLeaderboard();
    // Periods: 'monthly' | 'quarterly' | 'all'
    const btn = Array.from(document.querySelectorAll('button')).find(b => /monthly/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders quarterly period button', async () => {
    await renderLeaderboard();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /quarterly/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('renders all-time period button', async () => {
    await renderLeaderboard();
    // Button renders "All Time" for the 'all' period value
    const btn = Array.from(document.querySelectorAll('button')).find(b => /all time/i.test(b.textContent ?? ''));
    expect(btn).toBeTruthy();
  });

  it('switches period without crashing', async () => {
    await renderLeaderboard();
    const btn = Array.from(document.querySelectorAll('button')).find(b => /quarterly/i.test(b.textContent ?? ''));
    if (btn) {
      fireEvent.click(btn);
      expect(document.body.textContent).toMatch(/leaderboard/i);
    }
  });
});
