/**
 * useApi — typed axios instance with JWT injection and 401 auto-logout.
 */

import axios, { type AxiosInstance } from 'axios';
import { useStore } from '../store/useStore';
import type { Order, Position, Signal, AccountMetrics, SymbolInfo, OrderBookDepth } from '../store/useStore';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const BASE_URL = ((import.meta as any).env?.VITE_API_URL as string | undefined) ?? '/api';

// Singleton axios instance
export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

// Inject JWT on every request
api.interceptors.request.use((config) => {
  const token = useStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) {
      useStore.getState().clearAuth();
    }
    return Promise.reject(err);
  },
);

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginPayload  { email: string; password: string }
export interface LoginResponse { access_token: string; token_type: string; user: import('../store/useStore').User }

export const authApi = {
  login:    (payload: LoginPayload)  => api.post<LoginResponse>('/auth/login', payload),
  logout:   ()                       => api.post('/auth/logout'),
  me:       ()                       => api.get<import('../store/useStore').User>('/auth/me'),
  refresh:  ()                       => api.post<LoginResponse>('/auth/refresh'),
};

// ─── Trading ──────────────────────────────────────────────────────────────────

export interface PlaceOrderPayload {
  symbol: string;
  side: 'buy' | 'sell';
  order_type: 'market' | 'limit' | 'stop' | 'stop_limit' | 'trailing_stop';
  quantity: number;
  price?: number | null;
  stop_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  trailing_distance?: number | null;
  comment?: string;
}

export interface OrderFillResponse {
  order_id: string;
  symbol: string;
  side: string;
  quantity: number;
  fill_price: number;
  commission: number;
  status: string;
  timestamp: string;
}

export interface ModifyPositionPayload {
  stop_loss?: number | null;
  take_profit?: number | null;
  trailing_stop?: number | null;
}

export interface PartialClosePayload {
  quantity: number;
}

export interface OHLCVBar {
  timestamp: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export const tradingApi = {
  // Positions
  positions:       ()                                    => api.get<Position[]>('/trading/positions'),
  closePosition:   (id: string)                          => api.delete(`/trading/positions/${id}`),
  closeAllPositions: ()                                  => api.delete('/trading/positions'),
  modifyPosition:  (id: string, payload: ModifyPositionPayload) =>
    api.patch<Position>(`/trading/positions/${id}`, payload),
  partialClose:    (id: string, payload: PartialClosePayload) =>
    api.post<Position>(`/trading/positions/${id}/partial-close`, payload),
  hedgePosition:   (id: string)                          =>
    api.post<Order>(`/trading/positions/${id}/hedge`),

  // Orders
  placeOrder:      (order: PlaceOrderPayload)            => api.post<OrderFillResponse>('/trading/order', order),
  orders:          ()                                    => api.get<Order[]>('/trading/orders'),
  cancelOrder:     (id: string)                          => api.delete(`/trading/orders/${id}`),
  modifyOrder:     (id: string, payload: Partial<PlaceOrderPayload>) =>
    api.patch<Order>(`/trading/orders/${id}`, payload),

  // Market data
  account:         ()                                    => api.get<AccountMetrics>('/trading/account'),
  signals:         ()                                    => api.get<{ signals: Signal[] }>('/trading/signals'),
  ohlcv:           (symbol: string, tf: string, limit = 200) =>
    api.get<OHLCVBar[]>(`/trading/ohlcv/${symbol}`, { params: { timeframe: tf, limit } }),
  prices:          (symbols?: string[])                  =>
    api.get<Record<string, import('../store/useStore').PriceTick>>('/trading/prices', {
      params: symbols ? { symbols: symbols.join(',') } : undefined,
    }),
  depth:           (symbol: string, levels = 20)         =>
    api.get<OrderBookDepth>(`/trading/depth/${symbol}`, { params: { levels } }),
  symbolInfo:      (symbol: string)                      =>
    api.get<SymbolInfo>(`/trading/symbol/${symbol}`),
  symbolSearch:    (query: string)                       =>
    api.get<SymbolInfo[]>('/trading/symbols/search', { params: { q: query } }),
  symbolList:      ()                                    =>
    api.get<SymbolInfo[]>('/trading/symbols'),

  // Trade history
  trades:          (params?: { symbol?: string; limit?: number; offset?: number }) =>
    api.get<{ trades: import('../store/useStore').Order[] }>('/trading/trades', { params }),
  tradeHistory:    (params?: { symbol?: string; limit?: number; offset?: number }) =>
    api.get('/trading/history', { params }),

  // Paper trading
  startPaper:      ()                                    => api.post('/trading/paper/start'),
  stopPaper:       ()                                    => api.post('/trading/paper/stop'),

  // Emergency
  emergencyStop:   ()                                    => api.post('/trading/emergency-stop'),
};

// ─── Backtesting ──────────────────────────────────────────────────────────────

export const backtestApi = {
  run:     (params: object)  => api.post('/backtesting/run', params),
  results: (id: string)      => api.get(`/backtesting/results/${id}`),
  list:    ()                => api.get('/backtesting/list'),
};

// ─── ML ───────────────────────────────────────────────────────────────────────

export const mlApi = {
  predict:  (symbol: string) => api.get(`/ml/predict/${symbol}`),
  accuracy: ()               => api.get('/ml/accuracy'),
  models:   ()               => api.get('/ml/models'),
  health:   ()               => api.get('/ml/health'),
};

// ─── Performance ──────────────────────────────────────────────────────────────

export const performanceApi = {
  public:        ()          => api.get('/performance/public'),
  equityCurve:   ()          => api.get('/pnl/equity-curve'),
  drawdownCurve: ()          => api.get('/pnl/drawdown-curve'),
  summary:       ()          => api.get('/pnl/summary'),
  tradeLog:      (params?: { limit?: number; offset?: number }) =>
    api.get('/pnl/trade-log', { params }),
  openPositions: ()          => api.get('/pnl/open-positions'),
};

// ─── Alerts ───────────────────────────────────────────────────────────────────

export const alertsApi = {
  list:   ()                 => api.get('/alerts'),
  create: (payload: object)  => api.post('/alerts', payload),
  delete: (id: string)       => api.delete(`/alerts/${id}`),
  toggle: (id: string)       => api.patch(`/alerts/${id}/toggle`),
};

// ─── Watchlist ────────────────────────────────────────────────────────────────

export const watchlistApi = {
  get:    ()                 => api.get('/watchlist'),
  add:    (symbol: string)   => api.post('/watchlist', { symbol }),
  remove: (symbol: string)   => api.delete(`/watchlist/${symbol}`),
};
