/**
 * lib/api.ts — typed axios instance with JWT injection and 401 auto-logout.
 * Extends the existing useApi.ts with data-layer endpoints.
 */

import axios, { type AxiosInstance } from 'axios';
import { useStore } from '../store';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const BASE_URL = ((import.meta as any).env?.VITE_API_URL as string | undefined) ?? '/api';

export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = useStore.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) useStore.getState().clearAuth();
    return Promise.reject(err);
  },
);

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login:    (p: { email: string; password: string }) =>
    api.post<{ access_token: string; token_type: string; user: import('../types').User }>('/auth/login', p),
  logout:   () => api.post('/auth/logout'),
  me:       () => api.get<import('../types').User>('/auth/me'),
  register: (p: { email: string; username: string; password: string }) =>
    api.post('/auth/register', p),
};

// ── Trading ───────────────────────────────────────────────────────────────────

export const tradingApi = {
  positions:     () => api.get<import('../types').Position[]>('/trading/positions'),
  signals:       () => api.get<import('../types').Signal[]>('/trading/signals'),
  account:       () => api.get<import('../types').AccountMetrics>('/trading/account'),
  placeOrder:    (order: object) => api.post('/trading/orders', order),
  closePosition: (id: string)   => api.delete(`/trading/positions/${id}`),
};

// ── Data layer (orchestrator) ─────────────────────────────────────────────────

export const dataLayerApi = {
  health:         () => api.get<import('../types').OrchestratorHealth>('/data-layer/health'),
  tick:           (symbol = 'XAU_USD') => api.get<import('../types').GoldTick>('/data-layer/tick', { params: { symbol } }),
  sentiment:      () => api.get<import('../types').SentimentResponse>('/data-layer/sentiment'),
  macro:          () => api.get<import('../types').MacroResponse>('/data-layer/macro'),
  microstructure: (symbol = 'XAU_USD') => api.get('/data-layer/microstructure', { params: { symbol } }),
  quality:        (symbol = 'XAU_USD') => api.get<import('../types').QualityReport>('/data-layer/quality', { params: { symbol } }),
  lineage:        (limit = 50) => api.get('/data-layer/lineage', { params: { limit } }),
  feeds:          () => api.get('/data-layer/feeds'),
};

// ── Performance ───────────────────────────────────────────────────────────────

export const performanceApi = {
  summary:    () => api.get<import('../types').PerformanceSummary>('/performance/summary'),
  equityCurve: () => api.get<import('../types').EquityPoint[]>('/performance/equity-curve'),
  trades:     () => api.get('/performance/trades'),
};

// ── Macro ─────────────────────────────────────────────────────────────────────

export const macroApi = {
  snapshot: () => api.get('/macro/snapshot'),
  features: () => api.get('/macro/features'),
};

// ── Signals ───────────────────────────────────────────────────────────────────

export const signalsApi = {
  active:  () => api.get<import('../types').Signal[]>('/signals/active'),
  history: (limit = 50) => api.get('/signals/history', { params: { limit } }),
};
