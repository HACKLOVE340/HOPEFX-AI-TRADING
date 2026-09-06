/**
 * hooks/useApi.ts
 * Single axios instance with JWT injection, CSRF double-submit, and 401 auto-logout.
 * All API modules import from here. lib/api.ts re-exports this file.
 */

import axios, { type AxiosInstance } from 'axios';
import { useStore } from '../store';
import { getApiBase } from '../lib/utils';

// `?? '/api'` here resolved an empty VITE_API_URL to '' rather than '/api',
// which makes axios resolve every path against the page origin. See getApiBase.
const BASE_URL = getApiBase();

export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  // Send cookies on every request. The CSRF double-submit pattern requires the
  // `hopefx_csrf` cookie to accompany the X-CSRF-Token header on state-changing
  // requests; without this, cross-origin calls (e.g. Vite dev :5173 → API :8000)
  // drop the cookie and the server rejects them with "CSRF token missing".
  withCredentials: true,
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

  // If the server already set the cookie (e.g. from a previous session or a
  // server-side render), seed the in-memory cache from it immediately rather
  // than making an unnecessary network round-trip to /auth/csrf-token.
  if (cookieVal && !_csrfToken) {
    _csrfToken     = cookieVal;
    _csrfFetchedAt = Date.now();
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
  '/auth/activate-free-tier',          // post-registration setup, called before session cookie exists
  '/billing/auth/activate-free-tier',  // billing router alias — same semantics
  '/auth/refresh',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/verify-email',
  '/auth/resend-verification',
  '/email/webhook',
  '/health',
];

api.interceptors.request.use(async (config) => {
  // Use the in-memory Zustand token only — never localStorage.
  // Tokens are stored in httpOnly cookies; the access token is also kept in
  // Zustand memory so we can still send it as a Bearer header (works for
  // both XHR and non-browser API clients).  On page refresh the token will
  // be null until _silentRefresh() runs; the response interceptor handles
  // the 401 that results and retries transparently.
  const token = useStore.getState().token;
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
// When any request returns 401 we attempt one silent refresh.
// The httpOnly refresh-token cookie is sent automatically by the browser —
// no token needs to be read from localStorage or the request body.
// On success the new access token is stored in Zustand memory only.
// On failure the session is cleared and the user is sent to /login.

let _refreshPromise: Promise<string | null> | null = null;

// Bare axios calls in this function have no baseURL/timeout/interceptors of
// their own (see _fetchCsrfToken above for why: avoids the interceptor calling
// back into itself). Without an explicit timeout they use the browser's own
// default, which is effectively unbounded — a slow/hung network then hangs
// EVERY page load indefinitely instead of failing fast.
const _REFRESH_TIMEOUT_MS = 10_000;

/** True only for a DEFINITIVE auth rejection (refresh token invalid/expired/
 *  absent) — as opposed to a timeout/network/5xx, which says nothing about
 *  whether the session is actually valid. Exported for unit testing. */
export function _isDefiniteAuthRejection(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  return status === 401 || status === 403;
}

async function _refreshRequest(): Promise<string | null> {
  // Send with credentials so the browser includes the httpOnly
  // hopefx_refresh_token cookie scoped to /api/auth/refresh.
  const res = await axios.post(
    `${BASE_URL}/auth/refresh`,
    {},
    { withCredentials: true, timeout: _REFRESH_TIMEOUT_MS },
  );
  const { access_token } = res.data as { access_token: string };
  return access_token || null;
}

async function _silentRefresh(): Promise<string | null> {
  // Deduplicate: if a refresh is already in-flight, wait for it.
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    try {
      let access_token: string | null;
      try {
        access_token = await _refreshRequest();
      } catch (err) {
        if (_isDefiniteAuthRejection(err)) {
          // The refresh token itself was rejected — genuinely no session.
          return null;
        }
        // Transient failure (timeout / network blip / 5xx) says nothing about
        // whether the session is valid. Retry once after a short pause rather
        // than immediately treating a slow network the same as "not logged
        // in" — this was previously indistinguishable and would force-log-out
        // a user whose session was fine but whose network hiccuped.
        await new Promise((r) => setTimeout(r, 1500));
        try {
          access_token = await _refreshRequest();
        } catch {
          return null; // still failing after a retry — give up gracefully
        }
      }
      if (!access_token) return null;

      // Use persisted user from store; if missing, fetch from /me.
      let { user } = useStore.getState();
      if (!user) {
        try {
          const meRes = await axios.get(`${BASE_URL}/auth/me`, {
            headers: { Authorization: `Bearer ${access_token}` },
            timeout: _REFRESH_TIMEOUT_MS,
          });
          user = meRes.data as import('../store').User;
        } catch {
          // /me failed — can't restore session without user profile
          return null;
        }
      }
      // Store in Zustand memory only — never in localStorage.
      useStore.getState().setAuth(access_token, user);
      return access_token;
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
    const original = err.config as typeof err.config & { _retried?: boolean; _csrfRetried?: boolean };
    // Only attempt refresh on 401, once per request, and not for auth endpoints
    // themselves (login/refresh/logout) to avoid infinite loops.
    const isAuthEndpoint = original?.url?.includes('/auth/login') ||
                           original?.url?.includes('/auth/refresh') ||
                           original?.url?.includes('/auth/logout');

    // Self-heal stale/missing CSRF tokens: on a 403 whose detail mentions CSRF,
    // drop the cached token, fetch a fresh one, and retry the request once.
    const detail = (err?.response?.data?.detail ?? '') as string;
    if (err?.response?.status === 403 && /csrf/i.test(detail) && original && !original._csrfRetried) {
      original._csrfRetried = true;
      resetCsrfCache();
      const fresh = await _fetchCsrfToken();
      if (fresh) {
        original.headers = { ...original.headers, [CSRF_HEADER]: fresh };
        return api(original);
      }
    }

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
  // Login with automatic retry on 503 ("Auth service not initialised"). The
  // backend accepts requests as soon as it boots, but the auth service finishes
  // initialising a few seconds later (longer on slow machines / cold start), so
  // an early login can transiently 503. Retry for ~24s before giving up. Bad
  // credentials return 401 and are NOT retried. 60s per-attempt timeout covers
  // a slow first response.
  login: async (payload: LoginPayload) => {
    const maxAttempts = 12;
    let lastErr: unknown;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        return await api.post<LoginResponse>('/auth/login', payload, { timeout: 60_000 });
      } catch (err) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 503 && attempt < maxAttempts - 1) {
          lastErr = err;
          await new Promise((r) => setTimeout(r, 2000)); // auth still warming up
          continue;
        }
        throw err;
      }
    }
    throw lastErr;
  },
  // Cookies (access + refresh) are cleared server-side via Set-Cookie: max-age=0.
  // withCredentials ensures the browser sends the httpOnly refresh cookie.
  logout:   () => api.post('/auth/logout', {}, { withCredentials: true }),
  me:       ()                       => api.get<import('../store').User>('/auth/me'),
  /**
   * Restore an authenticated session on a cold page load / refresh.
   * The access token is never persisted, so after a reload the in-memory
   * token is null. This mints a fresh access token from the httpOnly refresh
   * cookie and writes it (plus the user) into the store, returning the new
   * token or null if no valid session exists.
   */
  restoreSession: (): Promise<string | null> => _silentRefresh(),
  register: (payload: { email: string; username: string; password: string }) =>
    api.post('/auth/register', payload),
  /** Grants the new-user trial. The account comes from the bearer token — call
   *  this only after setAuth(), and never pass a user id. */
  activateFreeTier: (refCode?: string) =>
    api.post('/auth/activate-free-tier', { ref_code: refCode }),
  /** Request a password reset email. Always returns 200 (prevents enumeration). */
  forgotPassword: (email: string) =>
    api.post('/auth/forgot-password', { email }),
  /** Set a new password using the token from the reset email. */
  resetPassword: (token: string, new_password: string) =>
    api.post('/auth/reset-password', { token, new_password }),
};

// ── Trading ───────────────────────────────────────────────────────────────────

export interface SymbolSpec {
  symbol: string;
  description: string;
  category: string;
  pip_size: number;
  lot_size: number;
  min_lot: number;
  max_lot: number;
  margin_rate: number;
}

export const tradingApi = {
  positions:      ()              => api.get('/trading/positions'),
  /** Instrument catalogue — the server's pip and contract sizes (F5-01). */
  symbols:        ()              => api.get<SymbolSpec[]>('/trading/symbols'),
  signals:        ()              => api.get('/trading/signals'),
  account:        ()              => api.get('/trading/account'),
  prices:         ()              => api.get<Record<string, { bid: number; ask: number; last: number; timestamp: number }>>('/trading/prices'),
  // OHLCV may fetch from yfinance — allow up to 30s before giving up
  ohlcv:          (symbol: string, timeframe = '1h', limit = 200) =>
    api.get(`/trading/ohlcv/${encodeURIComponent(symbol)}`, { params: { timeframe, limit }, timeout: 30_000 }),
  placeOrder:     (order: object) => api.post('/trading/orders', order),
  closePosition:  (id: string)    => api.delete(`/trading/positions/${id}`),
  closeAllPositions: ()           => api.delete('/trading/positions'),
  orders:         (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get('/trading/orders', { params }),
  trades:         (params?: { symbol?: string; limit?: number } | number) => {
    const limit  = typeof params === 'number' ? params : (params?.limit ?? 100);
    const symbol = typeof params === 'object' ? params?.symbol : undefined;
    return api.get('/trading/trades', { params: { limit, ...(symbol ? { symbol } : {}) } });
  },
  regime:         (symbol?: string) => api.get('/trading/regime', { params: symbol ? { symbol } : {} }),
  brainState:     ()              => api.get('/trading/brain-state'),
  emergencyStop:  ()              => api.post('/trading/emergency-stop'),
  // AI analysis involves regime detection + signal lookup — allow up to 30s
  aiAnalysis:     (payload: { symbol: string; price?: number; timeframe?: string }) =>
    api.post('/trading/ai-analysis', payload, { timeout: 30_000 }),
  riskMetrics:    ()              => api.get('/trading/risk'),
  patterns: (symbol: string, timeframe = '1h', limit = 200, minConfidence = 0.5) =>
    api.get('/trading/patterns', { params: { symbol, timeframe, limit, min_confidence: minConfidence }, timeout: 30_000 }),
};

// ── Backtesting ───────────────────────────────────────────────────────────────

export const backtestApi = {
  run:     (params: object) => api.post('/backtesting/run', params),
  results: (id: string)     => api.get(`/backtesting/results/${id}`),
  list:    ()               => api.get('/backtesting/list'),
};

// ── ML ────────────────────────────────────────────────────────────────────────

export const mlApi = {
  // ML predict loads OHLCV + runs inference — allow up to 30s
  predict:  (symbol: string, payload?: object) => api.post(`/ml/predict/${encodeURIComponent(symbol)}`, payload ?? {}, { timeout: 30_000 }),
  accuracy: ()               => api.get('/ml/accuracy'),
  models:   ()               => api.get('/ml/models'),
  features: ()               => api.get('/ml/features'),
  // Inference health + safety gates (staleness, drift, fallback rate, calibration).
  health:   ()               => api.get('/ml/health'),
  /** Live engine state: model version, feature count, OOS accuracy, last trained. */
  engineHealth: ()           => api.get('/ml/engine-health'),
  /** Built-in feature importances for a deployed MODEL (not a symbol).
   *  The response's `method` says how they were derived — "uniform" means the
   *  server measured nothing and returned 1/n per feature. See audit F232. */
  featureImportance: (modelName: string, topN = 30) =>
    api.get(`/ml/feature-importance/${encodeURIComponent(modelName)}`, { params: { top_n: topN } }),
  /** Feature-drift report; explains itself in `message` when it lacks samples. */
  driftReport: ()            => api.get('/ml/drift-report'),
};

// ── AI Core ───────────────────────────────────────────────────────────────────
//
// The read surface behind /ai-core (api/ai_core.py). Every call is a GET: the
// consequential actions live in /api/safe-platform behind the Part 1B matrix
// and 2FA, and a second, weaker door to them is not something the page needs.
//
// `budget` and `calls` return a WIDER body for a superadmin (per-operator
// spend, every operator's calls) and a self-scoped one for an admin. The page
// reads `scope` rather than the caller's role, so what it renders is what the
// server actually returned.

export const aiCoreApi = {
  /** One request for the header — chain, reachability, spend and call counts. */
  summary:      ()               => api.get('/ai-core/summary'),
  /** What this caller may do, as the server would decide it. */
  capabilities: ()               => api.get('/ai-core/capabilities'),
  /** The resolved chain per role, and which legs hold credentials. */
  chain:        ()               => api.get('/ai-core/chain'),
  /** Spend against the ceilings; scope depends on role. */
  budget:       ()               => api.get('/ai-core/budget'),
  /** Recent model calls. Prompts are SHA-256 digests, never text. */
  calls:        (limit = 50)     => api.get('/ai-core/calls', { params: { limit } }),
  /** Response-cache stats, or an explicit "not installed". */
  cache:        ()               => api.get('/ai-core/cache'),
  /** The latest eval report and what the promotion gate would do with it. */
  evals:        ()               => api.get('/ai-core/evals'),
  /** Which models each vendor currently serves. `provider` narrows it to one. */
  models:       (provider?: string) =>
    api.get('/ai-core/models', provider ? { params: { provider } } : undefined),
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
  list:    (period?: string) => api.get('/leaderboard', { params: period ? { period } : {} }),
  profile: (traderId: string) => api.get(`/leaderboard/${traderId}`),
  stats:   (traderId: string) => api.get(`/leaderboard/${traderId}/stats`),
};

// ── Performance ───────────────────────────────────────────────────────────────

export const performanceApi = {
  summary:     ()  => api.get('/performance/public'),
  // /api/trading/performance/summary is the authoritative endpoint
  tradingSummary: () => api.get('/trading/performance/summary'),
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
// Backend: /api/signals/* (api/signals.py — create_signals_router)

export const signalsApi = {
  active:       ()                   => api.get('/signals/active'),
  latest:       ()                   => api.get('/signals/latest'),
  history:      (limit = 50)         => api.get('/signals/history', { params: { limit } }),
  summary:      ()                   => api.get('/signals/summary'),
  analytics:    ()                   => api.get('/signals/analytics'),
  generate:     (payload: object)    => api.post('/signals/generate', payload),
  setAlert:     (payload: object)    => api.post('/signals/alerts', payload),
  alerts:       ()                   => api.get('/signals/alerts'),
  deleteAlert:  (alertId: string)    => api.delete(`/signals/alerts/${alertId}`),
  engine:       ()                   => api.get('/signals/engine'),
  /** Alias for engine() — returns signal engine status. */
  status:       ()                   => api.get('/signals/engine'),
  channels:     ()                   => api.get('/signals/channels'),
  filterStats:  ()                   => api.get('/ml/signal-filter/stats'),
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
  platformConfig:       ()                     => api.get('/superadmin/platform/config'),
  updatePlatformConfig: (p: object)            => api.patch('/superadmin/platform/config', p),
  savePlatformConfigFull: (p: object)          => api.put('/superadmin/platform/config/full', p),
  validatePlatformConfig: ()                   => api.get('/superadmin/platform/config/validate'),
  testSmtpConfig:    (p?: object)              => api.post('/superadmin/platform/test-smtp', p ?? {}),
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

  // Refund policy — where a creator's money comes from when a settled sale is
  // refunded. See monetization/refund_policy.py for what each option means.
  refundPolicy:      ()                        => api.get('/superadmin/financial/refund-policy'),
  setRefundPolicy:   (policy: string)          => api.put('/superadmin/financial/refund-policy', { policy }),

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

  // ── System Reliability & Connectivity ────────────────────────────────────
  reliabilityStatus:    ()                     => api.get('/superadmin/reliability/status'),
  reliabilityComponents: ()                    => api.get('/superadmin/reliability/components'),
  reliabilityProbe:     (component: string)    => api.post('/superadmin/reliability/probe', { component }),
  reliabilityTraces:    (limit?: number)       => api.get('/superadmin/reliability/traces', { params: limit ? { limit } : {} }),
  reliabilityTraceTest: ()                     => api.post('/superadmin/reliability/trace/test'),
  reliabilityValidate:  (key: string)          => api.get(`/superadmin/reliability/validate/${key}`),
  reliabilityEnv:       ()                     => api.get('/superadmin/reliability/env'),
  reliabilityRoutes:    ()                     => api.get('/superadmin/reliability/routes'),
  reliabilitySelfTest:  ()                     => api.post('/superadmin/reliability/self-test'),
  reliabilityMetrics:   ()                     => api.get('/superadmin/reliability/metrics'),
  reliabilityValidateToggle: (key: string, expectedValue: unknown) =>
    api.post('/superadmin/reliability/validate-toggle', { key, expected_value: expectedValue }),
  reliabilityHistory:       (limit?: number)       => api.get('/superadmin/reliability/history', { params: limit ? { limit } : {} }),
  reliabilityHistoryRecord: ()                     => api.post('/superadmin/reliability/history/record'),

  // ── Diagnostics ───────────────────────────────────────────────────────────
  diagnosticsRun:       ()                     => api.post('/superadmin/diagnostics/run'),
  diagnosticsReport:    ()                     => api.get('/superadmin/diagnostics/report'),
  diagnosticsResults:   (params?: Record<string, string>) => api.get('/superadmin/diagnostics/results', { params }),
  diagnosticsRemediate: ()                     => api.post('/superadmin/diagnostics/remediate'),
  diagnosticsChecks:    ()                     => api.get('/superadmin/diagnostics/checks'),
  diagnosticsRunCheck:  (name: string)         => api.post(`/superadmin/diagnostics/checks/${name}/run`),
  diagnosticsSummary:   ()                     => api.get('/superadmin/diagnostics/summary'),

  // ── Health Engine (auto-discovering) ─────────────────────────────────────
  healthEngineStatus:      ()                  => api.get('/superadmin/health-engine/status'),
  healthEngineProbes:      ()                  => api.get('/superadmin/health-engine/probes'),
  healthEngineRunProbe:    (name: string)      => api.post(`/superadmin/health-engine/probe/${name}`),
  healthEngineRun:         (probes?: string[]) => api.post('/superadmin/health-engine/run', { probes: probes ?? [] }),
  healthEngineHistory:     (limit?: number)    => api.get('/superadmin/health-engine/history', { params: limit ? { limit } : {} }),
  healthEngineRegister:    (body: object)      => api.post('/superadmin/health-engine/register', body),

  // ── ML extended (superadmin) ──────────────────────────────────────────────
  mlFilterStats:           ()                  => api.get('/ml/signal-filter/stats'),
  mlOnlineLearnerStatus:   ()                  => api.get('/online-learner/status'),
  mlDriftStatus:           ()                  => api.get('/ml/drift/status'),
  mlSharpeCircuitBreaker:  ()                  => api.get('/ml/sharpe-circuit-breaker/status'),

  // ── Diagnostics remediation log ───────────────────────────────────────────
  diagnosticsRemediationLog: (limit?: number)  => api.get('/superadmin/diagnostics/remediation-log', { params: limit ? { limit } : {} }),

  // ── Infrastructure extended ───────────────────────────────────────────────
  infraScheduledJobs:  ()                      => api.get('/superadmin/system/jobs'),
  infraBackups:        ()                      => api.get('/superadmin/system/backups'),
  infraTriggerBackup:  (type?: string)         => api.post('/superadmin/system/backups/trigger', { type: type ?? 'incremental' }),
  infraApiKeys:        ()                      => api.get('/superadmin/system/api-keys'),
  infraRevokeApiKey:   (keyId: string, reason?: string) => api.delete(`/superadmin/system/api-keys/${keyId}`, { data: { reason } }),
};

// ── Research ──────────────────────────────────────────────────────────────────

export const researchApi = {
  listNotebooks:  ()                           => api.get('/research/notebooks'),
  createNotebook: (body: object)               => api.post('/research/notebooks', body),
  getNotebook:    (id: string)                 => api.get(`/research/notebooks/${id}`),
  runNotebook:    (id: string)                 => api.post(`/research/notebooks/${id}/run`, {}),
  deleteNotebook: (id: string)                 => api.delete(`/research/notebooks/${id}`),
  getTemplates:   ()                           => api.get('/research/templates'),
};

// ── Teams ─────────────────────────────────────────────────────────────────────

export const teamsApi = {
  list:           ()                           => api.get('/teams'),
  create:         (body: object)               => api.post('/teams', body),
  get:            (id: string)                 => api.get(`/teams/${id}`),
  getPerformance: (id: string)                 => api.get(`/teams/${id}/performance`),
  invite:         (id: string, body: object)   => api.post(`/teams/${id}/members`, body),
  removeMember:   (id: string, uid: string)    => api.delete(`/teams/${id}/members/${uid}`),
  updateMember:   (id: string, uid: string, body: object) => api.patch(`/teams/${id}/members/${uid}`, body),
  delete:         (id: string)                 => api.delete(`/teams/${id}`),
};

// ── Replay ────────────────────────────────────────────────────────────────────

export const replayApi = {
  listSessions:   ()                           => api.get('/replay/sessions'),
  createSession:  (body: object)               => api.post('/replay/sessions', body),
  getSession:     (id: string)                 => api.get(`/replay/sessions/${id}`),
  stepSession:    (id: string)                 => api.post(`/replay/sessions/${id}/step`, {}),
  runSession:     (id: string, bars: number)   => api.post(`/replay/sessions/${id}/run`, { bars }),
  deleteSession:  (id: string)                 => api.delete(`/replay/sessions/${id}`),
};

// ── Whitelabel ────────────────────────────────────────────────────────────────

export const whitelabelApi = {
  listTenants:    (statusFilter?: string)      => api.get('/whitelabel/tenants', { params: statusFilter ? { status_filter: statusFilter } : {} }),
  createTenant:   (body: object)               => api.post('/whitelabel/tenants', body),
  getTenant:      (id: string)                 => api.get(`/whitelabel/tenants/${id}`),
  updateTenant:   (id: string, body: object)   => api.patch(`/whitelabel/tenants/${id}`, body),
  activateTenant: (id: string)                 => api.post(`/whitelabel/tenants/${id}/activate`),
  suspendTenant:  (id: string)                 => api.post(`/whitelabel/tenants/${id}/suspend`),
  deleteTenant:   (id: string)                 => api.delete(`/whitelabel/tenants/${id}`),
  enableFeature:  (id: string, feature: string) => api.post(`/whitelabel/tenants/${id}/features/${feature}`),
  disableFeature: (id: string, feature: string) => api.delete(`/whitelabel/tenants/${id}/features/${feature}`),
  generateApiKey: (id: string)                 => api.post(`/whitelabel/tenants/${id}/api-key`),
  previewTenant:  (id: string)                 => api.get(`/whitelabel/tenants/${id}/preview`),
  listFeatures:   ()                           => api.get('/whitelabel/features'),
};

// ── Explainability ────────────────────────────────────────────────────────────

export const explainabilityApi = {
  explain:        (symbol: string, params?: object) => api.post(`/explain/${encodeURIComponent(symbol)}`, params ?? {}),
  featureImportance: (symbol: string)          => api.get(`/explain/${encodeURIComponent(symbol)}`),
  shapValues:     (symbol: string)             => api.get(`/explain/${encodeURIComponent(symbol)}`),
  history:        (limit = 20)                 => api.get('/explain/latest', { params: { limit } }),
};

// ── No-Code Strategy Builder ──────────────────────────────────────────────────

// Backend: api/nocode.py (prefix /api/nocode) — template-driven no-code builder.
// The previous /nocode/strategies|blocks paths never existed in the backend.
export const nocodeApi = {
  templates:  (category?: string)    => api.get('/nocode/templates', { params: category ? { category } : {} }),
  nodeTypes:  ()                     => api.get('/nocode/node-types'),
  validate:   (body: { nodes: unknown[]; edges?: unknown[] }) => api.post('/nocode/validate', body),
  deploy:     (body: { template_id: string; parameters?: object; symbol?: string; timeframe?: string }) =>
                api.post('/nocode/deploy', body),
};

// ── Execution Transparency ────────────────────────────────────────────────────

// Backend: api/transparency.py (prefix /api/transparency). The previous paths
// (orders/{id}, best-execution, slippage, venues, summary) did not exist.
export const transparencyApi = {
  decisions: (params?: object)        => api.get('/transparency/decisions', { params }),
  explain:   (tradeId: string)        => api.get(`/transparency/explain/${tradeId}`),
  auditLog:  (params?: object)        => api.get('/transparency/audit-log', { params }),
  stats:     ()                       => api.get('/transparency/stats'),
};

// ── ML-Ops (roadmap) ─────────────────────────────────────────────────────────
// Backend: api/ml_ops.py (prefix /api/mlops)
export const mlOpsApi = {
  health:        ()                  => api.get('/mlops/health'),
  drift:         ()                  => api.get('/mlops/drift'),
  shadow:        ()                  => api.get('/mlops/shadow'),
  retrainHistory:()                  => api.get('/mlops/retrain/history'),
  modelMetrics:  (versionId: string) => api.get(`/mlops/models/${versionId}/metrics`),
  triggerRetrain:(reason = 'manual') => api.post('/mlops/retrain', { reason }),
  promote:       (versionId: string) => api.post(`/mlops/promote/${versionId}`),
};

// ── Observability (roadmap) ─────────────────────────────────────────────────
// Backend: api/observability.py (prefix /api/observability)
export const observabilityApi = {
  metrics:   (period = '1h')        => api.get('/observability/metrics', { params: { period } }),
  services:  ()                     => api.get('/observability/services'),
  alerts:    (severity?: string)    => api.get('/observability/alerts', { params: severity ? { severity } : {} }),
  traces:    (limit = 50)           => api.get('/observability/traces', { params: { limit } }),
  latency:   (period = '1h')        => api.get('/observability/latency-histogram', { params: { period } }),
};

// ── AI Brain ──────────────────────────────────────────────────────────────────

export const brainApi = {
  generateStrategy: (payload: object)          => api.post('/brain/generate-strategy', payload, { timeout: 180_000 }),
  deployStrategy:   (payload: object)          => api.post('/brain/deploy-strategy', payload),
};

// ── Macro Data ────────────────────────────────────────────────────────────────

export const macroApi = {
  snapshot:     ()              => api.get('/macro/snapshot'),
  refresh:      ()              => api.get('/macro/refresh'),
  features:     ()              => api.get('/macro/features'),
  store:        ()              => api.get('/macro/store'),
  storeUpdate:  (body: object)  => api.post('/macro/store/update', body),
  wgc:          ()              => api.get('/macro/wgc'),
  wgcRefresh:   ()              => api.post('/macro/wgc/refresh', {}),
  wgcHealth:    ()              => api.get('/macro/wgc/health'),
};

// ── Online Learner ────────────────────────────────────────────────────────────

export const onlineLearnerApi = {
  status:       (symbol?: string)              => api.get('/online-learner/status', { params: symbol ? { symbol } : {} }),
  partialFit:   (payload: object)              => api.post('/online-learner/partial-fit', payload),
  diagnostics:  (symbol?: string)              => api.get('/online-learner/diagnostics', { params: symbol ? { symbol } : {} }),
  reset:        (payload: object)              => api.post('/online-learner/reset', payload),
};

// ── Prop Firm ─────────────────────────────────────────────────────────────────

export const propFirmApi = {
  status:       ()              => api.get('/risk/prop-firm-status'),
};

// ── TCA (Transaction Cost Analysis) ──────────────────────────────────────────

export const tcaApi = {
  report:       (params?: object)              => api.get('/tca/report', { params }),
  reports:      (n?: number)                   => api.get('/tca/report', { params: n ? { last_n: n } : {} }),
  brokerReport: (broker: string)               => api.get(`/tca/report/${broker}`),
  records:      (n?: number)                   => api.get('/tca/records', { params: n ? { n } : {} }),
  alerts:       ()                             => api.get('/tca/alerts'),
  stats:        (n?: number)                   => api.get('/tca/stats', { params: n ? { n } : {} }),
  flushRecords: ()                             => api.delete('/tca/records'),
  flush:        ()                             => api.delete('/tca/records'),
};

// ── Regime ────────────────────────────────────────────────────────────────────

export const regimeApi = {
  current:      (symbol?: string)              => api.get('/trading/regime', { params: symbol ? { symbol } : {} }),
  history:      (limit = 50)                   => api.get('/trading/regime/history', { params: { limit } }),
};

// ── Position Sizing ───────────────────────────────────────────────────────────

export const positionSizingApi = {
  calculate:    (payload: object)              => api.post('/trading/position-size', payload),
  riskMetrics:  ()                             => api.get('/trading/risk'),
};

// ── Drawdown ──────────────────────────────────────────────────────────────────

export const drawdownApi = {
  curve:        (params?: object)              => api.get('/pnl/drawdown-curve', { params }),
  stats:        ()                             => api.get('/trading/risk'),
  superadmin:   ()                             => api.get('/superadmin/risk/drawdown'),
};

// ── Backtest Extended ─────────────────────────────────────────────────────────

export const backtestExtApi = {
  strategies:       ()                         => api.get('/backtesting/strategies'),
  run:              (params: object)           => api.post('/backtesting/run', params),
  results:          (params?: object)          => api.get('/backtesting/results', { params }),
  getResult:        (id: string)               => api.get(`/backtesting/results/${id}`),
  list:             ()                         => api.get('/backtesting/list'),
  walkForwardList:  ()                         => api.get('/backtesting/walk-forward'),
  walkForwardLatest: ()                        => api.get('/backtesting/walk-forward/latest'),
  walkForwardGet:   (id: string)               => api.get(`/backtesting/walk-forward/${id}`),
  walkForwardRun:   (params: object)           => api.post('/backtesting/walk-forward/run', params),
  // These start a background job and return { run_id, status: 'running' }
  // immediately — no long-held request. Poll replayResult(run_id) for completion.
  replayRun:        (params: object)           => api.post('/backtesting/replay/run', params),
  replayStress:     (params: object)           => api.post('/backtesting/replay/stress', params),
  replayResult:     (runId: string)            => api.get(`/backtesting/results/${runId}`),
  replayRegimes:    ()                         => api.get('/backtesting/replay/regimes'),
};

// ── Anomaly Detection ─────────────────────────────────────────────────────────
// Anomaly detection is configured via platform config; ML status via /ml/health

export const anomalyApi = {
  status:       ()              => api.get('/ml/health'),
  /** Anomaly alerts are surfaced via signal analytics — same endpoint as signalsApi.analytics */
  alerts:       (params?: object) => api.get('/signals/analytics', { params }),
  retrain:      (payload?: object) => api.post('/ml/retrain', payload ?? {}),
  /** Dedicated anomaly detection status from the ML anomaly router */
  anomalyStatus: ()             => api.get('/ml/anomaly/status'),
};

// ── Allocator ─────────────────────────────────────────────────────────────────
// Portfolio allocator is configured via platform config; status via /portfolio

export const allocatorApi = {
  status:       ()              => api.get('/portfolio/summary'),
  weights:      ()              => api.get('/portfolio/positions'),
  rebalance:    (payload?: object) => api.post('/trading/orders', payload ?? {}),
  history:      (limit = 50)   => api.get('/performance/equity-curve', { params: { limit } }),
};

// ── Pricing catalogue (public — no auth required) ─────────────────────────────

export const pricingApi = {
  /** Full 5-tier plan catalogue with feature matrix. */
  getPlans:      (billingCycle: 'monthly' | 'annual' = 'monthly') =>
    api.get('/pricing/plans', { params: { billing_cycle: billingCycle } }),
  /** Side-by-side feature comparison between two tiers. */
  compare:       (tierA: string, tierB: string) =>
    api.get('/pricing/compare', { params: { tier_a: tierA, tier_b: tierB } }),
  /** Ordered upgrade options from the user's current tier. */
  upgradePath:   (currentTier: string) =>
    api.get('/pricing/upgrade-path', { params: { current_tier: currentTier } }),
  /** Pricing FAQ entries. */
  getFaq:        () => api.get('/pricing/faq'),
  /** Estimate monthly cost for a tier + trade volume. */
  estimate:      (body: { tier: string; billing_cycle?: string; trade_volume_usd?: number }) =>
    api.post('/pricing/estimate', body),
};

// ── Tutorials / Academy ───────────────────────────────────────────────────────

export const tutorialsApi = {
  /** Full episode catalogue with per-episode lock flags for the caller's plan. */
  list: () => api.get('/tutorials'),
  /** One episode; returns video_url only if the caller's plan grants access (else 403). */
  get:  (episode: number) => api.get(`/tutorials/${episode}`),
};

// ── LLM / AI Provider ─────────────────────────────────────────────────────────

export const llmApi = {
  health:       ()              => api.get('/brain/health'),
  complete:     (payload: object) => api.post('/brain/complete', payload, { timeout: 120_000 }),
  embed:        (payload: object) => api.post('/brain/embed', payload, { timeout: 60_000 }),
};

// ── Signal Engine ─────────────────────────────────────────────────────────────
// Alias for signalsApi — kept for backward compatibility with existing consumers.
// New code should import signalsApi directly.

export const signalEngineApi = signalsApi;

// ── Elite Tier 5 ──────────────────────────────────────────────────────────────
// All endpoints require an active Elite subscription (or admin/superadmin role).
// Backend: /api/billing/elite/*

export interface SupportTicketPayload {
  subject: string;
  message: string;
  priority: 'normal' | 'high' | 'urgent';
  category: 'general' | 'technical' | 'billing' | 'strategy' | 'api' | 'onboarding';
}

export interface CustomDevPayload {
  title: string;
  description: string;
  request_type: 'strategy' | 'indicator' | 'integration' | 'dashboard' | 'api' | 'other';
  target_symbols: string[];
  target_timeframes: string[];
  budget_usd?: number;
  deadline?: string;
}

export const eliteApi = {
  /** Dedicated account manager contact details. */
  accountManager:    () =>
    api.get('/billing/elite/account-manager'),

  /** Submit a dedicated support ticket. */
  createTicket:      (payload: SupportTicketPayload) =>
    api.post('/billing/elite/support/ticket', payload),

  /** List all support tickets for the authenticated user. */
  listTickets:       (limit = 50, offset = 0) =>
    api.get('/billing/elite/support/tickets', { params: { limit, offset } }),

  /** Submit a custom development request. */
  submitCustomDev:   (payload: CustomDevPayload) =>
    api.post('/billing/elite/custom-dev/request', payload),

  /** List all custom development requests for the authenticated user. */
  listCustomDevReqs: (limit = 50, offset = 0) =>
    api.get('/billing/elite/custom-dev/requests', { params: { limit, offset } }),

  /** Ticket event timeline for drill-down. */
  ticketTimeline:    (ticketId: string) =>
    api.get(`/billing/elite/support/tickets/${ticketId}/timeline`),
};

// ── Geopolitical Intelligence ──────────────────────────────────────────────────
// Backend: /api/news/* (news/__init__.py — inline FastAPI router)

export const geopoliticalApi = {
  signal:       ()                     => api.get('/news/geopolitical/signal'),
  events:       (forceRefresh = false) => api.get('/news/geopolitical/events', { params: { force_refresh: forceRefresh } }),
  assessment:   ()                     => api.get('/news/geopolitical/assessment'),
  worldMonitor: ()                     => api.get('/news/geopolitical/world-monitor'),
  newsSentiment:(symbol: string)       => api.get(`/news/sentiment/${encodeURIComponent(symbol)}`),
};

// ── Watchlist ─────────────────────────────────────────────────────────────────
// Backend: /api/watchlist/* (api/watchlist.py)

export const watchlistApi = {
  list:    ()                        => api.get('/watchlist'),
  add:     (symbol: string)          => api.post(`/watchlist/${encodeURIComponent(symbol)}`),
  remove:  (symbol: string)          => api.delete(`/watchlist/${encodeURIComponent(symbol)}`),
  prices:  ()                        => api.get('/watchlist/prices'),
  reorder: (symbols: string[])       => api.patch('/watchlist/order', { symbols }),
};

// ── Strategy Marketplace ──────────────────────────────────────────────────────
// Backend: /api/monetization/marketplace/* (api/monetization.py)

export const marketplaceApi = {
  strategies:    (params?: Record<string, unknown>)  => api.get('/monetization/marketplace/strategies', { params }),
  strategy:      (id: string)                        => api.get(`/monetization/marketplace/strategies/${encodeURIComponent(id)}`),
  purchase:      (payload: object)                   => api.post('/monetization/marketplace/purchase', payload),
  featured:      ()                                  => api.get('/monetization/marketplace/featured'),
  stats:         ()                                  => api.get('/monetization/marketplace/stats'),
  list:          (payload: object)                   => api.post('/monetization/marketplace/list', payload),
  myStrategies:  (userId: string)                    => api.get(`/monetization/marketplace/strategies?creator_id=${userId}`),
  review:        (strategyId: string, payload: object) => api.post(`/monetization/marketplace/strategies/${encodeURIComponent(strategyId)}/reviews`, payload),
  reviews:       (strategyId: string)                => api.get(`/monetization/marketplace/strategies/${encodeURIComponent(strategyId)}/reviews`),
  unsubscribe:   (strategyId: string)                => api.delete(`/monetization/marketplace/subscriptions/${encodeURIComponent(strategyId)}`),
  mySubscriptions: ()                                => api.get('/monetization/marketplace/subscriptions'),
};

// ── Security Auto-Healing Dashboard ──────────────────────────────────────────
// Backend: /api/security/* (api/security_dashboard.py)

export const securityHealingApi = {
  attacks:         ()               => api.get('/security/attacks'),
  alerts:          ()               => api.get('/security/alerts'),
  lockdownStatus:  ()               => api.get('/security/lockdown'),
  blockedIps:      ()               => api.get('/security/blocked-ips'),
  healStatus:      ()               => api.get('/security/heal/status'),
  drift:           ()               => api.get('/security/heal/drift'),
  patches:         ()               => api.get('/security/heal/patches'),
  scanNow:         ()               => api.post('/security/heal/scan/now'),
  rebuildBaseline: ()               => api.post('/security/heal/baseline/rebuild'),
  avStatus:        ()               => api.get('/security/av/status'),
  avThreats:       ()               => api.get('/security/av/threats'),
  avScan:          (payload = {})   => api.post('/security/av/scan', payload),
  avQuarantine:    (payload = {})   => api.post('/security/av/quarantine', payload),
};

// ── Security Fix Approval Queue ───────────────────────────────────────────────
// Backend: /api/security/fixes/* (api/security/fixes.py)

export const securityFixesApi = {
  list:       (params?: Record<string, unknown>) => api.get('/security/fixes', { params }),
  approved:   (params?: Record<string, unknown>) => api.get('/security/fixes/approved', { params }),
  declined:   (params?: Record<string, unknown>) => api.get('/security/fixes/declined', { params }),
  stats:      ()                                 => api.get('/security/fixes/stats'),
  approve:    (fixId: string, notes?: string)    => api.post('/security/fixes/approve', { fix_id: fixId, notes }),
  decline:    (fixId: string, reason?: string)   => api.post('/security/fixes/decline', { fix_id: fixId, reason }),
  scan:       ()                                 => api.post('/security/fixes/scan'),
};

// ── Affiliate API ─────────────────────────────────────────────────────────────
// Backend: /api/monetization/affiliate/*

export const affiliateApi = {
  account:          (userId: string)                          => api.get(`/monetization/affiliate/${userId}`),
  signup:           (payload: Record<string, unknown>)        => api.post('/monetization/affiliate/signup', payload),
  referrals:        (affiliateId: string, params?: Record<string, unknown>) =>
                      api.get(`/monetization/affiliate/${affiliateId}/referrals`, { params }),
  leaderboard:      (params?: Record<string, unknown>)        => api.get('/monetization/affiliate/leaderboard', { params }),
  withdraw:         (affiliateId: string, amount: number)     =>
                      api.post(`/monetization/affiliate/${affiliateId}/withdraw`, { amount }),
  commissions:      (affiliateId: string, params?: Record<string, unknown>) =>
                      api.get(`/monetization/affiliate/${affiliateId}/commissions`, { params }),
  updatePayment:    (affiliateId: string, payload: Record<string, unknown>) =>
                      api.patch(`/monetization/affiliate/${affiliateId}/payment-method`, payload),
};

// ── Social / Signal Feed API ──────────────────────────────────────────────────
// Backend: /api/feed/* (signal feed), /api/copy/* (copy trading), /api/profiles/* (profiles)
// Note: frontend historically used /api/social/* — all calls now route to correct backend paths.

export const socialApi = {
  feed:             (params?: Record<string, unknown>)        => api.get('/feed', { params }),
  react:            (signalId: string, reaction: 'up' | 'down') =>
                      api.post(`/feed/${signalId}/react`, { reaction }),
  comments:         (signalId: string)                        => api.get(`/feed/${signalId}/comments`),
  addComment:       (signalId: string, text: string)          =>
                      api.post(`/feed/${signalId}/comment`, { text }),
  optIn:            ()                                        => api.post('/feed/opt-in'),
  optOut:           ()                                        => api.post('/feed/opt-out'),
  optStatus:        ()                                        => api.get('/feed/status/me'),
  copyTrader:       (traderId: string, payload: Record<string, unknown>) =>
                      api.post(`/copy/${traderId}`, payload),
  stopCopy:         (traderId: string)                        => api.delete(`/copy/${traderId}`),
  activeCopies:     ()                                        => api.get('/copy/active'),
  updateAllocation: (traderId: string, amount: number)        =>
                      api.patch(`/copy/${traderId}/allocation`, { allocation_amount: amount }),
  profile:          (traderId: string)                        => api.get(`/profiles/${traderId}`),
  follow:           (traderId: string)                        => api.post(`/profiles/${traderId}/follow`),
  unfollow:         (traderId: string)                        => api.delete(`/profiles/${traderId}/follow`),
};

// ── Notifications API ─────────────────────────────────────────────────────────
// Backend: /api/notifications/*

export const notificationsApi = {
  list:             (params?: Record<string, unknown>)        => api.get('/notifications', { params }),
  unreadCount:      ()                                        => api.get('/notifications/unread-count'),
  markRead:         (notifId: string)                         => api.patch(`/notifications/${notifId}/read`),
  markAllRead:      ()                                        => api.post('/notifications/mark-all-read'),
  delete:           (notifId: string)                         => api.delete(`/notifications/${notifId}`),
  preferences:      ()                                        => api.get('/notifications/preferences'),
  updatePrefs:      (payload: Record<string, unknown>)        => api.patch('/notifications/preferences', payload),
  subscribe:        (payload: Record<string, unknown>)        => api.post('/notifications/subscribe', payload),
};

// ── Profile API ───────────────────────────────────────────────────────────────
// Backend: /api/profiles/* (note plural — matches router prefix)

export const profileApi = {
  get:              (userId?: string)                         =>
                      api.get(userId ? `/profiles/${userId}` : '/profiles/me'),
  update:           (payload: Record<string, unknown>)        => api.put('/profiles/me', payload),
  uploadAvatar:     (formData: FormData)                      =>
                      api.post('/profiles/me/avatar', formData, {
                        headers: { 'Content-Type': 'multipart/form-data' },
                      }),
  follow:           (userId: string)                          => api.post(`/profiles/${userId}/follow`),
  unfollow:         (userId: string)                          => api.delete(`/profiles/${userId}/follow`),
  followers:        (userId: string)                          => api.get(`/profiles/${userId}/followers`),
  following:        (userId: string)                          => api.get(`/profiles/${userId}/following`),
  signals:          (userId: string, params?: Record<string, unknown>) =>
                      api.get(`/profiles/${userId}/signals`, { params }),
  strategies:       (userId: string)                          => api.get(`/profiles/${userId}/strategies`),
  stats:            (userId: string)                          => api.get(`/profiles/${userId}/stats`),
};

// ── Admin API ─────────────────────────────────────────────────────────────────
// Backend: /api/admin/*

export const adminApi = {
  // Overview — /api/admin/dashboard-data is the real overview endpoint
  overview:         ()                                        => api.get('/admin/dashboard-data'),
  alerts:           ()                                        => api.get('/admin/status'),
  // Users
  users:            (params?: Record<string, unknown>)        => api.get('/admin/users', { params }),
  user:             (userId: string)                          => api.get(`/admin/users/${userId}`),
  updateUser:       (userId: string, payload: Record<string, unknown>) =>
                      api.patch(`/admin/users/${userId}`, payload),
  banUser:          (userId: string, reason?: string)         =>
                      api.post(`/admin/users/${userId}/ban`, { reason }),
  unbanUser:        (userId: string)                          => api.post(`/admin/users/${userId}/unban`),
  resetPassword:    (userId: string)                          => api.post(`/admin/users/${userId}/reset-password`),
  // Audit
  auditLog:         (params?: Record<string, unknown>)        => api.get('/admin/audit-log', { params }),
  auditExport:      ()                                        => api.get('/admin/audit-log/export', { responseType: 'blob' }),
  // Platform
  platformConfig:   ()                                        => api.get('/admin/settings'),
  updateConfig:     (payload: Record<string, unknown>)        => api.post('/admin/settings', payload),
  maintenanceMode:  (enabled: boolean)                        =>
                      api.post('/admin/pause', { enabled }),
  // KYC
  kycList:          (params?: Record<string, unknown>)        => api.get('/admin/kyc/pending', { params }),
  kycApprove:       (userId: string)                          => api.post('/admin/kyc/decide', { user_id: userId, decision: 'approve' }),
  kycReject:        (userId: string, reason: string)          =>
                      api.post('/admin/kyc/decide', { user_id: userId, decision: 'reject', reason }),
  // Security — /api/security/* router
  lockdown:         (enable: boolean)                         =>
                      api.post('/security/lockdown', { enable }),
  unblockIp:        (ip: string)                              => api.post('/security/unblock-ip', { ip }),
  blockIp:          (ip: string, reason?: string)             =>
                      api.post('/security/block-ip', { ip, reason }),
};

// ── Billing API ───────────────────────────────────────────────────────────────
// Backend: /api/billing/*

export const billingApi = {
  balance:          ()                                        => api.get('/billing/balance'),
  transactions:     (params?: Record<string, unknown>)        => api.get('/billing/transactions', { params }),
  subscription:     ()                                        => api.get('/billing/subscription'),
  cancelSub:        ()                                        => api.post('/billing/subscription/cancel'),
  resumeSub:        ()                                        => api.post('/billing/subscription/resume'),
  changePlan:       (plan: string)                            => api.post('/billing/subscription/change', { plan }),
  paymentMethods:   ()                                        => api.get('/billing/payment-methods'),
  addPaymentMethod: (payload: Record<string, unknown>)        =>
                      api.post('/billing/payment-methods', payload),
  removePaymentMethod: (methodId: string)                     =>
                      api.delete(`/billing/payment-methods/${methodId}`),
  setDefaultMethod: (methodId: string)                        =>
                      api.post(`/billing/payment-methods/${methodId}/default`),
  deposit:          (payload: Record<string, unknown>)        => api.post('/payments/deposit', payload),
  withdraw:         (payload: Record<string, unknown>)        => api.post('/payments/withdraw', payload),
  invoices:         (params?: Record<string, unknown>)        => api.get('/billing/invoices', { params }),
  invoice:          (invoiceId: string)                       => api.get(`/billing/invoices/${invoiceId}`),
  plans:            ()                                        => api.get('/billing/plans'),
};

// ── Copy Trading API ──────────────────────────────────────────────────────────
// Backend: /api/copy/* and /api/leaderboard/*

export const copyTradingApi = {
  leaders:          (params?: Record<string, unknown>)        => api.get('/leaderboard', { params }),
  leaderProfile:    (traderId: string)                        => api.get(`/leaderboard/${traderId}`),
  leaderStats:      (traderId: string)                        => api.get(`/leaderboard/${traderId}/stats`),
  startCopy:        (traderId: string, payload: Record<string, unknown>) =>
                      api.post(`/copy/${traderId}`, payload),
  stopCopy:         (traderId: string)                        => api.delete(`/copy/${traderId}`),
  activeSessions:   ()                                        => api.get('/copy/active'),
  updateAllocation: (traderId: string, amount: number)        =>
                      api.patch(`/copy/${traderId}/allocation`, { allocation_amount: amount }),
  history:          (params?: Record<string, unknown>)        => api.get('/copy/history', { params }),
  performance:      (traderId: string)                        => api.get(`/copy/${traderId}/performance`),
};

// ── KYC API ───────────────────────────────────────────────────────────────────
// Backend: /api/kyc/*

export const kycApi = {
  status:           ()                                        => api.get('/kyc/status'),
  /**
   * Submit the KYC application.
   *
   * Takes no body (audit #58). The page used to send `document_types[]` built
   * from React state — a client-supplied claim about which documents exist, on a
   * compliance submission. The server ignores it and derives the list from what
   * it actually stored, which is the only trustworthy source.
   */
  submit:           ()                                        => api.post('/kyc/submit'),
  documents:        ()                                        => api.get('/kyc/documents'),
  uploadDocument:   (formData: FormData)                      =>
                      api.post('/kyc/documents', formData, {
                        headers: { 'Content-Type': 'multipart/form-data' },
                      }),
};

// ── Chat API ──────────────────────────────────────────────────────────────────
// Backend: /api/chat/*

export const chatApi = {
  rooms:            ()                                        => api.get('/chat/rooms'),
  room:             (roomId: string)                          => api.get(`/chat/rooms/${roomId}`),
  createRoom:       (payload: Record<string, unknown>)        => api.post('/chat/rooms', payload),
  messages:         (roomId: string, params?: Record<string, unknown>) =>
                      api.get(`/chat/rooms/${roomId}/messages`, { params }),
  sendMessage:      (roomId: string, text: string, attachments?: string[]) =>
                      api.post(`/chat/rooms/${roomId}/messages`, { content: text, text, attachments }),
  deleteMessage:    (roomId: string, msgId: string)           =>
                      api.delete(`/chat/rooms/${roomId}/messages/${msgId}`),
  addReaction:      (roomId: string, msgId: string, emoji: string) =>
                      api.post(`/chat/rooms/${roomId}/messages/${msgId}/reactions`, { emoji }),
  removeReaction:   (roomId: string, msgId: string, emoji: string) =>
                      api.delete(`/chat/rooms/${roomId}/messages/${msgId}/reactions/${encodeURIComponent(emoji)}`),
  markRead:         (roomId: string)                          => api.post(`/chat/rooms/${roomId}/read`),
  directMessages:   (userId: string, params?: Record<string, unknown>) =>
                      api.get(`/chat/dm/${userId}`, { params }),
  sendDM:           (userId: string, text: string)            =>
                      api.post(`/chat/dm/${userId}`, { content: text, text }),
  onlineUsers:      ()                                        => api.get('/chat/online'),
};

// ── AI Assistant API ──────────────────────────────────────────────────────────
// Backend: api/chat.py — POST /api/chat (LLM agent with offline fallback).
// Distinct from the community chatApi above (which is /api/chat/rooms/*).

export const aiAssistantApi = {
  /** Send a message to the AI assistant. `session_id` isolates conversation
   *  history (e.g. "assistant" vs "support"). Backend caps the round-trip at
   *  25s, so allow a little headroom on the client. */
  send:         (message: string, sessionId?: string) =>
                  api.post('/chat', { message, session_id: sessionId }, { timeout: 35_000 }),
  /** Clear conversation history for a session. */
  clearHistory: (sessionId?: string) =>
                  api.delete('/chat/history', { params: sessionId ? { session_id: sessionId } : {} }),
  /** Readiness / configured backend probe. */
  status:       () => api.get('/chat/status'),
};

// ── Cloud Voice API (optional) ──────────────────────────────────────────────────
// Backend: /api/voice/* — server-side TTS/STT behind a provider key. When no
// provider is configured these return 503 and the frontend falls back to the
// browser-native Web Speech API. See api/voice.py.

export const voiceApi = {
  /** Which cloud providers (if any) are configured. */
  status: () => api.get<{ tts_available: boolean; stt_available: boolean; tts_provider?: string | null; stt_provider?: string | null }>('/voice/status'),
  /** Synthesize text to speech; returns an audio blob (audio/mpeg). */
  tts:    (text: string, voice?: string) =>
            api.post('/voice/tts', { text, voice }, { responseType: 'blob', timeout: 35_000 }),
  /** Transcribe an audio clip to text. */
  stt:    (audio: Blob, filename = 'audio.webm') => {
            const form = new FormData();
            form.append('audio', audio, filename);
            return api.post<{ text: string }>('/voice/stt', form, { timeout: 35_000 });
          },
};

// ── Risk Calculator API ───────────────────────────────────────────────────────
// Backend: /api/risk/calculator/*

export const riskCalcApi = {
  livePrice:        (symbol: string)                          => api.get(`/risk/live-price/${encodeURIComponent(symbol)}`),
  history:          ()                                        => api.get('/risk/calculator/history'),
  saveCalc:         (payload: Record<string, unknown>)        => api.post('/risk/calculator/history', payload),
  deleteCalc:       (id: string)                              => api.delete(`/risk/calculator/history/${id}`),
};

// ── 2FA API ───────────────────────────────────────────────────────────────────
// Backend: /api/2fa/*

export const twoFactorApi = {
  // GET /api/2fa/status — returns { user_id, enabled, backup_codes_remaining }
  status:           ()                                        => api.get('/2fa/status'),
  setup:            ()                                        => api.post('/2fa/setup'),
  verify:           (code: string)                            => api.post('/2fa/verify', { code }),
  disable:          (code: string)                            => api.post('/2fa/disable', { code }),
  // GET /api/2fa/backup-codes — generates and returns 8 one-time codes
  backupCodes:      ()                                        => api.get('/2fa/backup-codes'),
  regenerateCodes:  ()                                        => api.post('/2fa/backup-codes/regenerate'),
};

// ── Crypto Checkout API ───────────────────────────────────────────────────────
// Backend: /api/billing/crypto/*

export const cryptoCheckoutApi = {
  rates:            ()                                        => api.get('/billing/crypto/rates'),
  createOrder:      (payload: Record<string, unknown>)        => api.post('/billing/crypto/order', payload),
  orderStatus:      (orderId: string)                         => api.get(`/billing/crypto/order/${orderId}`),
  cancelOrder:      (orderId: string)                         => api.post(`/billing/crypto/order/${orderId}/cancel`),
};

// ── Journal API ───────────────────────────────────────────────────────────────
// Backend: /api/journal/*

export const journalApi = {
  trades:           (params?: Record<string, unknown>)        => api.get('/journal/trades', { params }),
  trade:            (tradeId: string)                         => api.get(`/journal/trades/${tradeId}`),
  updateTrade:      (tradeId: string, payload: Record<string, unknown>) =>
                      api.patch(`/journal/trades/${tradeId}`, payload),
  stats:            (params?: Record<string, unknown>)        => api.get('/journal/stats', { params }),
  mistakes:         (params?: Record<string, unknown>)        => api.get('/journal/mistakes', { params }),
  emotionStats:     ()                                        => api.get('/journal/emotion-stats'),
  weeklyReport:     ()                                        => api.get('/journal/weekly-report'),
  export:           (format: 'csv' | 'json' = 'csv')         =>
                      api.get(`/journal/export?format=${format}`, { responseType: 'blob' }),
  tags:             ()                                        => api.get('/journal/tags'),
  uploadScreenshot: (tradeId: string, form: FormData)         =>
                      api.post(`/journal/trades/${tradeId}/screenshot`, form, {
                        headers: { 'Content-Type': 'multipart/form-data' },
                      }),
};

// ── Prop Firm API ─────────────────────────────────────────────────────────────
// Backend: /api/risk/prop-firm*

export const propFirmExtApi = {
  status:           ()                                        => api.get('/risk/prop-firm-status'),
  history:          (params?: Record<string, unknown>)        => api.get('/risk/prop-firm/history', { params }),
  challenges:       ()                                        => api.get('/risk/prop-firm/challenges'),
  dailyStats:       (params?: Record<string, unknown>)        => api.get('/risk/prop-firm/daily-stats', { params }),
  breachAlerts:     ()                                        => api.get('/risk/prop-firm/breach-alerts'),
  acknowledgeAlert: (alertId: string)                         =>
                      api.post(`/risk/prop-firm/breach-alerts/${alertId}/acknowledge`),
  accounts:         ()                                        => api.get('/risk/prop-firm/accounts'),
};

// ── Performance Extended API ──────────────────────────────────────────────────
// Backend: /api/performance/*

export const performanceExtApi = {
  public:           ()                                        => api.get('/performance/public'),
  equityCurve:      ()                                        => api.get('/performance/equity-curve'),
  weeklyReport:     ()                                        => api.get('/performance/weekly-report/latest'),
  weeklyReports:    (params?: Record<string, unknown>)        => api.get('/performance/weekly-reports', { params }),
  export:           (format: 'csv' | 'pdf' = 'csv', params?: Record<string, unknown>) =>
                      api.get(`/performance/export?format=${format}`, { params, responseType: 'blob' }),
  tradeBreakdown:   (params?: Record<string, unknown>)        => api.get('/performance/trade-breakdown', { params }),
  attribution:      ()                                        => api.get('/performance/attribution'),
};

// ── PnL Extended API ──────────────────────────────────────────────────────────
// Backend: /api/pnl/*

export const pnlApi = {
  summary:          ()                                        => api.get('/pnl/summary'),
  equityCurve:      ()                                        => api.get('/pnl/equity-curve'),
  drawdownCurve:    ()                                        => api.get('/pnl/drawdown-curve'),
  tradeLog:         (params?: Record<string, unknown>)        => api.get('/pnl/trade-log', { params }),
  openPositions:    ()                                        => api.get('/pnl/open-positions'),
  /** Closed-trade history. Unlike tradeLog this accepts a `symbol` filter. */
  history:          (params?: Record<string, unknown>)        => api.get('/pnl/history', { params }),
  export:           (format: 'csv' | 'json' = 'csv')         =>
                      api.get(`/pnl/export?format=${format}`, { responseType: 'blob' }),
};

// ── AI Strategy Extended API ──────────────────────────────────────────────────
// Backend: /api/brain/*

export const aiStrategyApi = {
  generate:         (payload: Record<string, unknown>)        => api.post('/brain/generate-strategy', payload),
  deploy:           (payload: Record<string, unknown>)        => api.post('/brain/deploy-strategy', payload),
  history:          (params?: Record<string, unknown>)        => api.get('/brain/strategies', { params }),
  strategy:         (strategyId: string)                      => api.get(`/brain/strategies/${strategyId}`),
  deleteStrategy:   (strategyId: string)                      => api.delete(`/brain/strategies/${strategyId}`),
  backtest:         (strategyId: string)                      => api.post(`/brain/strategies/${strategyId}/backtest`),
  activate:         (strategyId: string)                      => api.post(`/brain/strategies/${strategyId}/activate`),
  deactivate:       (strategyId: string)                      => api.post(`/brain/strategies/${strategyId}/deactivate`),
};

// ── Indicators Extended API ───────────────────────────────────────────────────
// Backend: /api/indicators/*

export const indicatorsApi = {
  list:             ()                                        => api.get('/indicators'),
  create:           (payload: Record<string, unknown>)        => api.post('/indicators', payload),
  update:           (id: string, payload: Record<string, unknown>) =>
                      api.patch(`/indicators/${id}`, payload),
  delete:           (id: string)                              => api.delete(`/indicators/${id}`),
  preview:          (payload: Record<string, unknown>)        => api.post('/indicators/preview', payload),
  apply:            (id: string, payload: Record<string, unknown>) =>
                      api.post(`/indicators/${id}/apply`, payload),
};

// ── News API ──────────────────────────────────────────────────────────────────
// Backend: /api/news/* (news/__init__.py create_news_router)

export const newsApi = {
  /** Roadmap news feed with AI sentiment per article (api/news_feed.py). */
  feed:             (params?: object)                         => api.get('/news/feed', { params }),
  /** Nuclear-sentiment score for a symbol. */
  nuclearScore:     (symbol = 'XAUUSD')                       => api.get('/news/nuclear-score', { params: { symbol } }),
  /** News-driven economic calendar. */
  calendar:         ()                                        => api.get('/news/calendar'),
  /** Aggregated latest sentiment summary (api/sentiment prefix). */
  sentimentLatest:  (symbol = 'XAUUSD')                       => api.get('/sentiment/latest', { params: { symbol } }),
  /** Latest news articles, optionally filtered by symbol. */
  latest:           (params?: { symbol?: string; limit?: number }) =>
                      api.get('/news/latest', { params }),
  /** News-based sentiment score for a symbol. */
  sentiment:        (symbol: string)                          => api.get(`/news/sentiment/${encodeURIComponent(symbol)}`),
  /** Geopolitical risk signal for gold/USD. */
  geopoliticalSignal: ()                                      => api.get('/news/geopolitical/signal'),
  /** Recent geopolitical events. */
  geopoliticalEvents: (forceRefresh = false)                  =>
                      api.get('/news/geopolitical/events', { params: { force_refresh: forceRefresh } }),
  /** Full geopolitical risk assessment. */
  geopoliticalAssessment: ()                                  => api.get('/news/geopolitical/assessment'),
  /** World Monitor deep-link views. */
  worldMonitor:     ()                                        => api.get('/news/geopolitical/world-monitor'),
  /** Upcoming high-impact economic events. */
  economicUpcoming: (params?: { days?: number; importance?: string }) =>
                      api.get('/news/economic/upcoming', { params }),
};

// ── Profiles List API ─────────────────────────────────────────────────────────
// Backend: GET /api/profiles (api/profiles.py)

export const profilesListApi = {
  /** Paginated list of public trader profiles. */
  list:             (params?: { limit?: number; offset?: number; search?: string; sort_by?: string }) =>
                      api.get('/profiles', { params }),
};
