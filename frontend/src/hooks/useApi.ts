/**
 * hooks/useApi.ts
 * Single axios instance with JWT injection and 401 auto-logout.
 * All API modules import from here. lib/api.ts re-exports this file.
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

export interface LoginPayload  { email: string; password: string }
export interface LoginResponse { access_token: string; token_type: string; user: import('../store').User }

export const authApi = {
  login:    (payload: LoginPayload)  => api.post<LoginResponse>('/auth/login', payload),
  logout:   ()                       => api.post('/auth/logout'),
  me:       ()                       => api.get<import('../store').User>('/auth/me'),
  register: (payload: { email: string; username: string; password: string }) =>
    api.post('/auth/register', payload),
  activateFreeTier: (userId: string, refCode?: string) =>
    api.post('/auth/activate-free-tier', { user_id: userId, ref_code: refCode }),
};

// ── Trading ───────────────────────────────────────────────────────────────────

export const tradingApi = {
  positions:     ()              => api.get('/trading/positions'),
  signals:       ()              => api.get('/trading/signals'),
  account:       ()              => api.get('/trading/account'),
  placeOrder:    (order: object) => api.post('/trading/orders', order),
  closePosition: (id: string)    => api.delete(`/trading/positions/${id}`),
};

// ── Backtesting ───────────────────────────────────────────────────────────────

export const backtestApi = {
  run:     (params: object) => api.post('/backtesting/run', params),
  results: (id: string)     => api.get(`/backtesting/results/${id}`),
  list:    ()               => api.get('/backtesting/list'),
};

// ── ML ────────────────────────────────────────────────────────────────────────

export const mlApi = {
  predict:  (symbol: string) => api.get(`/ml/predict/${symbol}`),
  accuracy: ()               => api.get('/ml/accuracy'),
  models:   ()               => api.get('/ml/models'),
  features: (symbol: string) => api.get(`/ml/features/${symbol}`),
};

// ── Accounts / Teams ──────────────────────────────────────────────────────────

export const accountsApi = {
  listSubAccounts:  ()                                          => api.get('/accounts/sub-accounts'),
  createSubAccount: (payload: object)                          => api.post('/accounts/sub-accounts', payload),
  updateSubAccount: (id: string, p: object)                    => api.patch(`/accounts/sub-accounts/${id}`, p),
  deleteSubAccount: (id: string)                               => api.delete(`/accounts/sub-accounts/${id}`),
  listTeams:        ()                                         => api.get('/accounts/teams'),
  createTeam:       (payload: object)                          => api.post('/accounts/teams', payload),
  inviteMember:     (teamId: string, p: object)                => api.post(`/accounts/teams/${teamId}/members`, p),
  updateMember:     (teamId: string, uid: string, p: object)   => api.patch(`/accounts/teams/${teamId}/members/${uid}`, p),
  removeMember:     (teamId: string, uid: string)              => api.delete(`/accounts/teams/${teamId}/members/${uid}`),
};

// ── Audit ─────────────────────────────────────────────────────────────────────

export const auditApi = {
  list:   (params?: Record<string, string>) => api.get('/admin/audit-log', { params }),
  export: ()                                => api.get('/admin/audit-log/export', { responseType: 'blob' }),
};

// ── Walk-forward ──────────────────────────────────────────────────────────────

export const walkForwardApi = {
  list: ()           => api.get('/backtesting/walk-forward'),
  get:  (id: string) => api.get(`/backtesting/walk-forward/${id}`),
  run:  (p: object)  => api.post('/backtesting/walk-forward/run', p),
};

// ── Correlation ───────────────────────────────────────────────────────────────

export const correlationApi = {
  matrix: (window?: number) => api.get('/advanced/correlation', { params: window ? { window } : {} }),
  cot:    ()                => api.get('/advanced/cot-sentiment'),
};

// ── A/B Testing ───────────────────────────────────────────────────────────────

export const abTestingApi = {
  list: ()           => api.get('/advanced/ab-tests'),
  get:  (id: string) => api.get(`/advanced/ab-tests/${id}`),
  run:  (p: object)  => api.post('/advanced/ab-tests/run', p),
};

// ── Leaderboard ───────────────────────────────────────────────────────────────

export const leaderboardApi = {
  list: (period?: string) => api.get('/leaderboard', { params: period ? { period } : {} }),
};

// ── Performance ───────────────────────────────────────────────────────────────

export const performanceApi = {
  summary:     ()  => api.get('/performance/public'),
  equity:      ()  => api.get('/performance/equity-curve'),
  equityCurve: ()  => api.get('/performance/equity-curve'),
  trades:      ()  => api.get('/trading/trades'),
  weekly:      ()  => api.get('/performance/weekly-report/latest'),
  weeklyList:  ()  => api.get('/performance/weekly-report/list'),
};

// ── Data layer (orchestrator) ─────────────────────────────────────────────────

export const dataLayerApi = {
  health:         ()                   => api.get('/data-layer/health'),
  tick:           (symbol = 'XAU_USD') => api.get('/data-layer/tick', { params: { symbol } }),
  sentiment:      ()                   => api.get('/data-layer/sentiment'),
  macro:          ()                   => api.get('/data-layer/macro'),
  microstructure: (symbol = 'XAU_USD') => api.get('/data-layer/microstructure', { params: { symbol } }),
  quality:        (symbol = 'XAU_USD') => api.get('/data-layer/quality', { params: { symbol } }),
  lineage:        (limit = 50)         => api.get('/data-layer/lineage', { params: { limit } }),
  feeds:          ()                   => api.get('/data-layer/feeds'),
};

// ── Signals ───────────────────────────────────────────────────────────────────

export const signalsApi = {
  active:    ()                   => api.get('/signals/active'),
  latest:    ()                   => api.get('/signals/latest'),
  history:   (limit = 50)         => api.get('/signals/history', { params: { limit } }),
  summary:   ()                   => api.get('/signals/summary'),
  analytics: ()                   => api.get('/signals/analytics'),
  generate:  (payload: object)    => api.post('/signals/generate', payload),
  setAlert:  (payload: object)    => api.post('/signals/alerts', payload),
};

// ── ML extended ───────────────────────────────────────────────────────────────

export const mlExtendedApi = {
  health:        ()                   => api.get('/ml/health'),
  retrain:       (payload?: object)   => api.post('/ml/retrain', payload ?? {}),
  filterStats:   ()                   => api.get('/ml/signal-filter/stats'),
  rlStatus:      ()                   => api.get('/ml/rl/status'),
  rlTrain:       (payload: object)    => api.post('/ml/rl/train', payload),
  walkForward:   (payload: object)    => api.post('/ml/rl/walk-forward', payload),
  explain:       (symbol: string)     => api.get(`/explain/${symbol}`),
};

// ── Calendar ──────────────────────────────────────────────────────────────────

export const calendarApi = {
  upcoming:   (hours = 168)  => api.get('/calendar/upcoming', { params: { hours } }),
  today:      ()             => api.get('/calendar/today'),
  highImpact: ()             => api.get('/calendar/high-impact'),
  autoPause:  ()             => api.get('/calendar/auto-pause'),
  setAutoPause: (cfg: object) => api.post('/calendar/auto-pause', cfg),
  fomc:       ()             => api.get('/calendar/fomc'),
};
