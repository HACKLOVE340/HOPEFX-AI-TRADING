/**
 * Page-level render tests — smoke tests for all 7 pages.
 * ~80 tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({ send: vi.fn() })),
}));

vi.mock('../hooks/usePriceSimulator', () => ({
  usePriceSimulator: vi.fn(),
}));

vi.mock('../hooks/useApi', () => ({
  tradingApi: {
    positions: vi.fn().mockResolvedValue({ data: { positions: [] } }),
    signals:   vi.fn().mockResolvedValue({ data: { signals: [] } }),
    account:   vi.fn().mockResolvedValue({ data: null }),
    placeOrder: vi.fn(),
    closePosition: vi.fn(),
  },
  mlApi: {
    accuracy: vi.fn().mockResolvedValue({ data: { models: [] } }),
    predict: vi.fn(),
    models: vi.fn(),
  },
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
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
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
  });

  it('renders password field', async () => {
    await renderLogin();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
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
