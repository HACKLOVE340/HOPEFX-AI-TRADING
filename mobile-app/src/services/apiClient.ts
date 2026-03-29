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

const BASE_URL: string =
  (Constants.expoConfig?.extra?.apiBaseUrl as string) ?? 'http://localhost:8000';

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
    const res = await _axios.post<AuthTokens>('/api/auth/2fa/verify', { code });
    _accessToken = res.data.access_token;
    _refreshToken = res.data.refresh_token;
    return res.data;
  },

  async forgotPassword(email: string): Promise<void> {
    await _axios.post('/api/auth/forgot-password', { email });
  },

  // ── Account ────────────────────────────────────────────────────────────────

  async getAccount(): Promise<Account> {
    const res = await _axios.get<Account>('/api/trading/account');
    return res.data;
  },

  // ── Market data ────────────────────────────────────────────────────────────

  async getQuote(symbol: string): Promise<Quote> {
    const res = await _axios.get<Quote>(`/api/trading/price/${symbol}`);
    return res.data;
  },

  async getQuotes(symbols: string[]): Promise<Quote[]> {
    const res = await _axios.get<Quote[]>('/api/trading/prices', {
      params: { symbols: symbols.join(',') },
    });
    return res.data;
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
    const res = await _axios.get<Order[]>('/api/trading/orders', {
      params: status ? { status } : undefined,
    });
    return res.data;
  },

  async cancelOrder(orderId: string): Promise<void> {
    await _axios.delete(`/api/trading/order/${orderId}`);
  },

  // ── Positions ──────────────────────────────────────────────────────────────

  async getPositions(): Promise<Position[]> {
    const res = await _axios.get<Position[]>('/api/trading/positions');
    return res.data;
  },

  async closePosition(positionId: string): Promise<void> {
    await _axios.post(`/api/trading/position/${positionId}/close`);
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
    const res = await _axios.get<Signal[]>(`/api/signals/history/${symbol}`, {
      params: { limit },
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
    const res = await _axios.get('/api/performance/summary', { params: { period } });
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
