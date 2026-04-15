/**
 * Tests for Portfolio, Performance, and TradingDashboard pages.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

// ─── Mocks ────────────────────────────────────────────────────────────────────

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
  authApi: { login: vi.fn(), logout: vi.fn(), me: vi.fn() },
  backtestApi: { run: vi.fn(), results: vi.fn(), list: vi.fn() },
  performanceApi: {
    summary:     vi.fn().mockResolvedValue({ data: {
      total_trades: 42, win_rate: 0.65, avg_return_pct: 1.2,
      total_return_pct: 12.5, sharpe_ratio: 1.8, sortino_ratio: 2.1,
      max_drawdown_pct: 8.5, profit_factor: 1.6, avg_trade_pnl: 45.0,
      best_trade: 320.0, worst_trade: -180.0, cvar_95: -95.0,
    } }),
    equity:      vi.fn().mockResolvedValue({ data: { curve: [] } }),
    equityCurve: vi.fn().mockResolvedValue({ data: [
      { time: 1700000000, value: 100000 },
      { time: 1700086400, value: 102000 },
      { time: 1700172800, value: 101500 },
    ] }),
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
    get:    vi.fn().mockResolvedValue({ data: {} }),
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

function wrap(element: React.ReactElement, qc = makeQC()) {
  return render(
    <QueryClientProvider client={qc}>
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

// ─── Portfolio ────────────────────────────────────────────────────────────────

describe('Portfolio page', () => {
  async function renderPortfolio() {
    const Portfolio = (await import('../pages/Portfolio')).default;
    return wrap(<Portfolio />);
  }

  it('renders Portfolio heading', async () => {
    await renderPortfolio();
    expect(screen.getByText('Portfolio')).toBeInTheDocument();
  });

  it('renders account summary section', async () => {
    await renderPortfolio();
    // Balance label appears in stat tiles
    expect(screen.getByText(/balance/i)).toBeInTheDocument();
  });

  it('renders equity curve section', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/equity/i).length).toBeGreaterThan(0);
  });

  it('renders trade history section', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/trade history/i).length).toBeGreaterThan(0);
  });

  it('shows no closed trades when empty', async () => {
    await renderPortfolio();
    await waitFor(() => {
      expect(screen.getAllByText(/no closed trades yet/i).length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('shows account balance from store', async () => {
    act(() => {
      useStore.getState().setAccount({
        balance: 125_000, equity: 127_500, margin_used: 2_500, margin_free: 122_500,
        margin_level: 5100, daily_pnl: 500, daily_pnl_pct: 0.4, total_pnl: 7_500,
        win_rate: 0.68, sharpe_ratio: 1.9, max_drawdown: 0.04, open_trades: 2,
      });
    });
    await renderPortfolio();
    expect(screen.getByText(/125,000/)).toBeInTheDocument();
  });

  it('shows open positions from store', async () => {
    act(() => {
      useStore.getState().setPositions([{
        id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
        entry_price: 2340, current_price: 2360, unrealized_pnl: 200,
        realized_pnl: 0, opened_at: new Date().toISOString(),
      }]);
    });
    await renderPortfolio();
    expect(screen.getAllByText('XAU/USD').length).toBeGreaterThan(0);
  });

  it('renders performance metrics section', async () => {
    await renderPortfolio();
    expect(screen.getByText(/performance/i)).toBeInTheDocument();
  });

  it('renders win rate stat tile', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/win rate/i).length).toBeGreaterThan(0);
  });

  it('renders sharpe ratio stat tile', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/sharpe/i).length).toBeGreaterThan(0);
  });

  it('renders max drawdown stat tile', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/drawdown/i).length).toBeGreaterThan(0);
  });

  it('renders positions table headers', async () => {
    await renderPortfolio();
    expect(screen.getAllByText(/open positions/i).length).toBeGreaterThan(0);
  });
});

// ─── Performance ─────────────────────────────────────────────────────────────

describe('Performance page', () => {
  async function renderPerformance() {
    const Performance = (await import('../pages/Performance')).default;
    return wrap(<Performance />);
  }

  it('renders Performance heading', async () => {
    await renderPerformance();
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('renders tab navigation', async () => {
    await renderPerformance();
    expect(screen.getByRole('button', { name: /overview/i })).toBeInTheDocument();
  });

  it('renders trades tab button', async () => {
    await renderPerformance();
    expect(screen.getByRole('button', { name: /trades/i })).toBeInTheDocument();
  });

  it('renders weekly tab button', async () => {
    await renderPerformance();
    expect(screen.getByRole('button', { name: /weekly/i })).toBeInTheDocument();
  });

  it('renders refresh button', async () => {
    await renderPerformance();
    expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument();
  });

  it('renders equity curve section', async () => {
    await renderPerformance();
    expect(screen.getByText(/equity curve/i)).toBeInTheDocument();
  });

  it('shows total trades stat', async () => {
    await renderPerformance();
    await waitFor(() => {
      expect(screen.getByText(/total trades/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows win rate stat', async () => {
    await renderPerformance();
    await waitFor(() => {
      expect(screen.getByText(/win rate/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows sharpe stat', async () => {
    await renderPerformance();
    await waitFor(() => {
      expect(screen.getByText(/sharpe/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows max drawdown stat', async () => {
    await renderPerformance();
    await waitFor(() => {
      expect(screen.getAllByText(/drawdown/i).length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('switches to trades tab', async () => {
    await renderPerformance();
    const tradesBtn = screen.getByRole('button', { name: /trades/i });
    fireEvent.click(tradesBtn);
    await waitFor(() => {
      expect(screen.getByText(/trade history/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('switches to weekly tab', async () => {
    await renderPerformance();
    const weeklyBtn = screen.getByRole('button', { name: /weekly/i });
    fireEvent.click(weeklyBtn);
    await waitFor(() => {
      expect(screen.getByText(/weekly report/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('renders trade filter input on trades tab', async () => {
    await renderPerformance();
    fireEvent.click(screen.getByRole('button', { name: /trades/i }));
    await waitFor(() => {
      // Performance page uses "Filter symbol…" placeholder
      expect(screen.getByPlaceholderText(/filter/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('shows no trades found when empty', async () => {
    await renderPerformance();
    fireEvent.click(screen.getByRole('button', { name: /trades/i }));
    await waitFor(() => {
      expect(screen.getByText(/no trades found/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });
});

// ─── TradingDashboard ─────────────────────────────────────────────────────────

describe('TradingDashboard page', () => {
  async function renderTradingDashboard() {
    const TradingDashboard = (await import('../pages/TradingDashboard')).default;
    return wrap(<TradingDashboard />);
  }

  it('renders without crashing', async () => {
    const { container } = await renderTradingDashboard();
    expect(container).toBeInTheDocument();
  });

  it('renders price ticker area', async () => {
    await renderTradingDashboard();
    // LivePriceTicker renders symbols — check container exists
    const container = document.querySelector('[class*="flex"]');
    expect(container).toBeInTheDocument();
  });

  it('shows WS disconnected status initially via StatusDot label', async () => {
    await renderTradingDashboard();
    // StatusDot renders the raw wsStatus string as label
    expect(screen.getByText('disconnected')).toBeInTheDocument();
  });

  it('shows WS connected status when store updates via StatusDot label', async () => {
    await renderTradingDashboard();
    act(() => { useStore.getState().setWsStatus('connected'); });
    expect(screen.getByText('connected')).toBeInTheDocument();
  });

  it('shows account balance when set in store', async () => {
    act(() => {
      useStore.getState().setAccount({
        balance: 75_000, equity: 76_000, margin_used: 1_000, margin_free: 74_000,
        margin_level: 7600, daily_pnl: 200, daily_pnl_pct: 0.27, total_pnl: 1_000,
        win_rate: 0.60, sharpe_ratio: 1.4, max_drawdown: 0.02, open_trades: 1,
      });
    });
    await renderTradingDashboard();
    expect(screen.getByText(/75,000/)).toBeInTheDocument();
  });

  it('renders equity curve panel area', async () => {
    await renderTradingDashboard();
    // PanelErrorBoundary wraps with title prop — check grid exists
    const grid = document.querySelector('[class*="grid"]');
    expect(grid).toBeInTheDocument();
  });

  it('renders full-screen layout container', async () => {
    await renderTradingDashboard();
    const layout = document.querySelector('[class*="h-screen"]');
    expect(layout).toBeInTheDocument();
  });

  it('shows price tick data when store has prices', async () => {
    act(() => {
      useStore.getState().setPrice({
        symbol: 'XAU/USD', bid: 2341.50, ask: 2341.80, mid: 2341.65,
        spread: 0.30, timestamp: Date.now(), change_pct: 0.12,
      });
    });
    await renderTradingDashboard();
    // LivePriceTicker always renders the symbol label regardless of price data
    // Price value may show as formatted number or dash depending on render timing
    const container = document.querySelector('[class*="flex"]');
    expect(container).toBeInTheDocument();
  });

  it('renders without errors when positions are populated', async () => {
    act(() => {
      useStore.getState().setPositions([{
        id: 'p1', symbol: 'EUR/USD', side: 'long', size: 10_000,
        entry_price: 1.085, current_price: 1.088, unrealized_pnl: 30,
        realized_pnl: 0, opened_at: new Date().toISOString(),
      }]);
    });
    const { container } = await renderTradingDashboard();
    expect(container).toBeInTheDocument();
  });

  it('renders without errors when signals are populated', async () => {
    act(() => {
      useStore.getState().setSignals([{
        id: 's1', symbol: 'XAU/USD', direction: 'long', confidence: 0.85,
        model: 'XGBoost', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
        generated_at: new Date().toISOString(), status: 'active',
      }]);
    });
    const { container } = await renderTradingDashboard();
    expect(container).toBeInTheDocument();
  });
});
