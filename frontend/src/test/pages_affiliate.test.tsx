/**
 * Affiliate page — unit tests
 *
 * Covers:
 * - Unauthenticated state (no userId)
 * - Loading state
 * - Error state with retry button
 * - Not-enrolled state (join program CTA)
 * - Tier cards (bronze/silver/gold/platinum)
 * - Signup flow (success + error)
 * - Enrolled state: referral link, copy button, level badge
 * - Overview tab: metric cards
 * - Referrals tab: table, empty state, error
 * - Leaderboard tab: table, rank medals, error
 * - Tab switching
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

// ── Fixtures ──────────────────────────────────────────────────────────────────

const AFFILIATE_ACCOUNT = {
  affiliate_id: 'aff1',
  code: 'TRADER123',
  level: 'gold' as const,
  commission_rate: 0.20,
  status: 'active',
};

const AFFILIATE_METRICS = {
  total_referrals: 18,
  converted_referrals: 12,
  total_revenue: 4800,
  total_commissions: 960,
  pending_commissions: 240,
  conversion_rate: 66.7,
};

const REFERRALS = [
  {
    referral_id: 'r1',
    referred_user_id: 'user_abc',
    status: 'converted' as const,
    created_at: '2025-01-10T10:00:00Z',
    converted_at: '2025-01-15T10:00:00Z',
    commission_amount: 49,
  },
  {
    referral_id: 'r2',
    referred_user_id: 'user_def',
    status: 'pending' as const,
    created_at: '2025-02-01T08:00:00Z',
  },
];

const LEADERBOARD = [
  { rank: 1, affiliate_id: 'aff_top', code: 'TOPTRADER', level: 'platinum', total_commissions: 5200, converted_referrals: 45 },
  { rank: 2, affiliate_id: 'aff1',    code: 'TRADER123', level: 'gold',     total_commissions: 960,  converted_referrals: 12 },
  { rank: 3, affiliate_id: 'aff3',    code: 'SILVER99',  level: 'silver',   total_commissions: 420,  converted_referrals: 7  },
];

// ── Mocks ─────────────────────────────────────────────────────────────────────

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({
  mockApiGet:  vi.fn(),
  mockApiPost: vi.fn(),
}));

vi.mock('../hooks/useApi', () => ({
  api: {
    get:  mockApiGet,
    post: mockApiPost,
    defaults: { baseURL: '/api', timeout: 15000, headers: { 'Content-Type': 'application/json' } },
    interceptors: {
      request:  { handlers: [{}], use: vi.fn() },
      response: { handlers: [{}], use: vi.fn() },
    },
  },
  tradingApi:     { positions: vi.fn().mockResolvedValue({ data: [] }) },
  authApi:        { login: vi.fn(), logout: vi.fn(), me: vi.fn() },
  backtestApi:    { run: vi.fn(), results: vi.fn(), list: vi.fn() },
  mlApi:          { accuracy: vi.fn().mockResolvedValue({ data: {} }) },
  performanceApi: { summary: vi.fn().mockResolvedValue({ data: {} }) },
  signalsApi:     { active: vi.fn().mockResolvedValue({ data: [] }) },
  affiliateApi: {
    account:        (userId: string) => mockApiGet(`/monetization/affiliate/${userId}`),
    signup:         (payload: object) => mockApiPost('/monetization/affiliate/signup', payload),
    referrals:      (affiliateId: string, params?: object) => mockApiGet(`/monetization/affiliate/${affiliateId}/referrals`, { params }),
    leaderboard:    (params?: object) => mockApiGet('/monetization/affiliate/leaderboard', { params }),
    withdraw:       (affiliateId: string, amount: number) => mockApiPost(`/monetization/affiliate/${affiliateId}/withdraw`, { amount }),
    commissions:    (affiliateId: string, params?: object) => mockApiGet(`/monetization/affiliate/${affiliateId}/commissions`, { params }),
    updatePayment:  (affiliateId: string, payload: object) => mockApiPost(`/monetization/affiliate/${affiliateId}/payment-method`, payload),
  },
  socialApi: {
    feed:             vi.fn().mockResolvedValue({ data: { items: [], total: 0, page: 1 } }),
    react:            vi.fn().mockResolvedValue({ data: {} }),
    comments:         vi.fn().mockResolvedValue({ data: { comments: [] } }),
    addComment:       vi.fn().mockResolvedValue({ data: {} }),
    optIn:            vi.fn().mockResolvedValue({ data: {} }),
    optOut:           vi.fn().mockResolvedValue({ data: {} }),
    optStatus:        vi.fn().mockResolvedValue({ data: { opted_in: false } }),
    copyTrader:       vi.fn().mockResolvedValue({ data: {} }),
    stopCopy:         vi.fn().mockResolvedValue({ data: {} }),
    activeCopies:     vi.fn().mockResolvedValue({ data: [] }),
    updateAllocation: vi.fn().mockResolvedValue({ data: {} }),
    profile:          vi.fn().mockResolvedValue({ data: {} }),
    follow:           vi.fn().mockResolvedValue({ data: {} }),
    unfollow:         vi.fn().mockResolvedValue({ data: {} }),
  },
  profileApi: {
    get:          vi.fn().mockResolvedValue({ data: {} }),
    update:       vi.fn().mockResolvedValue({ data: {} }),
    uploadAvatar: vi.fn().mockResolvedValue({ data: {} }),
    follow:       vi.fn().mockResolvedValue({ data: {} }),
    unfollow:     vi.fn().mockResolvedValue({ data: {} }),
    followers:    vi.fn().mockResolvedValue({ data: [] }),
    following:    vi.fn().mockResolvedValue({ data: [] }),
    signals:      vi.fn().mockResolvedValue({ data: [] }),
    strategies:   vi.fn().mockResolvedValue({ data: [] }),
    stats:        vi.fn().mockResolvedValue({ data: {} }),
  },
  adminApi: {
    users:           vi.fn().mockResolvedValue({ data: { users: [], total: 0 } }),
    user:            vi.fn().mockResolvedValue({ data: {} }),
    updateUser:      vi.fn().mockResolvedValue({ data: {} }),
    banUser:         vi.fn().mockResolvedValue({ data: {} }),
    unbanUser:       vi.fn().mockResolvedValue({ data: {} }),
    resetPassword:   vi.fn().mockResolvedValue({ data: {} }),
    auditLog:        vi.fn().mockResolvedValue({ data: { events: [], total: 0 } }),
    auditExport:     vi.fn().mockResolvedValue({ data: {} }),
    platformConfig:  vi.fn().mockResolvedValue({ data: {} }),
    updateConfig:    vi.fn().mockResolvedValue({ data: {} }),
    maintenanceMode: vi.fn().mockResolvedValue({ data: {} }),
    kycList:         vi.fn().mockResolvedValue({ data: { kyc: [] } }),
    kycApprove:      vi.fn().mockResolvedValue({ data: {} }),
    kycReject:       vi.fn().mockResolvedValue({ data: {} }),
    lockdown:        vi.fn().mockResolvedValue({ data: {} }),
    unblockIp:       vi.fn().mockResolvedValue({ data: {} }),
    blockIp:         vi.fn().mockResolvedValue({ data: {} }),
  },
  marketplaceApi: {
    strategies:      vi.fn().mockResolvedValue({ data: { strategies: [], total: 0 } }),
    strategy:        vi.fn().mockResolvedValue({ data: {} }),
    purchase:        vi.fn().mockResolvedValue({ data: {} }),
    featured:        vi.fn().mockResolvedValue({ data: [] }),
    stats:           vi.fn().mockResolvedValue({ data: {} }),
    list:            vi.fn().mockResolvedValue({ data: { strategies: [], total: 0 } }),
    myStrategies:    vi.fn().mockResolvedValue({ data: { strategies: [] } }),
    review:          vi.fn().mockResolvedValue({ data: {} }),
    reviews:         vi.fn().mockResolvedValue({ data: { reviews: [] } }),
    unsubscribe:     vi.fn().mockResolvedValue({ data: {} }),
    mySubscriptions: vi.fn().mockResolvedValue({ data: [] }),
  },
  journalApi: {
    trades:       vi.fn().mockResolvedValue({ data: { trades: [], total: 0 } }),
    trade:        vi.fn().mockResolvedValue({ data: {} }),
    updateTrade:  vi.fn().mockResolvedValue({ data: {} }),
    stats:        vi.fn().mockResolvedValue({ data: {} }),
    mistakes:     vi.fn().mockResolvedValue({ data: { mistakes: [] } }),
    emotionStats: vi.fn().mockResolvedValue({ data: {} }),
    weeklyReport: vi.fn().mockResolvedValue({ data: {} }),
    export:       vi.fn().mockResolvedValue({ data: {} }),
    tags:         vi.fn().mockResolvedValue({ data: [] }),
  },
  resetCsrfCache:    vi.fn(),
  getCsrfToken:      vi.fn().mockResolvedValue(null),
  prefetchCsrfToken: vi.fn().mockResolvedValue(undefined),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const mockUser = { id: 'u1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

function setupEnrolledMocks() {
  mockApiGet.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/monetization/affiliate/u1') && !url.includes('/referrals')) {
      return Promise.resolve({
        data: {
          has_affiliate_account: true,
          affiliate: AFFILIATE_ACCOUNT,
          metrics: AFFILIATE_METRICS,
        },
      });
    }
    if (typeof url === 'string' && url.includes('/referrals')) {
      return Promise.resolve({ data: { referrals: REFERRALS } });
    }
    if (typeof url === 'string' && url.includes('/leaderboard')) {
      return Promise.resolve({ data: { leaderboard: LEADERBOARD } });
    }
    return Promise.resolve({ data: {} });
  });
  mockApiPost.mockResolvedValue({ data: {} });
}

function setupNotEnrolledMocks() {
  mockApiGet.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/monetization/affiliate/u1') && !url.includes('/referrals')) {
      return Promise.resolve({
        data: { has_affiliate_account: false },
      });
    }
    if (typeof url === 'string' && url.includes('/leaderboard')) {
      return Promise.resolve({ data: { leaderboard: [] } });
    }
    return Promise.resolve({ data: {} });
  });
  mockApiPost.mockResolvedValue({ data: {} });
}

async function renderAffiliate() {
  const Affiliate = (await import('../pages/Affiliate')).default;
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/affiliate']}>
        <Routes>
          <Route path="*" element={<Affiliate />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Affiliate — unauthenticated', () => {
  beforeEach(() => {
    setupNotEnrolledMocks();
    useStore.setState({ token: null, user: null, isAuthenticated: false, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders without crashing', async () => {
    await renderAffiliate();
    expect(document.body).toBeTruthy();
  });

  it('shows login prompt when not authenticated', async () => {
    await renderAffiliate();
    expect(screen.getByText(/please log in/i)).toBeInTheDocument();
  });

  it('does not call API when no userId', async () => {
    await renderAffiliate();
    expect(mockApiGet).not.toHaveBeenCalled();
  });
});

describe('Affiliate — loading state', () => {
  beforeEach(() => {
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('shows loading state initially', async () => {
    let resolve: (v: unknown) => void;
    mockApiGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderAffiliate();
    expect(screen.getByText(/loading affiliate data/i)).toBeInTheDocument();
    resolve!({ data: { has_affiliate_account: false } });
  });
});

describe('Affiliate — error state', () => {
  beforeEach(() => {
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('shows error message when API fails', async () => {
    mockApiGet.mockRejectedValue(new Error('Connection refused'));
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText(/connection refused/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows Retry button on error', async () => {
    mockApiGet.mockRejectedValue(new Error('Connection refused'));
    await renderAffiliate();
    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Retry button calls API again', async () => {
    mockApiGet.mockRejectedValue(new Error('Connection refused'));
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /retry/i }), { timeout: 3000 });
    const callsBefore = mockApiGet.mock.calls.length;
    // Set up success for retry
    mockApiGet.mockResolvedValueOnce({ data: { has_affiliate_account: false } });
    mockApiGet.mockResolvedValueOnce({ data: { leaderboard: [] } });
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    await waitFor(() => expect(mockApiGet.mock.calls.length).toBeGreaterThan(callsBefore), { timeout: 3000 });
  });
});

describe('Affiliate — not enrolled', () => {
  beforeEach(() => {
    setupNotEnrolledMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders Affiliate Program heading', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Affiliate Program')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows Earn by referring traders heading', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText(/earn by referring traders/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows all 4 tier cards', async () => {
    await renderAffiliate();
    await waitFor(() => {
      expect(screen.getByText('bronze')).toBeInTheDocument();
      expect(screen.getByText('silver')).toBeInTheDocument();
      expect(screen.getByText('gold')).toBeInTheDocument();
      expect(screen.getByText('platinum')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows commission rates for each tier', async () => {
    await renderAffiliate();
    await waitFor(() => {
      expect(screen.getByText('10%')).toBeInTheDocument();
      expect(screen.getByText('15%')).toBeInTheDocument();
      expect(screen.getByText('20%')).toBeInTheDocument();
      expect(screen.getByText('25%')).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows Join the affiliate program button', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByRole('button', { name: /join the affiliate program/i })).toBeInTheDocument(), { timeout: 3000 });
  });

  it('signup button calls POST /monetization/affiliate/signup', async () => {
    // After signup, reload shows enrolled
    mockApiPost.mockResolvedValueOnce({ data: {} });
    mockApiGet
      .mockResolvedValueOnce({ data: { has_affiliate_account: false } })
      .mockResolvedValueOnce({ data: { leaderboard: [] } })
      .mockResolvedValueOnce({
        data: { has_affiliate_account: true, affiliate: AFFILIATE_ACCOUNT, metrics: AFFILIATE_METRICS },
      })
      .mockResolvedValueOnce({ data: { referrals: [] } })
      .mockResolvedValueOnce({ data: { leaderboard: [] } });
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /join the affiliate program/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /join the affiliate program/i }));
    await waitFor(() => expect(mockApiPost).toHaveBeenCalledWith(
      '/monetization/affiliate/signup',
      expect.objectContaining({ user_id: 'u1' })
    ), { timeout: 3000 });
  });

  it('shows Joining… while signup is in progress', async () => {
    let resolve: (v: unknown) => void;
    mockApiPost.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /join the affiliate program/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /join the affiliate program/i }));
    expect(screen.getByText(/joining/i)).toBeInTheDocument();
    resolve!({ data: {} });
  });

  it('shows error when signup fails', async () => {
    mockApiPost.mockRejectedValueOnce(new Error('Signup service unavailable'));
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /join the affiliate program/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /join the affiliate program/i }));
    await waitFor(() => expect(screen.getByText(/signup service unavailable/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Affiliate — enrolled: overview tab', () => {
  beforeEach(() => {
    setupEnrolledMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders Affiliate Program heading', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Affiliate Program')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows GOLD level badge', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('GOLD')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows commission rate', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText(/20% commission/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows referral link with code', async () => {
    await renderAffiliate();
    // Code appears in both the link card and leaderboard — at least one match
    await waitFor(() => expect(screen.getAllByText(/TRADER123/).length).toBeGreaterThan(0), { timeout: 3000 });
  });

  it('shows Copy link button', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows Total referrals metric', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Total referrals')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('18')).toBeInTheDocument();
  });

  it('shows Converted metric', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Converted')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('shows Total earned metric', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Total earned')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('$960.00')).toBeInTheDocument();
  });

  it('shows Pending payout metric', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText('Pending payout')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('$240.00')).toBeInTheDocument();
  });

  it('shows How commissions work section', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText(/how commissions work/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows conversion rate sub-label', async () => {
    await renderAffiliate();
    await waitFor(() => expect(screen.getByText(/66.7% rate/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Affiliate — enrolled: tabs', () => {
  beforeEach(() => {
    setupEnrolledMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders Overview, Referrals, Leaderboard tabs', async () => {
    await renderAffiliate();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^overview$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^referrals$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^leaderboard$/i })).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('Referrals tab shows referral table', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText('Referral history')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Referrals tab shows referred user IDs', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText('user_abc')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('user_def')).toBeInTheDocument();
  });

  it('Referrals tab shows status badges', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText('converted')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('Referrals tab shows commission amount', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText('$49.00')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Leaderboard tab shows top affiliates table', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('Top affiliates')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Leaderboard tab shows affiliate codes', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('TOPTRADER')).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText('SILVER99')).toBeInTheDocument();
  });

  it('Leaderboard tab shows gold medal for rank 1', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('🥇')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Leaderboard tab shows silver medal for rank 2', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('🥈')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Leaderboard tab shows bronze medal for rank 3', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('🥉')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('Leaderboard tab shows earned commissions', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText('$5,200.00')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('switching back to Overview tab shows metrics', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^overview$/i }));
    await waitFor(() => expect(screen.getByText('Total referrals')).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Affiliate — enrolled: referrals empty state', () => {
  beforeEach(() => {
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/monetization/affiliate/u1') && !url.includes('/referrals')) {
        return Promise.resolve({
          data: { has_affiliate_account: true, affiliate: AFFILIATE_ACCOUNT, metrics: AFFILIATE_METRICS },
        });
      }
      if (typeof url === 'string' && url.includes('/referrals')) {
        return Promise.resolve({ data: { referrals: [] } });
      }
      if (typeof url === 'string' && url.includes('/leaderboard')) {
        return Promise.resolve({ data: { leaderboard: [] } });
      }
      return Promise.resolve({ data: {} });
    });
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('shows no referrals message when list is empty', async () => {
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText(/no referrals yet/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Affiliate — enrolled: sub-errors', () => {
  beforeEach(() => {
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('shows referral error when referrals API fails', async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/monetization/affiliate/u1') && !url.includes('/referrals')) {
        return Promise.resolve({
          data: { has_affiliate_account: true, affiliate: AFFILIATE_ACCOUNT, metrics: AFFILIATE_METRICS },
        });
      }
      if (typeof url === 'string' && url.includes('/referrals')) {
        return Promise.reject(new Error('Referrals service down'));
      }
      if (typeof url === 'string' && url.includes('/leaderboard')) {
        return Promise.resolve({ data: { leaderboard: [] } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^referrals$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^referrals$/i }));
    await waitFor(() => expect(screen.getByText(/referrals service down/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows leaderboard error when leaderboard API fails', async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/monetization/affiliate/u1') && !url.includes('/referrals')) {
        return Promise.resolve({
          data: { has_affiliate_account: true, affiliate: AFFILIATE_ACCOUNT, metrics: AFFILIATE_METRICS },
        });
      }
      if (typeof url === 'string' && url.includes('/referrals')) {
        return Promise.resolve({ data: { referrals: [] } });
      }
      if (typeof url === 'string' && url.includes('/leaderboard')) {
        return Promise.reject(new Error('Leaderboard unavailable'));
      }
      return Promise.resolve({ data: {} });
    });
    await renderAffiliate();
    await waitFor(() => screen.getByRole('button', { name: /^leaderboard$/i }), { timeout: 3000 });
    fireEvent.click(screen.getByRole('button', { name: /^leaderboard$/i }));
    await waitFor(() => expect(screen.getByText(/leaderboard unavailable/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});
