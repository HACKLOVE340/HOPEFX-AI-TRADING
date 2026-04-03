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
  positions:      ()              => api.get('/trading/positions'),
  signals:        ()              => api.get('/trading/signals'),
  account:        ()              => api.get('/trading/account'),
  ohlcv:          (symbol: string, timeframe = '1h', limit = 200) =>
    api.get(`/trading/ohlcv/${encodeURIComponent(symbol)}`, { params: { timeframe, limit } }),
  placeOrder:     (order: object) => api.post('/trading/orders', order),
  closePosition:  (id: string)    => api.delete(`/trading/positions/${id}`),
  closeAllPositions: ()           => api.delete('/trading/positions'),
  trades:         (limit = 100)   => api.get('/trading/trades', { params: { limit } }),
  regime:         ()              => api.get('/trading/regime'),
  brainState:     ()              => api.get('/trading/brain-state'),
  emergencyStop:  ()              => api.post('/trading/emergency-stop'),
};

// ── Backtesting ───────────────────────────────────────────────────────────────

export const backtestApi = {
  run:     (params: object) => api.post('/backtesting/run', params),
  results: (id: string)     => api.get(`/backtesting/results/${id}`),
  list:    ()               => api.get('/backtesting/list'),
};

// ── ML ────────────────────────────────────────────────────────────────────────

export const mlApi = {
  predict:  (symbol: string, payload?: object) => api.post(`/ml/predict/${encodeURIComponent(symbol)}`, payload ?? {}),
  accuracy: ()               => api.get('/ml/accuracy'),
  models:   ()               => api.get('/ml/models'),
  features: ()               => api.get('/ml/features'),
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

// ── SuperAdmin ────────────────────────────────────────────────────────────────

export const superadminApi = {
  // Platform overview
  overview:          ()                        => api.get('/superadmin/overview'),

  // User management
  users:             (params?: Record<string, string>) => api.get('/superadmin/users', { params }),
  getUser:           (id: string)              => api.get(`/superadmin/users/${id}`),
  updateUser:        (id: string, p: object)   => api.patch(`/superadmin/users/${id}`, p),
  deleteUser:        (id: string)              => api.delete(`/superadmin/users/${id}`),
  impersonateUser:   (id: string)              => api.post(`/superadmin/users/${id}/impersonate`),
  resetUserPassword: (id: string)              => api.post(`/superadmin/users/${id}/reset-password`),
  setUserRole:       (id: string, role: string) => api.patch(`/superadmin/users/${id}/role`, { role }),
  setUserPlan:       (id: string, plan: string) => api.patch(`/superadmin/users/${id}/plan`, { plan }),
  banUser:           (id: string, reason: string) => api.post(`/superadmin/users/${id}/ban`, { reason }),
  unbanUser:         (id: string)              => api.post(`/superadmin/users/${id}/unban`),
  userActivity:      (id: string)              => api.get(`/superadmin/users/${id}/activity`),

  // Platform settings
  platformConfig:    ()                        => api.get('/superadmin/platform/config'),
  updatePlatformConfig: (p: object)            => api.patch('/superadmin/platform/config', p),
  maintenanceMode:   (enabled: boolean, msg?: string) =>
    api.post('/superadmin/platform/maintenance', { enabled, message: msg }),
  broadcastMessage:  (p: object)               => api.post('/superadmin/platform/broadcast', p),

  // ML / AI engine
  mlStatus:          ()                        => api.get('/superadmin/ml/status'),
  mlModels:          ()                        => api.get('/superadmin/ml/models'),
  retrainModel:      (model: string, p?: object) => api.post(`/superadmin/ml/retrain/${model}`, p ?? {}),
  deployModel:       (model: string, version: string) =>
    api.post(`/superadmin/ml/deploy`, { model, version }),
  rollbackModel:     (model: string)           => api.post(`/superadmin/ml/rollback/${model}`),
  mlMetrics:         ()                        => api.get('/superadmin/ml/metrics'),
  rlAgentStatus:     ()                        => api.get('/superadmin/ml/rl/status'),
  rlAgentControl:    (action: string)          => api.post('/superadmin/ml/rl/control', { action }),

  // Trading engine
  engineStatus:      ()                        => api.get('/superadmin/engine/status'),
  engineConfig:      ()                        => api.get('/superadmin/engine/config'),
  updateEngineConfig: (p: object)              => api.patch('/superadmin/engine/config', p),
  killSwitch:        (enabled: boolean)        => api.post('/superadmin/engine/kill-switch', { enabled }),
  pauseTrading:      (reason: string)          => api.post('/superadmin/engine/pause', { reason }),
  resumeTrading:     ()                        => api.post('/superadmin/engine/resume'),
  engineMetrics:     ()                        => api.get('/superadmin/engine/metrics'),

  // Financial / billing
  revenueStats:      (period?: string)         => api.get('/superadmin/financial/revenue', { params: period ? { period } : {} }),
  subscriptionStats: ()                        => api.get('/superadmin/financial/subscriptions'),
  paymentHistory:    (params?: Record<string, string>) => api.get('/superadmin/financial/payments', { params }),
  refundPayment:     (id: string, reason: string) => api.post(`/superadmin/financial/payments/${id}/refund`, { reason }),
  affiliateStats:    ()                        => api.get('/superadmin/financial/affiliates'),

  // Security
  securityEvents:    (params?: Record<string, string>) => api.get('/superadmin/security/events', { params }),
  blockedIPs:        ()                        => api.get('/superadmin/security/blocked-ips'),
  blockIP:           (ip: string, reason: string) => api.post('/superadmin/security/block-ip', { ip, reason }),
  unblockIP:         (ip: string)              => api.delete(`/superadmin/security/blocked-ips/${ip}`),
  activeSessions:    ()                        => api.get('/superadmin/security/sessions'),
  revokeSession:     (sessionId: string)       => api.delete(`/superadmin/security/sessions/${sessionId}`),
  revokeAllSessions: (userId: string)          => api.delete(`/superadmin/security/sessions/user/${userId}`),
  threatIntel:       ()                        => api.get('/superadmin/security/threat-intel'),

  // System logs
  logs:              (params?: Record<string, string>) => api.get('/superadmin/logs', { params }),
  logLevels:         ()                        => api.get('/superadmin/logs/levels'),
  setLogLevel:       (logger: string, level: string) =>
    api.patch('/superadmin/logs/levels', { logger, level }),
  exportLogs:        (params?: Record<string, string>) =>
    api.get('/superadmin/logs/export', { params, responseType: 'blob' }),

  // Feature flags
  featureFlags:      ()                        => api.get('/superadmin/feature-flags'),
  setFeatureFlag:    (name: string, enabled: boolean, userIds?: string[]) =>
    api.patch(`/superadmin/feature-flags/${name}`, { enabled, user_ids: userIds }),
  userFlagOverrides: (userId: string)          => api.get(`/superadmin/feature-flags/overrides/${userId}`),
  setUserFlagOverride: (userId: string, flag: string, enabled: boolean) =>
    api.patch(`/superadmin/feature-flags/overrides/${userId}/${flag}`, { enabled }),

  // Audit
  auditLog:          (params?: Record<string, string>) => api.get('/superadmin/audit', { params }),
  exportAudit:       ()                        => api.get('/superadmin/audit/export', { responseType: 'blob' }),

  // Infrastructure
  infraHealth:       ()                        => api.get('/superadmin/infra/health'),
  cacheStats:        ()                        => api.get('/superadmin/infra/cache'),
  flushCache:        (pattern?: string)        => api.post('/superadmin/infra/cache/flush', { pattern }),
  dbStats:           ()                        => api.get('/superadmin/infra/db'),
  queueStats:        ()                        => api.get('/superadmin/infra/queues'),
};
