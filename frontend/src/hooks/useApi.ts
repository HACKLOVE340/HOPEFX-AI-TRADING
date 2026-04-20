/**
 * hooks/useApi.ts
 * Single axios instance with JWT injection, CSRF double-submit, and 401 auto-logout.
 * All API modules import from here. lib/api.ts re-exports this file.
 */

import axios, { type AxiosInstance } from 'axios';
import { useStore } from '../store';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api';

export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

// ── CSRF token management ─────────────────────────────────────────────────────
// The backend issues a CSRF token via GET /api/auth/csrf-token, setting a
// SameSite=Strict cookie (hopefx_csrf) and returning the value in the body.
// Every state-changing request must echo the token back as X-CSRF-Token.
// We cache the token in memory and refresh it when it expires (1 hour TTL).

const CSRF_HEADER   = 'X-CSRF-Token';
const CSRF_COOKIE   = 'hopefx_csrf';
const CSRF_TTL_MS   = 55 * 60 * 1000; // 55 min — refresh before the 1-hour server TTL

let _csrfToken: string | null = null;
let _csrfFetchedAt  = 0;
let _csrfFetchPromise: Promise<string | null> | null = null;

/** Read the hopefx_csrf cookie value set by the server. */
function _readCsrfCookie(): string | null {
  const match = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null;
}

/** Fetch a fresh CSRF token from the server. Deduplicates concurrent calls. */
async function _fetchCsrfToken(): Promise<string | null> {
  if (_csrfFetchPromise) return _csrfFetchPromise;

  _csrfFetchPromise = (async () => {
    // Attempt up to 2 fetches before giving up so transient network errors
    // don't permanently break CSRF injection for the session lifetime.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        // Use a bare axios call — not the intercepted `api` instance — to avoid
        // a circular dependency where the interceptor waits on itself.
        const res = await axios.get<{ csrf_token: string }>(`${BASE_URL}/auth/csrf-token`, {
          withCredentials: true,
          timeout: 5000,
        });
        const token = res.data?.csrf_token ?? _readCsrfCookie();
        if (token) {
          _csrfToken     = token;
          _csrfFetchedAt = Date.now();
          return _csrfToken;
        }
      } catch {
        // Fall back to reading the cookie directly (server may have set it already).
        const cookieVal = _readCsrfCookie();
        if (cookieVal) {
          _csrfToken     = cookieVal;
          _csrfFetchedAt = Date.now();
          return _csrfToken;
        }
        // Brief pause before retry
        if (attempt === 0) await new Promise((r) => setTimeout(r, 300));
      }
    }
    return _csrfToken; // return whatever we have (may be null)
  })().finally(() => {
    _csrfFetchPromise = null;
  });

  return _csrfFetchPromise;
}

/** Return a valid CSRF token, fetching one if the cache is stale or empty. */
export async function getCsrfToken(): Promise<string | null> {
  return _getCsrfToken();
}

/**
 * Eagerly fetch and cache a CSRF token.
 * Call this immediately after login so the token is ready before the first
 * state-changing request, avoiding a round-trip delay on the first POST.
 */
export async function prefetchCsrfToken(): Promise<void> {
  await _fetchCsrfToken();
}

/**
 * Immediately invalidate the in-memory CSRF token cache.
 * Call this on logout so the next request fetches a fresh token rather than
 * sending a stale one that the server has already invalidated.
 * The cookie self-heals via _getCsrfToken()'s cookie-absent check, but
 * explicit reset avoids a window where the stale in-memory value is used.
 */
export function resetCsrfCache(): void {
  _csrfToken     = null;
  _csrfFetchedAt = 0;
}

async function _getCsrfToken(): Promise<string | null> {
  const cookieVal = _readCsrfCookie();

  // If the cookie was cleared (e.g. after logout) reset the in-memory cache.
  if (!cookieVal) {
    _csrfToken    = null;
    _csrfFetchedAt = 0;
  }

  if (_csrfToken && cookieVal === _csrfToken && Date.now() - _csrfFetchedAt < CSRF_TTL_MS) {
    return _csrfToken;
  }

  return _fetchCsrfToken();
}

// Methods that require CSRF validation (mirrors core/middleware.py).
const CSRF_PROTECTED_METHODS = new Set(['post', 'put', 'patch', 'delete']);

// Paths exempt from CSRF (mirrors _CSRF_EXEMPT_PREFIXES in core/middleware.py).
const CSRF_EXEMPT_PREFIXES = [
  '/auth/csrf-token',
  '/auth/login',
  '/auth/register',
  '/auth/activate-free-tier',  // post-registration setup, called before session cookie exists
  '/auth/refresh',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/verify-email',
  '/auth/resend-verification',
  '/email/webhook',
  '/health',
];

api.interceptors.request.use(async (config) => {
  // Prefer the Zustand store token; fall back to localStorage for the window
  // between page load and Zustand persist rehydration completing.
  const token = useStore.getState().token ?? localStorage.getItem('hopefx_access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;

  // Inject CSRF header on state-changing requests to non-exempt paths.
  const method  = (config.method ?? '').toLowerCase();
  const url     = config.url ?? '';
  const isExempt = CSRF_EXEMPT_PREFIXES.some((p) => url.startsWith(p));

  if (CSRF_PROTECTED_METHODS.has(method) && !isExempt) {
    const csrfToken = await _getCsrfToken();
    if (csrfToken) config.headers[CSRF_HEADER] = csrfToken;
  }

  return config;
});

// ── Silent token refresh on 401 ───────────────────────────────────────────────
// When any request returns 401 we attempt one silent refresh using the stored
// refresh_token.  On success the new access token is saved and the original
// request is retried transparently.  On failure (refresh token also expired or
// revoked) the session is cleared and the user is sent to /login.

let _refreshPromise: Promise<string | null> | null = null;

async function _silentRefresh(): Promise<string | null> {
  // Deduplicate: if a refresh is already in-flight, wait for it.
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    const refreshToken = localStorage.getItem('hopefx_refresh_token');
    if (!refreshToken) return null;
    try {
      const res = await axios.post(`${BASE_URL}/auth/refresh`, { refresh_token: refreshToken });
      const { access_token, refresh_token: newRefresh } = res.data;
      // Persist new tokens
      localStorage.setItem('hopefx_access_token',  access_token);
      localStorage.setItem('hopefx_refresh_token', newRefresh ?? refreshToken);
      // Update Zustand store so all future requests use the new token
      const { user } = useStore.getState();
      if (user) useStore.getState().setAuth(access_token, user);
      return access_token as string;
    } catch {
      return null;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

/** Redirect to /login, preserving the current path so AuthGuard can restore it. */
function _redirectToLogin(): void {
  const current = window.location.pathname + window.location.search;
  // Avoid redirect loops — don't redirect if already on /login or /register.
  if (current.startsWith('/login') || current.startsWith('/register')) return;
  window.location.replace(`/login?next=${encodeURIComponent(current)}`);
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config as typeof err.config & { _retried?: boolean };
    // Only attempt refresh on 401, once per request, and not for auth endpoints
    // themselves (login/refresh/logout) to avoid infinite loops.
    const isAuthEndpoint = original?.url?.includes('/auth/login') ||
                           original?.url?.includes('/auth/refresh') ||
                           original?.url?.includes('/auth/logout');

    if (err?.response?.status === 401 && !isAuthEndpoint) {
      if (!original._retried) {
        original._retried = true;
        const newToken = await _silentRefresh();
        if (newToken) {
          // Retry the original request with the new token.
          original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` };
          return api(original);
        }
      }
      // Either already retried or refresh failed — clear session and redirect.
      useStore.getState().clearAuth();
      _redirectToLogin();
    }

    return Promise.reject(err);
  },
);

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface LoginPayload  { email?: string; username?: string; password: string }
export interface LoginResponse {
  access_token:  string;
  refresh_token: string;
  token_type:    string;
  expires_in:    number;
  user:          import('../store').User;
}

export const authApi = {
  login:    (payload: LoginPayload)  => api.post<LoginResponse>('/auth/login', payload),
  logout:   () => {
    const refreshToken = localStorage.getItem('hopefx_refresh_token');
    return api.post('/auth/logout', refreshToken ? { refresh_token: refreshToken } : {});
  },
  me:       ()                       => api.get<import('../store').User>('/auth/me'),
  register: (payload: { email: string; username: string; password: string }) =>
    api.post('/auth/register', payload),
  activateFreeTier: (userId: string, refCode?: string) =>
    api.post('/auth/activate-free-tier', { user_id: userId, ref_code: refCode }),
  /** Request a password reset email. Always returns 200 (prevents enumeration). */
  forgotPassword: (email: string) =>
    api.post('/auth/forgot-password', { email }),
  /** Set a new password using the token from the reset email. */
  resetPassword: (token: string, new_password: string) =>
    api.post('/auth/reset-password', { token, new_password }),
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
  trades:         (params?: { symbol?: string; limit?: number } | number) => {
    const limit  = typeof params === 'number' ? params : (params?.limit ?? 100);
    const symbol = typeof params === 'object' ? params?.symbol : undefined;
    return api.get('/trading/trades', { params: { limit, ...(symbol ? { symbol } : {}) } });
  },
  regime:         (symbol?: string) => api.get('/trading/regime', { params: symbol ? { symbol } : {} }),
  brainState:     ()              => api.get('/trading/brain-state'),
  emergencyStop:  ()              => api.post('/trading/emergency-stop'),
  aiAnalysis:     (payload: { symbol: string; price?: number; timeframe?: string }) =>
    api.post('/trading/ai-analysis', payload),
  riskMetrics:    ()              => api.get('/trading/risk'),
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
  bulkBanUsers:      (userIds: string[], reason?: string) => api.post('/superadmin/users/bulk/ban', { user_ids: userIds, reason }),
  bulkUnbanUsers:    (userIds: string[])       => api.post('/superadmin/users/bulk/unban', { user_ids: userIds }),
  bulkExportUsers:   (userIds: string[])       => api.post('/superadmin/users/bulk/export', { user_ids: userIds }, { responseType: 'blob' }),

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

  // Chargebacks
  chargebacks:       (params?: Record<string, string | number>) => api.get('/superadmin/financial/chargebacks', { params }),
  updateChargeback:  (id: string, body: Record<string, unknown>) => api.patch(`/superadmin/financial/chargebacks/${id}`, body),

  // Tax reports
  taxReports:        (params?: Record<string, string | number>) => api.get('/superadmin/financial/tax-reports', { params }),
  createTaxReport:   (body: Record<string, unknown>)            => api.post('/superadmin/financial/tax-reports', body),
  updateTaxReport:   (id: string, body: Record<string, unknown>) => api.patch(`/superadmin/financial/tax-reports/${id}`, body),

  // Reconciliation
  reconciliationRecords: (params?: Record<string, string | number>) => api.get('/superadmin/financial/reconciliation', { params }),
  runReconciliation:     (body: Record<string, unknown>)             => api.post('/superadmin/financial/reconciliation/run', body),
  resolveReconciliation: (id: string, notes?: string)               => api.patch(`/superadmin/financial/reconciliation/${id}`, { notes }),

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

  // ── Compliance / KYC / AML ────────────────────────────────────────────────
  kycQueue:          (params?: Record<string, string>) => api.get('/superadmin/compliance/kyc', { params }),
  approveKyc:        (userId: string)          => api.post(`/superadmin/compliance/kyc/${userId}/approve`),
  rejectKyc:         (userId: string, reason: string) =>
    api.post(`/superadmin/compliance/kyc/${userId}/reject`, { reason }),
  amlAlerts:         (params?: Record<string, string>) => api.get('/superadmin/compliance/aml/alerts', { params }),
  updateAmlAlert:    (alertId: string, status: string, notes?: string) =>
    api.patch(`/superadmin/compliance/aml/alerts/${alertId}`, { status, notes }),
  sanctionsHits:     (params?: Record<string, string>) => api.get('/superadmin/compliance/sanctions', { params }),
  clearSanctionsHit: (hitId: string)           => api.post(`/superadmin/compliance/sanctions/${hitId}/clear`),
  regulatoryReports: ()                        => api.get('/superadmin/compliance/regulatory/reports'),
  triggerRegReport:  (reportType: string, period: string) =>
    api.post('/superadmin/compliance/regulatory/trigger', { report_type: reportType, period }),
  immutableAuditLog: (params?: Record<string, string>) => api.get('/superadmin/compliance/audit-trail', { params }),
  exportAuditTrail:  ()                        => api.get('/superadmin/compliance/audit-trail/export', { responseType: 'blob' }),

  // ── Risk Management ───────────────────────────────────────────────────────
  circuitBreakers:   ()                        => api.get('/superadmin/risk/circuit-breakers'),
  resetCircuitBreaker: (name: string)          => api.post(`/superadmin/risk/circuit-breakers/${name}/reset`),
  forceOpenBreaker:  (name: string)            => api.post(`/superadmin/risk/circuit-breakers/${name}/open`),
  varMetrics:        ()                        => api.get('/superadmin/risk/var'),
  stressTestResults: ()                        => api.get('/superadmin/risk/stress-tests'),
  runStressTest:     (scenario: string)        => api.post('/superadmin/risk/stress-tests/run', { scenario }),
  propBreaches:      (params?: Record<string, string>) => api.get('/superadmin/risk/prop-breaches', { params }),
  drawdownStats:     ()                        => api.get('/superadmin/risk/drawdown'),

  // ── Broker Management / TCA ───────────────────────────────────────────────
  brokerHealth:      ()                        => api.get('/superadmin/brokers/health'),
  reconnectBroker:   (brokerId: string)        => api.post(`/superadmin/brokers/${brokerId}/reconnect`),
  disconnectBroker:  (brokerId: string)        => api.post(`/superadmin/brokers/${brokerId}/disconnect`),
  tcaMetrics:        (params?: Record<string, string>) => api.get('/superadmin/brokers/tca', { params }),
  brokerRouting:     ()                        => api.get('/superadmin/brokers/routing'),
  updateBrokerRouting: (p: object)             => api.patch('/superadmin/brokers/routing', p),

  // ── White-Label Tenants ───────────────────────────────────────────────────
  tenants:           (params?: Record<string, string>) => api.get('/superadmin/whitelabel/tenants', { params }),
  getTenant:         (id: string)              => api.get(`/superadmin/whitelabel/tenants/${id}`),
  createTenant:      (p: object)               => api.post('/superadmin/whitelabel/tenants', p),
  updateTenant:      (id: string, p: object)   => api.patch(`/superadmin/whitelabel/tenants/${id}`, p),
  suspendTenant:     (id: string)              => api.post(`/superadmin/whitelabel/tenants/${id}/suspend`),
  activateTenant:    (id: string)              => api.post(`/superadmin/whitelabel/tenants/${id}/activate`),
  deleteTenant:      (id: string)              => api.delete(`/superadmin/whitelabel/tenants/${id}`),
  tenantApiKeys:     (id: string)              => api.get(`/superadmin/whitelabel/tenants/${id}/api-keys`),
  rotateTenantKey:   (id: string)              => api.post(`/superadmin/whitelabel/tenants/${id}/api-keys/rotate`),
  tenantUsage:       (id: string)              => api.get(`/superadmin/whitelabel/tenants/${id}/usage`),

  // ── GDPR / Data Privacy ───────────────────────────────────────────────────
  gdprRequests:      (params?: Record<string, string>) => api.get('/superadmin/gdpr/requests', { params }),
  processGdprRequest: (reqId: string, action: 'approve' | 'reject', notes?: string) =>
    api.post(`/superadmin/gdpr/requests/${reqId}/process`, { action, notes }),
  gdprExportUser:    (userId: string)          => api.post(`/superadmin/gdpr/users/${userId}/export`),
  gdprEraseUser:     (userId: string, reason: string) =>
    api.post(`/superadmin/gdpr/users/${userId}/erase`, { reason }),
  consentLog:        (userId?: string)         => api.get('/superadmin/gdpr/consent-log', { params: userId ? { user_id: userId } : {} }),
  retentionPolicies: ()                        => api.get('/superadmin/gdpr/retention-policies'),
  updateRetentionPolicy: (p: object)           => api.patch('/superadmin/gdpr/retention-policies', p),

  // ── Nuclear Emergency Controls ────────────────────────────────────────────
  nuclearStatus:     ()                        => api.get('/superadmin/nuclear/status'),
  nuclearHalt:       (reason: string)          => api.post('/superadmin/nuclear/halt', { reason }),
  nuclearResume:     ()                        => api.post('/superadmin/nuclear/resume'),
  activateHedge:     (params: object)          => api.post('/superadmin/nuclear/hedge/activate', params),
  deactivateHedge:   ()                        => api.post('/superadmin/nuclear/hedge/deactivate'),
  maxRiskOverride:   (params: object)          => api.post('/superadmin/nuclear/risk-override', params),
  nuclearLog:        ()                        => api.get('/superadmin/nuclear/log'),

  // ── Rate Limiting ─────────────────────────────────────────────────────────
  rateLimitRules:    ()                        => api.get('/superadmin/rate-limits/rules'),
  updateRateLimitRule: (ruleId: string, p: object) =>
    api.patch(`/superadmin/rate-limits/rules/${ruleId}`, p),
  createRateLimitRule: (p: object)             => api.post('/superadmin/rate-limits/rules', p),
  deleteRateLimitRule: (ruleId: string)        => api.delete(`/superadmin/rate-limits/rules/${ruleId}`),
  rateLimitStats:    ()                        => api.get('/superadmin/rate-limits/stats'),
  rateLimitViolations: (params?: Record<string, string>) =>
    api.get('/superadmin/rate-limits/violations', { params }),

  // ── Alerting / Monitoring ─────────────────────────────────────────────────
  alertRules:        ()                        => api.get('/superadmin/alerting/rules'),
  createAlertRule:   (p: object)               => api.post('/superadmin/alerting/rules', p),
  updateAlertRule:   (ruleId: string, p: object) =>
    api.patch(`/superadmin/alerting/rules/${ruleId}`, p),
  deleteAlertRule:   (ruleId: string)          => api.delete(`/superadmin/alerting/rules/${ruleId}`),
  silenceAlert:      (ruleId: string, durationMin: number) =>
    api.post(`/superadmin/alerting/rules/${ruleId}/silence`, { duration_minutes: durationMin }),
  firedAlerts:       (params?: Record<string, string>) => api.get('/superadmin/alerting/fired', { params }),
  prometheusStatus:  ()                        => api.get('/superadmin/alerting/prometheus'),

  // ── Reporting ─────────────────────────────────────────────────────────────
  reportList:        ()                        => api.get('/superadmin/reports'),
  triggerReport:     (type: string, period: string) =>
    api.post('/superadmin/reports/generate', { type, period }),
  downloadReport:    (reportId: string)        => api.get(`/superadmin/reports/${reportId}/download`, { responseType: 'blob' }),
  deleteReport:      (reportId: string)        => api.delete(`/superadmin/reports/${reportId}`),

  // ── Security Infrastructure ───────────────────────────────────────────────
  selfHealerStatus:  ()                        => api.get('/superadmin/security-infra/self-healer'),
  triggerIntegrityScan: ()                     => api.post('/superadmin/security-infra/self-healer/scan'),

  // ── Autonomous Healing Engine ─────────────────────────────────────────────
  autoHealConfig:          ()                  => api.get('/superadmin/auto-healing/config'),
  autoHealSaveConfig:      (cfg: object)       => api.put('/superadmin/auto-healing/config', cfg),
  autoHealTestIndex:       ()                  => api.get('/superadmin/auto-healing/tests/index'),
  autoHealReindexTests:    ()                  => api.post('/superadmin/auto-healing/tests/reindex'),
  autoHealRunTests:        ()                  => api.post('/superadmin/auto-healing/tests/run'),
  autoHealRebuildBaseline: ()                  => api.post('/superadmin/auto-healing/baseline/rebuild'),
  autoHealStatus:          ()                  => api.get('/superadmin/auto-healing/status'),
  autoHealDrift:           (limit?: number)    => api.get('/superadmin/auto-healing/drift', { params: limit ? { limit } : {} }),
  autoHealPatches:         (limit?: number)    => api.get('/superadmin/auto-healing/patches', { params: limit ? { limit } : {} }),
  autoHealQuarantine:      ()                  => api.get('/superadmin/auto-healing/quarantine'),
  autoHealPendingApproval: ()                  => api.get('/superadmin/auto-healing/pending-approval'),
  autoHealApprovePatch:    (idx: number)       => api.post(`/superadmin/auto-healing/approve/${idx}`),
  antivirusStatus:   ()                        => api.get('/superadmin/security-infra/antivirus'),
  triggerAvScan:     (path?: string)           => api.post('/superadmin/security-infra/antivirus/scan', { path }),
  hsmStatus:         ()                        => api.get('/superadmin/security-infra/hsm'),
  hsmRotateKey:      (keyId: string)           => api.post(`/superadmin/security-infra/hsm/keys/${keyId}/rotate`),
  securityInfraLog:  ()                        => api.get('/superadmin/security-infra/log'),

  // ── System Health (services, backups, scheduled jobs) ────────────────────
  serviceStatuses:   ()                        => api.get('/superadmin/system/services'),
  backupList:        ()                        => api.get('/superadmin/system/backups'),
  triggerBackup:     (type: 'full' | 'incremental' | 'snapshot') =>
    api.post('/superadmin/system/backups/trigger', { type }),
  scheduledJobs:     ()                        => api.get('/superadmin/system/jobs'),
  triggerJob:        (jobId: string)           => api.post(`/superadmin/system/jobs/${jobId}/trigger`),
  pauseJob:          (jobId: string)           => api.post(`/superadmin/system/jobs/${jobId}/pause`),
  resumeJob:         (jobId: string)           => api.post(`/superadmin/system/jobs/${jobId}/resume`),
  apiKeyAudit:       (params?: Record<string, string>) => api.get('/superadmin/system/api-keys', { params }),
  revokeApiKey:      (keyId: string)           => api.delete(`/superadmin/system/api-keys/${keyId}`),
};
