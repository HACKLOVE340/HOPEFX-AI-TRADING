// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/apiClient.ts
 * =====================
 * Axios-based HTTP client wired to the HopeFX backend.
 *
 * Features:
 *  - Base URL from app.json extra.apiBaseUrl (overridable via env)
 *  - JWT Bearer token injection on every request
 *  - Automatic token refresh on 401 (single-flight, no duplicate refreshes)
 *  - Request/response logging in dev mode
 *  - Typed response helpers for all API domains
 */

import axios, {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import Constants from 'expo-constants';
import {
  Account,
  AuthTokens,
  Order,
  Position,
  Quote,
  Signal,
  Trade,
  User,
  NotificationPrefs,
  PushToken,
} from '../types';

// ── Config ────────────────────────────────────────────────────────────────────

// BASE_URL must come from app.json extra.apiBaseUrl (set to https://api.hopefx.io
// for production builds via EAS).  There is no localhost fallback — a missing
// config value is a build misconfiguration that should fail loudly, not silently
// point at a developer machine.
const _configuredUrl = Constants.expoConfig?.extra?.apiBaseUrl as string | undefined;
if (!_configuredUrl) {
  throw new Error(
    '[apiClient] Constants.expoConfig.extra.apiBaseUrl is not set. ' +
      'Ensure app.json extra.apiBaseUrl is configured for this build target.'
  );
}
const BASE_URL: string = _configuredUrl;

const TIMEOUT_MS = 15_000;

// ── Token store (in-memory; SecureStore is the source of truth) ───────────────

let _accessToken: string | null = null;
let _refreshToken: string | null = null;
let _refreshPromise: Promise<string> | null = null;

// ── Axios instance ────────────────────────────────────────────────────────────

const _axios: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor — inject Bearer token
_axios.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (_accessToken && config.headers) {
    config.headers['Authorization'] = `Bearer ${_accessToken}`;
  }
  return config;
});

// Response interceptor — handle 401 with token refresh
_axios.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };
    if (error.response?.status === 401 && !original._retry && _refreshToken) {
      original._retry = true;
      try {
        const newToken = await _doRefresh();
        if (original.headers) {
          (original.headers as Record<string, string>)['Authorization'] = `Bearer ${newToken}`;
        }
        return _axios(original);
      } catch {
        // Refresh failed — caller will receive the 401
      }
    }
    return Promise.reject(error);
  }
);

async function _doRefresh(): Promise<string> {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = _axios
    .post<AuthTokens>('/api/auth/refresh', { refresh_token: _refreshToken })
    .then((res) => {
      _accessToken = res.data.access_token;
      _refreshToken = res.data.refresh_token;
      return _accessToken;
    })
    .finally(() => {
      _refreshPromise = null;
    });
  return _refreshPromise;
}

// ── Public API ────────────────────────────────────────────────────────────────

export const apiClient = {
  // ── Token management ───────────────────────────────────────────────────────

  setAuthToken(token: string): void {
    _accessToken = token;
  },

  setRefreshToken(token: string): void {
    _refreshToken = token;
  },

  clearTokens(): void {
    _accessToken = null;
    _refreshToken = null;
  },

  // ── Auth ───────────────────────────────────────────────────────────────────

  async login(email: string, password: string): Promise<AuthTokens> {
    const res = await _axios.post<AuthTokens>('/api/auth/login', { email, password });
    _accessToken = res.data.access_token;
    _refreshToken = res.data.refresh_token;
    return res.data;
  },

  async register(
    email: string,
    password: string,
    username: string
  ): Promise<AuthTokens> {
    const res = await _axios.post<AuthTokens>('/api/auth/register', {
      email,
      password,
      username,
    });
    _accessToken = res.data.access_token;
    _refreshToken = res.data.refresh_token;
    return res.data;
  },

  async logout(): Promise<void> {
    try {
      await _axios.post('/api/auth/logout');
    } finally {
      apiClient.clearTokens();
    }
  },

  async getMe(): Promise<User> {
    const res = await _axios.get<User>('/api/auth/me');
    return res.data;
  },

  async verifyTwoFactor(code: string): Promise<AuthTokens> {
    // Backend endpoint: POST /api/auth/2fa/confirm (confirm = verify after scanning QR)
    const res = await _axios.post<AuthTokens>('/api/auth/2fa/confirm', { code });
    _accessToken = res.data.access_token;
    _refreshToken = res.data.refresh_token;
    return res.data;
  },

  async forgotPassword(email: string): Promise<void> {
    await _axios.post('/api/auth/forgot-password', { email });
  },

  /** Alias used by ForgotPasswordScreen */
  async requestPasswordReset(email: string): Promise<void> {
    await _axios.post('/api/auth/forgot-password', { email });
  },

  /** Full 2FA verify with email + password + code (used by TwoFactorScreen) */
  async verifyTwoFactorLogin(email: string, password: string, code: string): Promise<import('../types').AuthTokens> {
    const res = await _axios.post<import('../types').AuthTokens>('/api/auth/2fa/verify', { email, password, code });
    _accessToken  = res.data.access_token;
    _refreshToken = res.data.refresh_token;
    return res.data;
  },

  // ── Account ────────────────────────────────────────────────────────────────

  async getAccount(): Promise<Account> {
    const res = await _axios.get<Account>('/api/trading/account');
    return res.data;
  },

  // ── Market data ────────────────────────────────────────────────────────────

  async getQuote(symbol: string): Promise<Quote> {
    // Backend: GET /api/trading/prices → Dict[symbol, {bid, ask, last, timestamp}]
    const res = await _axios.get<Record<string, { bid: number; ask: number; last: number; timestamp: number }>>('/api/trading/prices');
    const raw = res.data[symbol];
    if (!raw) throw new Error(`No price data for ${symbol}`);
    const mid = (raw.bid + raw.ask) / 2;
    return {
      symbol,
      bid: raw.bid,
      ask: raw.ask,
      mid,
      spread: raw.ask - raw.bid,
      timestamp: new Date(raw.timestamp * 1000).toISOString(),
      change_pct: 0, // not provided by this endpoint
    };
  },

  async getQuotes(symbols: string[]): Promise<Quote[]> {
    const res = await _axios.get<Record<string, { bid: number; ask: number; last: number; timestamp: number }>>('/api/trading/prices');
    return symbols
      .filter((s) => res.data[s])
      .map((s) => {
        const raw = res.data[s];
        const mid = (raw.bid + raw.ask) / 2;
        return {
          symbol: s,
          bid: raw.bid,
          ask: raw.ask,
          mid,
          spread: raw.ask - raw.bid,
          timestamp: new Date(raw.timestamp * 1000).toISOString(),
          change_pct: 0,
        };
      });
  },

  // ── Orders ─────────────────────────────────────────────────────────────────

  async placeOrder(order: {
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    order_type?: 'market' | 'limit' | 'stop';
    price?: number;
    stop_loss?: number;
    take_profit?: number;
  }): Promise<Order> {
    const res = await _axios.post<Order>('/api/trading/order', order);
    return res.data;
  },

  async getOrders(status?: string): Promise<Order[]> {
    // Backend stores orders inside positions; use /api/trading/trades for history
    // and /api/trading/positions for open orders. This shim returns open positions
    // as pending orders when status is 'open'/'pending', trades otherwise.
    if (!status || status === 'open' || status === 'pending') {
      const res = await _axios.get<Position[]>('/api/trading/positions');
      // Map positions to Order shape for the mobile store
      return res.data.map((p) => ({
        id: p.id,
        symbol: p.symbol,
        side: p.side,
        type: 'market' as const,
        quantity: p.quantity,
        status: 'open' as const,
        created_at: p.opened_at,
        fill_price: p.entry_price,
      }));
    }
    const res = await _axios.get<Trade[]>('/api/trading/trades', { params: { limit: 50 } });
    return res.data.map((t) => ({
      id: t.id,
      symbol: t.symbol,
      side: t.side,
      type: 'market' as const,
      quantity: t.quantity,
      status: 'filled' as const,
      created_at: t.opened_at,
      filled_at: t.closed_at,
      fill_price: t.exit_price,
    }));
  },

  async cancelOrder(orderId: string): Promise<void> {
    // Backend: DELETE /api/trading/positions/{position_id} closes/cancels a position
    await _axios.delete(`/api/trading/positions/${orderId}`);
  },

  // ── Positions ──────────────────────────────────────────────────────────────

  async getPositions(): Promise<Position[]> {
    const res = await _axios.get<Position[]>('/api/trading/positions');
    return res.data;
  },

  async closePosition(positionId: string): Promise<void> {
    // Backend: DELETE /api/trading/positions/{position_id}
    await _axios.delete(`/api/trading/positions/${positionId}`);
  },

  // ── Trade history ──────────────────────────────────────────────────────────

  async getTrades(limit = 50, offset = 0): Promise<Trade[]> {
    const res = await _axios.get<Trade[]>('/api/trading/trades', {
      params: { limit, offset },
    });
    return res.data;
  },

  // ── Signals ────────────────────────────────────────────────────────────────

  async getSignals(symbol?: string): Promise<Signal[]> {
    const res = await _axios.get<Signal[]>('/api/signals/latest', {
      params: symbol ? { symbol } : undefined,
    });
    return res.data;
  },

  async getSignalHistory(symbol: string, limit = 20): Promise<Signal[]> {
    // Backend: GET /api/signals/history (no symbol path param — use query param)
    const res = await _axios.get<Signal[]>('/api/signals/history', {
      params: { symbol, limit },
    });
    return res.data;
  },

  // ── Push notifications ─────────────────────────────────────────────────────

  async registerPushToken(pushToken: PushToken): Promise<void> {
    await _axios.post('/api/mobile/push-token', pushToken);
  },

  async getNotificationPrefs(): Promise<NotificationPrefs> {
    const res = await _axios.get<NotificationPrefs>('/api/mobile/notification-prefs');
    return res.data;
  },

  async updateNotificationPrefs(prefs: Partial<NotificationPrefs>): Promise<void> {
    await _axios.patch('/api/mobile/notification-prefs', prefs);
  },

  // ── Performance ────────────────────────────────────────────────────────────

  async getPerformance(period = '30d'): Promise<Record<string, unknown>> {
    // Backend: GET /api/trading/performance/summary
    const res = await _axios.get('/api/trading/performance/summary', { params: { period } });
    return res.data;
  },

  // ── Risk metrics ──────────────────────────────────────────────────────────

  async getRiskMetrics(): Promise<import('../types').RiskMetrics> {
    const res = await _axios.get<import('../types').RiskMetrics>('/api/risk/metrics');
    return res.data;
  },

  // ── Sentiment ──────────────────────────────────────────────────────────────

  async getSentiment(symbol = 'XAUUSD'): Promise<import('../types').SentimentData> {
    const res = await _axios.get<import('../types').SentimentData>('/api/sentiment/latest', {
      params: { symbol },
    });
    return res.data;
  },

  // ── Raw access ─────────────────────────────────────────────────────────────

  get<T>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return _axios.get<T>(url, config);
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return _axios.post<T>(url, data, config);
  },
  patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return _axios.patch<T>(url, data, config);
  },
  delete<T>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    return _axios.delete<T>(url, config);
  },
};

// ── Risk metrics ───────────────────────────────────────────────────────────────
// (appended to existing apiClient export)
