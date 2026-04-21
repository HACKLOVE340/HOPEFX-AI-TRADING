/**
 * Page-level render tests — smoke tests for all 7 pages.
 * ~80 tests
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
  tradingApi: {
    positions:         vi.fn().mockResolvedValue({ data: [] }),
    signals:           vi.fn().mockResolvedValue({ data: [] }),
    account:           vi.fn().mockResolvedValue({ data: null }),
    ohlcv:             vi.fn().mockResolvedValue({ data: [] }),
    placeOrder:        vi.fn().mockResolvedValue({ data: {} }),
    closePosition:     vi.fn().mockResolvedValue({ data: {} }),
    closeAllPositions: vi.fn().mockResolvedValue({ data: {} }),
    trades:            vi.fn().mockResolvedValue({ data: [] }),
    regime:            vi.fn().mockResolvedValue({ data: { regime: 'BULLISH', confidence: 0.82, volatility: 'LOW', trend: 'UP' } }),
    brainState:        vi.fn().mockResolvedValue({ data: { status: 'active', mode: 'live', active_strategies: ['momentum'] } }),
    emergencyStop:     vi.fn().mockResolvedValue({ data: {} }),
    aiAnalysis:        vi.fn().mockResolvedValue({ data: { direction: 'long', confidence: 0.78, reasoning: 'Bullish momentum' } }),
    riskMetrics:       vi.fn().mockResolvedValue({ data: {} }),
  },
  mlApi: {
    accuracy: vi.fn().mockResolvedValue({ data: {} }),
    predict:  vi.fn(),
    models:   vi.fn().mockResolvedValue({ data: [] }),
    features: vi.fn().mockResolvedValue({ data: { features: [] } }),
  },
  mlExtendedApi: {
    health: vi.fn().mockResolvedValue({ data: { status: 'ok', model_loaded: true, model_id: 'test', feature_count: 10, predict_count: 0 } }),
  },
  dataLayerApi: {
    health:         vi.fn().mockResolvedValue({ data: {} }),
    microstructure: vi.fn().mockResolvedValue({ data: { snapshot: null, features: {} } }),
    sentiment:      vi.fn().mockResolvedValue({ data: { signal: { news_sentiment_score: 0, news_sentiment_momentum: 0, news_article_count_1h: 0, news_bullish_ratio: 0.5 }, recent_articles: [] } }),
    macro:          vi.fn().mockResolvedValue({ data: { calendar_features: {}, macro_features: {}, is_blackout: false, impact_score: 0, upcoming_events: [] } }),
    quality:        vi.fn().mockResolvedValue({ data: {} }),
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
    active:  vi.fn().mockResolvedValue({ data: [] }),
    summary: vi.fn().mockResolvedValue({ data: {} }),
    history: vi.fn().mockResolvedValue({ data: [] }),
  },
  authApi: {
    login:  vi.fn(),
    logout: vi.fn(),
    me:     vi.fn(),
  },
  backtestApi: { run: vi.fn(), results: vi.fn(), list: vi.fn() },
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

function wrap(element: React.ReactElement, path = '/') {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={element} />
        </Routes>
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

// ─── Dashboard ────────────────────────────────────────────────────────────────

describe('Dashboard page', () => {
  async function renderDashboard() {
    const Dashboard = (await import('../pages/Dashboard')).default;
    return wrap(<Dashboard />);
  }

  it('renders without crashing', async () => {
    await renderDashboard();
    expect(document.body).toBeTruthy();
  });

  it('renders Dashboard heading', async () => {
    await renderDashboard();
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('renders real-time trading overview text', async () => {
    await renderDashboard();
    expect(screen.getByText(/real-time trading overview/i)).toBeInTheDocument();
  });

  it('renders Balance stat card', async () => {
    await renderDashboard();
    expect(screen.getByText('Balance')).toBeInTheDocument();
  });

  it('renders Equity stat card', async () => {
    await renderDashboard();
    expect(screen.getByText('Equity')).toBeInTheDocument();
  });

  it('renders Win Rate stat card', async () => {
    await renderDashboard();
    expect(screen.getByText('Win Rate')).toBeInTheDocument();
  });

  it('renders Sharpe stat card', async () => {
    await renderDashboard();
    expect(screen.getByText('Sharpe')).toBeInTheDocument();
  });

  it('renders Open Positions section', async () => {
    await renderDashboard();
    expect(screen.getByText('Open Positions')).toBeInTheDocument();
  });

  it('renders Active Signals section', async () => {
    await renderDashboard();
    expect(screen.getByText('Active Signals')).toBeInTheDocument();
  });

  it('renders ML Model Accuracy section', async () => {
    await renderDashboard();
    expect(screen.getByText('ML Model Accuracy')).toBeInTheDocument();
  });

  it('renders Equity Curve section', async () => {
    await renderDashboard();
    expect(screen.getByText(/equity curve/i)).toBeInTheDocument();
  });

  it('renders XAU/USD in ticker', async () => {
    await renderDashboard();
    // Symbol appears in both ticker and signal panel — use getAllByText
    expect(screen.getAllByText('XAU/USD').length).toBeGreaterThan(0);
  });

  it('renders EUR/USD in ticker', async () => {
    await renderDashboard();
    expect(screen.getAllByText('EUR/USD').length).toBeGreaterThan(0);
  });

  it('renders BTC/USD in ticker', async () => {
    await renderDashboard();
    expect(screen.getAllByText('BTC/USD').length).toBeGreaterThan(0);
  });

  it('renders Daily P&L stat', async () => {
    await renderDashboard();
    expect(screen.getByText('Daily P&L')).toBeInTheDocument();
  });

  it('renders Max Drawdown stat', async () => {
    await renderDashboard();
    expect(screen.getByText('Max Drawdown')).toBeInTheDocument();
  });

  it('renders Open Trades stat', async () => {
    await renderDashboard();
    expect(screen.getByText('Open Trades')).toBeInTheDocument();
  });

  it('shows no open positions message when empty', async () => {
    await renderDashboard();
    expect(screen.getByText(/no open positions/i)).toBeInTheDocument();
  });
});

// ─── Login page ───────────────────────────────────────────────────────────────

describe('Login page', () => {
  async function renderLogin() {
    const Login = (await import('../pages/Login')).default;
    return wrap(<Login />);
  }

  it('renders without crashing', async () => {
    await renderLogin();
    expect(document.body).toBeTruthy();
  });

  it('renders HOPEFX branding', async () => {
    await renderLogin();
    expect(screen.getByText(/HOPE/)).toBeInTheDocument();
  });

  it('renders sign in button', async () => {
    await renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders email field', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/email or username/i)).toBeInTheDocument();
  });

  it('renders password field', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it('renders AI-Powered tagline', async () => {
    await renderLogin();
    expect(screen.getByText(/ai-powered/i)).toBeInTheDocument();
  });
});

// ─── StatusPage ───────────────────────────────────────────────────────────────

describe('StatusPage', () => {
  async function renderStatus() {
    const StatusPage = (await import('../pages/StatusPage')).default;
    return wrap(<StatusPage />);
  }

  it('renders without crashing', async () => {
    await renderStatus();
    expect(document.body).toBeTruthy();
  });

  it('renders some status content', async () => {
    await renderStatus();
    expect(document.body.textContent?.length).toBeGreaterThan(0);
  });
});

// ─── Settings page ────────────────────────────────────────────────────────────

describe('Settings page', () => {
  async function renderSettings() {
    const Settings = (await import('../pages/Settings')).default;
    return wrap(<Settings />);
  }

  it('renders without crashing', async () => {
    await renderSettings();
    expect(document.body).toBeTruthy();
  });

  it('renders some settings content', async () => {
    await renderSettings();
    expect(document.body.textContent?.length).toBeGreaterThan(0);
  });
});

// ─── Marketplace page ─────────────────────────────────────────────────────────

describe('Marketplace page', () => {
  async function renderMarketplace() {
    const Marketplace = (await import('../pages/Marketplace')).default;
    return wrap(<Marketplace />);
  }

  it('renders without crashing', async () => {
    await renderMarketplace();
    expect(document.body).toBeTruthy();
  });

  it('renders some marketplace content', async () => {
    await renderMarketplace();
    expect(document.body.textContent?.length).toBeGreaterThan(0);
  });
});

// ─── Affiliate page ───────────────────────────────────────────────────────────

describe('Affiliate page', () => {
  async function renderAffiliate() {
    const Affiliate = (await import('../pages/Affiliate')).default;
    return wrap(<Affiliate />);
  }

  it('renders without crashing', async () => {
    await renderAffiliate();
    expect(document.body).toBeTruthy();
  });
});

// ─── CryptoCheckout page ──────────────────────────────────────────────────────

describe('CryptoCheckout page', () => {
  async function renderCheckout() {
    const CryptoCheckout = (await import('../pages/CryptoCheckout')).default;
    return wrap(<CryptoCheckout />);
  }

  it('renders without crashing', async () => {
    await renderCheckout();
    expect(document.body).toBeTruthy();
  });
});

// ─── App routing ──────────────────────────────────────────────────────────────

describe('App routing', () => {
  async function renderApp(path: string) {
    const App = (await import('../App')).default;
    return render(<App />);
  }

  it('renders App without crashing', async () => {
    await renderApp('/');
    expect(document.body).toBeTruthy();
  });

  it('renders landing page at /', async () => {
    const App = (await import('../App')).default;
    render(<App />);
    // Landing page should have some content
    expect(document.body.textContent?.length).toBeGreaterThan(0);
  });
});

// ─── Dashboard with positions ─────────────────────────────────────────────────

describe('Dashboard with data', () => {
  async function renderDashboardWithData() {
    useStore.getState().setPositions([{
      id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
      entry_price: 2340, current_price: 2360, unrealized_pnl: 200,
      realized_pnl: 0, opened_at: new Date().toISOString(),
    }]);
    useStore.getState().setSignals([{
      id: 's1', symbol: 'XAU/USD', direction: 'long', confidence: 0.87,
      model: 'Stacking Ensemble', entry_price: 2341, stop_loss: 2320,
      take_profit: 2380, generated_at: new Date().toISOString(), status: 'active',
    }]);
    useStore.getState().setAccount({
      balance: 100_000, equity: 102_000, margin_used: 4_000, margin_free: 98_000,
      margin_level: 2550, daily_pnl: 500, daily_pnl_pct: 0.5, total_pnl: 2_000,
      win_rate: 0.65, sharpe_ratio: 1.8, max_drawdown: 0.04, open_trades: 1,
    });
    const Dashboard = (await import('../pages/Dashboard')).default;
    return wrap(<Dashboard />);
  }

  it('renders position symbol', async () => {
    await renderDashboardWithData();
    const cells = screen.getAllByText('XAU/USD');
    expect(cells.length).toBeGreaterThan(0);
  });

  it('renders signal confidence', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('87.0%')).toBeInTheDocument();
  });

  it('renders signal model name', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('Stacking Ensemble')).toBeInTheDocument();
  });

  it('renders account balance', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('$100,000.00')).toBeInTheDocument();
  });

  it('renders win rate', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('65.0%')).toBeInTheDocument();
  });

  it('renders sharpe ratio', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('1.80')).toBeInTheDocument();
  });

  it('renders LONG badge for long signal', async () => {
    await renderDashboardWithData();
    expect(screen.getByText('LONG')).toBeInTheDocument();
  });

  it('renders position side', async () => {
    await renderDashboardWithData();
    // Position table has 'long' in lowercase
    const longs = screen.getAllByText(/long/i);
    expect(longs.length).toBeGreaterThan(0);
  });
});

// ─── Trading page ─────────────────────────────────────────────────────────────

// lightweight-charts creates a canvas — stub it for jsdom
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      update:  vi.fn(),
      applyOptions: vi.fn(),
    })),
    priceScale:  vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale:   vi.fn(() => ({ fitContent: vi.fn(), applyOptions: vi.fn() })),
    applyOptions: vi.fn(),
    remove:       vi.fn(),
  })),
  CandlestickSeries: 'CandlestickSeries',
  LineSeries:        'LineSeries',
  HistogramSeries:   'HistogramSeries',
}));



describe('Trading page', () => {
  const tradingQc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  async function renderTrading() {
    const Trading = (await import('../pages/Trading')).default;
    return render(
      <QueryClientProvider client={tradingQc}>
        <MemoryRouter initialEntries={['/trading/legacy']}>
          <Routes>
            <Route path="*" element={<Trading />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  beforeEach(() => {
    useStore.setState({
      token: 'tok',
      user: { id: '1', email: 'a@b.com', username: 'trader1', role: 'trader' as const },
      isAuthenticated: true,
      prices: {}, priceHistory: {},
      positions: [], signals: [],
      account: null,
      wsStatus: 'disconnected', lastHeartbeat: null,
    });
  });

  it('renders without crashing', async () => {
    await renderTrading();
    expect(document.body).toBeTruthy();
  });

  it('renders HOPEFX TERMINAL branding', async () => {
    await renderTrading();
    expect(screen.getByText('HOPEFX')).toBeInTheDocument();
    expect(screen.getByText('TERMINAL')).toBeInTheDocument();
  });

  it('renders symbol selector with XAU/USD default', async () => {
    await renderTrading();
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('XAU/USD');
  });

  it('renders all timeframe buttons', async () => {
    await renderTrading();
    for (const tf of ['1m', '5m', '15m', '1h', '4h', '1d']) {
      expect(screen.getByRole('button', { name: tf })).toBeInTheDocument();
    }
  });

  it('1h timeframe button is active by default', async () => {
    await renderTrading();
    const btn = screen.getByRole('button', { name: '1h' });
    expect(btn.className).toMatch(/text-\[#60a5fa\]/);
  });

  it('renders positions tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^positions$/i })).toBeInTheDocument();
  });

  it('renders history tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^history$/i })).toBeInTheDocument();
  });

  it('renders signals tab button in bottom tabs', async () => {
    await renderTrading();
    const sigBtns = screen.getAllByRole('button', { name: /signals/i });
    expect(sigBtns.length).toBeGreaterThan(0);
  });

  it('renders right-panel Risk tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^risk$/i })).toBeInTheDocument();
  });

  it('renders right-panel ML tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^ml$/i })).toBeInTheDocument();
  });

  it('renders right-panel Micro tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^micro$/i })).toBeInTheDocument();
  });

  it('renders right-panel Sentiment tab button', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /^sentiment$/i })).toBeInTheDocument();
  });

  it('renders Order Entry panel', async () => {
    await renderTrading();
    expect(screen.getByText(/order entry/i)).toBeInTheDocument();
  });

  it('renders Controls panel with emergency stop', async () => {
    await renderTrading();
    expect(screen.getByText(/emergency stop/i)).toBeInTheDocument();
  });

  it('renders AI Analysis panel', async () => {
    await renderTrading();
    // Panel title + button both contain "AI Analysis" — just check at least one exists
    expect(screen.getAllByText(/ai analysis/i).length).toBeGreaterThan(0);
  });

  it('renders Market Regime panel', async () => {
    await renderTrading();
    expect(screen.getByText(/market regime/i)).toBeInTheDocument();
  });

  it('renders WS status badge', async () => {
    await renderTrading();
    // "○ REST" or "● LIVE" — may appear more than once
    expect(screen.getAllByText(/live|rest/i).length).toBeGreaterThan(0);
  });

  it('shows live price labels when tick is in store', async () => {
    useStore.getState().setPrice({
      symbol: 'XAU/USD', bid: 2341.50, ask: 2341.80, mid: 2341.65,
      spread: 0.30, timestamp: Date.now(), change_pct: 0.12,
    });
    await renderTrading();
    // Bid/Ask appear in both TopBar and OrderEntryForm
    expect(screen.getAllByText('Bid').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ask').length).toBeGreaterThan(0);
  });

  it('shows account balance when account is in store', async () => {
    useStore.getState().setAccount({
      balance: 50000, equity: 51000, margin_used: 2000, margin_free: 49000,
      margin_level: 2550, daily_pnl: 250, daily_pnl_pct: 0.5, total_pnl: 1000,
      win_rate: 0.62, sharpe_ratio: 1.5, max_drawdown: 0.03, open_trades: 1,
    });
    await renderTrading();
    expect(screen.getByText(/50,000/)).toBeInTheDocument();
  });

  it('shows no open positions when positions list is empty', async () => {
    await renderTrading();
    expect(screen.getByText(/no open positions/i)).toBeInTheDocument();
  });

  it('shows position row when positions are in store', async () => {
    useStore.getState().setPositions([{
      id: 'p1', symbol: 'XAU/USD', side: 'long', size: 0.5,
      entry_price: 2340, current_price: 2355, unrealized_pnl: 75,
      realized_pnl: 0, opened_at: new Date().toISOString(),
    }]);
    await renderTrading();
    const cells = screen.getAllByText('XAU/USD');
    expect(cells.length).toBeGreaterThan(0);
  });

  it('Vol and MA20 checkboxes are present', async () => {
    await renderTrading();
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBeGreaterThanOrEqual(2);
  });

  it('Run AI Analysis button is present', async () => {
    await renderTrading();
    expect(screen.getByRole('button', { name: /run ai analysis/i })).toBeInTheDocument();
  });

  it('switching to history tab shows trade history panel', async () => {
    await renderTrading();
    const histBtn = screen.getByRole('button', { name: /^history$/i });
    fireEvent.click(histBtn);
    await waitFor(() => {
      expect(screen.getByText(/no closed trades yet/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('switching to signals tab shows signals panel', async () => {
    await renderTrading();
    const sigBtns = screen.getAllByRole('button', { name: /^signals$/i });
    fireEvent.click(sigBtns[0]);
    expect(screen.getByText(/no signals for/i)).toBeInTheDocument();
  });

  it('switching timeframe updates active button style', async () => {
    await renderTrading();
    const btn4h = screen.getByRole('button', { name: '4h' });
    fireEvent.click(btn4h);
    expect(btn4h.className).toMatch(/text-\[#60a5fa\]/);
  });

  it('switching symbol updates selector value', async () => {
    await renderTrading();
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'EUR/USD' } });
    expect(select.value).toBe('EUR/USD');
  });
});
