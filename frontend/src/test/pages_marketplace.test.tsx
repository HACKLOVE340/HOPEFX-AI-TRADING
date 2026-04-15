/**
 * Marketplace page — unit tests
 *
 * Covers:
 * - Renders heading and filter bar
 * - Loads and displays strategy cards from API
 * - Category filter pills
 * - Sort dropdown
 * - Search input (client-side filter)
 * - Empty state when no strategies match
 * - Error state when API fails
 * - Loading state
 * - Strategy detail modal (open, close, subscribe)
 * - Subscribe success and error
 * - Reviews rendered in modal
 * - Stats line (total strategies / subscribers)
 * - Free vs paid price display
 * - Performance badges
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

// ── Fixtures ──────────────────────────────────────────────────────────────────

const STRATEGY_FREE: Record<string, unknown> = {
  strategy_id: 's1',
  name: 'Gold Momentum',
  description: 'Trend-following strategy for XAUUSD using LSTM signals.',
  creator_id: 'u1',
  category: 'trend_following',
  price: 0,
  license_type: 'subscription',
  rating: 4.5,
  review_count: 32,
  subscriber_count: 210,
  status: 'active',
  tags: ['gold', 'lstm'],
  performance: {
    total_return_pct: 18.4,
    sharpe_ratio: 1.72,
    max_drawdown_pct: 6.1,
    win_rate_pct: 62,
  },
};

const STRATEGY_PAID = {
  strategy_id: 's2',
  name: 'Smart Money Scalper',
  description: 'Institutional order flow detection for intraday scalping.',
  creator_id: 'u2',
  category: 'smart_money',
  price: 49,
  license_type: 'subscription',
  rating: 4.8,
  review_count: 87,
  subscriber_count: 540,
  status: 'active',
  tags: ['scalping', 'order-flow'],
  performance: {
    total_return_pct: 31.2,
    sharpe_ratio: 2.1,
    max_drawdown_pct: 4.8,
    win_rate_pct: 71,
  },
};

const REVIEWS = [
  {
    review_id: 'r1',
    user_id: 'u3',
    rating: 5,
    title: 'Excellent strategy',
    content: 'Consistent returns over 3 months.',
    created_at: '2025-01-15T10:00:00Z',
  },
  {
    review_id: 'r2',
    user_id: 'u4',
    rating: 4,
    title: 'Good but needs tuning',
    content: 'Works well in trending markets.',
    created_at: '2025-02-01T08:30:00Z',
  },
];

// ── Mocks ─────────────────────────────────────────────────────────────────────

// vi.hoisted ensures these are available before vi.mock factory runs
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
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const mockUser = { id: 'u1', email: 'a@b.com', username: 'trader1', role: 'trader' as const };

async function renderMarketplace() {
  const Marketplace = (await import('../pages/Marketplace')).default;
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/marketplace']}>
        <Routes>
          <Route path="*" element={<Marketplace />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function setupDefaultMocks() {
  mockApiGet.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies/s1')) {
      return Promise.resolve({ data: { strategy: STRATEGY_FREE, reviews: REVIEWS } });
    }
    if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies/s2')) {
      return Promise.resolve({ data: { strategy: STRATEGY_PAID, reviews: [] } });
    }
    if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies')) {
      return Promise.resolve({ data: { strategies: [STRATEGY_FREE, STRATEGY_PAID], total: 2 } });
    }
    if (typeof url === 'string' && url.includes('/monetization/marketplace/stats')) {
      return Promise.resolve({ data: { total_strategies: 42, total_subscribers: 3800 } });
    }
    return Promise.resolve({ data: {} });
  });
  mockApiPost.mockResolvedValue({ data: { purchase_id: 'p1', status: 'active' } });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

// Apply default mocks once at module level so they're active before any test
setupDefaultMocks();

describe('Marketplace — render and layout', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders without crashing', async () => {
    await renderMarketplace();
    expect(document.body).toBeTruthy();
  });

  it('renders Strategy Marketplace heading', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('Strategy Marketplace')).toBeInTheDocument());
  });

  it('renders search input', async () => {
    await renderMarketplace();
    expect(screen.getByPlaceholderText(/search strategies/i)).toBeInTheDocument();
  });

  it('renders sort dropdown', async () => {
    await renderMarketplace();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('renders all category pills', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('All')).toBeInTheDocument());
    // Use getAllByText since category names also appear in strategy cards
    expect(screen.getAllByText('trend following').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('mean reversion').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('smart money').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('macro').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('breakout').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('swing').length).toBeGreaterThanOrEqual(1);
  });

  it('shows stats line with strategy count', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText(/42 strategies/)).toBeInTheDocument());
  });

  it('shows stats line with subscriber count', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText(/3,800 subscribers/)).toBeInTheDocument());
  });
});

describe('Marketplace — strategy cards', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('renders strategy names from API', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('Gold Momentum')).toBeInTheDocument());
    expect(screen.getByText('Smart Money Scalper')).toBeInTheDocument();
  });

  it('renders Free label for zero-price strategy', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('Free')).toBeInTheDocument());
  });

  it('renders price for paid strategy', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('$49')).toBeInTheDocument());
  });

  it('renders performance return badge', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('+18.4%')).toBeInTheDocument());
  });

  it('renders Sharpe ratio badge', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('1.7')).toBeInTheDocument());
  });

  it('renders win rate badge', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('62%')).toBeInTheDocument());
  });

  it('renders subscriber count', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('210 subscribers')).toBeInTheDocument());
  });

  it('renders review count', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText(/32\)/)).toBeInTheDocument());
  });

  it('renders category tag on card', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('trend following')).toBeInTheDocument());
  });

  it('renders tags on card', async () => {
    await renderMarketplace();
    await waitFor(() => expect(screen.getByText('gold')).toBeInTheDocument());
  });
});

describe('Marketplace — loading and error states', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('shows loading state initially', async () => {
    let resolve: (v: unknown) => void;
    mockApiGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderMarketplace();
    expect(screen.getByText(/loading strategies/i)).toBeInTheDocument();
    resolve!({ data: { strategies: [], total: 0 } });
  });

  it('shows error message when API fails', async () => {
    // extractErrorMessage returns err.message for plain Error objects
    mockApiGet.mockRejectedValue(new Error('Service unavailable'));
    const Marketplace = (await import('../pages/Marketplace')).default;
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><Routes><Route path="*" element={<Marketplace />} /></Routes></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(screen.getByText(/service unavailable/i)).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows empty state when no strategies match', async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies') && !url.includes('/stats')) {
        return Promise.resolve({ data: { strategies: [], total: 0 } });
      }
      return Promise.resolve({ data: {} });
    });
    const Marketplace = (await import('../pages/Marketplace')).default;
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><Routes><Route path="*" element={<Marketplace />} /></Routes></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(screen.getByText(/no strategies match/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Marketplace — search and filter', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('filters strategies by search term (client-side)', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    const searchInput = screen.getByPlaceholderText(/search strategies/i);
    fireEvent.change(searchInput, { target: { value: 'scalper' } });
    await waitFor(() => {
      expect(screen.queryByText('Gold Momentum')).not.toBeInTheDocument();
      expect(screen.getByText('Smart Money Scalper')).toBeInTheDocument();
    });
  });

  it('shows empty state when search matches nothing', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.change(screen.getByPlaceholderText(/search strategies/i), { target: { value: 'zzznomatch' } });
    await waitFor(() => expect(screen.getByText(/no strategies match/i)).toBeInTheDocument());
  });

  it('category pill click triggers API reload', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    // Click the category pill button (not the card tag — use role=button)
    const pillBtns = screen.getAllByRole('button');
    const smartMoneyPill = pillBtns.find(b => b.textContent === 'smart money');
    if (smartMoneyPill) fireEvent.click(smartMoneyPill);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith(
      expect.stringContaining('/monetization/marketplace/strategies'),
      expect.objectContaining({ params: expect.objectContaining({ category: 'smart_money' }) })
    ), { timeout: 3000 });
  });

  it('sort dropdown change triggers API reload', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'rating' } });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith(
      expect.stringContaining('/monetization/marketplace/strategies'),
      expect.objectContaining({ params: expect.objectContaining({ sort_by: 'rating' }) })
    ));
  });

  it('All category pill shows all strategies', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    // Click smart money pill then All pill
    const pillBtns = screen.getAllByRole('button');
    const smartMoneyPill = pillBtns.find(b => b.textContent === 'smart money');
    if (smartMoneyPill) fireEvent.click(smartMoneyPill);
    const allPill = screen.getByText('All');
    fireEvent.click(allPill);
    await waitFor(() => {
      expect(screen.getByText('Gold Momentum')).toBeInTheDocument();
      expect(screen.getByText('Smart Money Scalper')).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});

describe('Marketplace — detail modal', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('opens modal on card click', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => expect(screen.getByText(/add to my strategies/i)).toBeInTheDocument());
  });

  it('modal shows strategy description', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    // Description appears in both card (truncated) and modal — at least one match
    await waitFor(() => expect(screen.getAllByText(/trend-following strategy for XAUUSD/i).length).toBeGreaterThan(0));
  });

  it('modal shows reviews', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => expect(screen.getByText('Excellent strategy')).toBeInTheDocument());
    expect(screen.getByText('Good but needs tuning')).toBeInTheDocument();
  });

  it('modal shows review content', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => expect(screen.getByText('Consistent returns over 3 months.')).toBeInTheDocument());
  });

  it('modal close button dismisses modal', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    fireEvent.click(screen.getByText('✕'));
    await waitFor(() => expect(screen.queryByText(/add to my strategies/i)).not.toBeInTheDocument());
  });

  it('clicking overlay closes modal', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    // Click the overlay (fixed backdrop)
    const overlay = document.querySelector('[style*="position: fixed"]') as HTMLElement;
    if (overlay) fireEvent.click(overlay);
    await waitFor(() => expect(screen.queryByText(/add to my strategies/i)).not.toBeInTheDocument());
  });

  it('paid strategy modal shows Subscribe button with price', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Smart Money Scalper'));
    fireEvent.click(screen.getByText('Smart Money Scalper'));
    await waitFor(() => expect(screen.getByText(/subscribe — \$49/i)).toBeInTheDocument());
  });

  it('subscribe button calls purchase API', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    fireEvent.click(screen.getByText(/add to my strategies/i));
    await waitFor(() => expect(mockApiPost).toHaveBeenCalledWith(
      '/monetization/marketplace/purchase',
      expect.objectContaining({ strategy_id: 's1' })
    ));
  });

  it('subscribe button shows Subscribed after success', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    fireEvent.click(screen.getByText(/add to my strategies/i));
    await waitFor(() => expect(screen.getByText(/subscribed/i)).toBeInTheDocument());
  });

  it('subscribe button is disabled after subscribing', async () => {
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    fireEvent.click(screen.getByText(/add to my strategies/i));
    await waitFor(() => {
      const btn = screen.getByText(/subscribed/i).closest('button');
      expect(btn).toBeDisabled();
    });
  });

  it('shows purchase error when subscribe API fails', async () => {
    mockApiPost.mockRejectedValueOnce(new Error('Payment declined'));
    await renderMarketplace();
    await waitFor(() => screen.getByText('Gold Momentum'));
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => screen.getByText(/add to my strategies/i));
    fireEvent.click(screen.getByText(/add to my strategies/i));
    await waitFor(() => expect(screen.getByText(/payment declined/i)).toBeInTheDocument());
  });

  it('shows reviews error when reviews API fails', async () => {
    // extractErrorMessage returns err.message for plain Error objects
    mockApiGet.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies/s1')) {
        return Promise.reject(new Error('Reviews fetch failed'));
      }
      if (typeof url === 'string' && url.includes('/monetization/marketplace/strategies') && !url.includes('/stats')) {
        return Promise.resolve({ data: { strategies: [STRATEGY_FREE], total: 1 } });
      }
      if (typeof url === 'string' && url.includes('/monetization/marketplace/stats')) {
        return Promise.resolve({ data: { total_strategies: 1, total_subscribers: 100 } });
      }
      return Promise.resolve({ data: {} });
    });
    const Marketplace = (await import('../pages/Marketplace')).default;
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><Routes><Route path="*" element={<Marketplace />} /></Routes></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => screen.getByText('Gold Momentum'), { timeout: 3000 });
    fireEvent.click(screen.getByText('Gold Momentum'));
    await waitFor(() => expect(screen.getByText(/reviews fetch failed/i)).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('Marketplace — sort options', () => {
  beforeEach(() => {
    setupDefaultMocks();
    useStore.setState({ token: 'tok', user: mockUser, isAuthenticated: true, prices: {}, priceHistory: {}, positions: [], signals: [], account: null, wsStatus: 'disconnected', lastHeartbeat: null });
  });

  it('sort dropdown has Most popular option', async () => {
    await renderMarketplace();
    expect(screen.getByRole('option', { name: /most popular/i })).toBeInTheDocument();
  });

  it('sort dropdown has Highest rated option', async () => {
    await renderMarketplace();
    expect(screen.getByRole('option', { name: /highest rated/i })).toBeInTheDocument();
  });

  it('sort dropdown has Newest option', async () => {
    await renderMarketplace();
    expect(screen.getByRole('option', { name: /newest/i })).toBeInTheDocument();
  });

  it('sort dropdown has Price low to high option', async () => {
    await renderMarketplace();
    expect(screen.getByRole('option', { name: /price: low/i })).toBeInTheDocument();
  });

  it('sort dropdown has Price high to low option', async () => {
    await renderMarketplace();
    expect(screen.getByRole('option', { name: /price: high/i })).toBeInTheDocument();
  });
});
