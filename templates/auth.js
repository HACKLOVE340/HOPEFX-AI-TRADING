/**
 * static/auth.js
 * Shared authentication helpers for all HOPEFX dashboard pages.
 *
 * - Single source of truth for localStorage key names
 * - Silent JWT refresh: proactively refreshes the access token 2 min before expiry
 * - authFetch(): drop-in replacement for fetch() that injects Bearer token
 *   and retries once after a silent refresh on 401
 * - redirectIfUnauthenticated(): call on protected pages to bounce to /login
 */

const AUTH_KEYS = {
  accessToken:  'hopefx_access_token',
  refreshToken: 'hopefx_refresh_token',
  user:         'hopefx_user',
};

// ── Token storage ─────────────────────────────────────────────────────────────

// The React app (Zustand) persists state to 'hopefx-store' as a JSON blob.
// Backend HTML templates read the flat 'hopefx_access_token' key instead.
// Login.tsx now writes both, but this fallback covers sessions that were
// established before that fix — reads the token out of the Zustand blob
// and back-fills the flat key so subsequent calls work without re-login.
function getAccessToken() {
  const flat = localStorage.getItem(AUTH_KEYS.accessToken);
  if (flat) return flat;
  try {
    const store = JSON.parse(localStorage.getItem('hopefx-store') || '{}');
    const token = store?.state?.token || '';
    if (token) {
      // Back-fill so future calls use the fast path.
      localStorage.setItem(AUTH_KEYS.accessToken, token);
    }
    return token;
  } catch { return ''; }
}

function getRefreshToken() {
  const flat = localStorage.getItem(AUTH_KEYS.refreshToken);
  if (flat) return flat;
  try {
    // Zustand does not persist the refresh token in the store blob —
    // it is stored separately under hopefx_refresh_token by Login.tsx.
    return '';
  } catch { return ''; }
}

function getUser() { try { return JSON.parse(localStorage.getItem(AUTH_KEYS.user) || '{}'); } catch { return {}; } }

function setTokens(accessToken, refreshToken) {
  localStorage.setItem(AUTH_KEYS.accessToken,  accessToken);
  if (refreshToken) localStorage.setItem(AUTH_KEYS.refreshToken, refreshToken);
}

function clearTokens() {
  localStorage.removeItem(AUTH_KEYS.accessToken);
  localStorage.removeItem(AUTH_KEYS.refreshToken);
  localStorage.removeItem(AUTH_KEYS.user);
}

// ── JWT decode (no signature verification — server validates on every request) ─

function decodeJwt(token) {
  try {
    return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch { return null; }
}

function tokenExpiresAt(token) {
  const p = decodeJwt(token);
  return p && p.exp ? p.exp * 1000 : 0; // ms
}

function tokenRole(token) {
  const p = decodeJwt(token);
  return p ? (p.role || 'user') : 'user';
}

// ── Silent refresh ────────────────────────────────────────────────────────────

let _refreshPromise = null; // deduplicate concurrent refresh calls

async function silentRefresh() {
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) { clearTokens(); return false; }

    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      const data = await res.json();
      if (data.access_token) {
        setTokens(data.access_token, data.refresh_token || refreshToken);
        return true;
      }
      clearTokens();
      return false;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

// Schedule a proactive refresh 2 minutes before the token expires.
function scheduleRefresh() {
  const token = getAccessToken();
  if (!token) return;

  const expiresAt = tokenExpiresAt(token);
  if (!expiresAt) return;

  const refreshAt = expiresAt - 2 * 60 * 1000; // 2 min before expiry
  const delay     = refreshAt - Date.now();

  if (delay <= 0) {
    // Already expired or about to — refresh immediately
    silentRefresh().then(ok => { if (ok) scheduleRefresh(); else redirectToLogin(); });
    return;
  }

  setTimeout(async () => {
    const ok = await silentRefresh();
    if (ok) scheduleRefresh();
    else redirectToLogin();
  }, delay);
}

// ── CSRF token management ─────────────────────────────────────────────────────

const _CSRF_COOKIE   = 'hopefx_csrf';
const _CSRF_HEADER   = 'X-CSRF-Token';
const _CSRF_TTL_MS   = 55 * 60 * 1000; // 55 min — refresh before the 1-hour server TTL
const _CSRF_METHODS  = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// Paths that are exempt from CSRF (must mirror _CSRF_EXEMPT_PREFIXES in core/middleware.py)
const _CSRF_EXEMPT   = [
  '/api/auth/csrf-token',
  '/api/auth/login',
  '/api/auth/register',
  '/api/auth/activate-free-tier',
  '/api/auth/refresh',
  '/api/auth/forgot-password',
  '/api/auth/reset-password',
  '/api/auth/verify-email',
  '/api/auth/resend-verification',
  '/api/email/webhook',
  '/api/health',
];

let _csrfToken     = null;
let _csrfFetchedAt = 0;
let _csrfFetchProm = null;

function _readCsrfCookie() {
  const match = document.cookie.split(';')
    .map(c => c.trim())
    .find(c => c.startsWith(_CSRF_COOKIE + '='));
  return match ? decodeURIComponent(match.slice(_CSRF_COOKIE.length + 1)) : null;
}

async function _fetchCsrfToken() {
  if (_csrfFetchProm) return _csrfFetchProm;
  _csrfFetchProm = (async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await fetch('/api/auth/csrf-token', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json().catch(() => ({}));
          const token = data.csrf_token || _readCsrfCookie();
          if (token) { _csrfToken = token; _csrfFetchedAt = Date.now(); return token; }
        }
      } catch { /* fall through to cookie read */ }
      const cookie = _readCsrfCookie();
      if (cookie) { _csrfToken = cookie; _csrfFetchedAt = Date.now(); return cookie; }
      if (attempt === 0) await new Promise(r => setTimeout(r, 300));
    }
    return _csrfToken;
  })().finally(() => { _csrfFetchProm = null; });
  return _csrfFetchProm;
}

async function _getCsrfToken() {
  const cookie = _readCsrfCookie();
  if (!cookie) { _csrfToken = null; _csrfFetchedAt = 0; }
  if (_csrfToken && cookie === _csrfToken && Date.now() - _csrfFetchedAt < _CSRF_TTL_MS) {
    return _csrfToken;
  }
  return _fetchCsrfToken();
}

// ── Authenticated fetch ───────────────────────────────────────────────────────

/**
 * Drop-in replacement for fetch() that:
 * 1. Injects Authorization: Bearer <token>
 * 2. Injects X-CSRF-Token for state-changing requests (POST/PUT/PATCH/DELETE)
 * 3. On 401, attempts a silent refresh and retries once
 * 4. On second 401, redirects to /login
 */
async function authFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const isExempt = _CSRF_EXEMPT.some(p => url.startsWith(p));

  const makeHeaders = async () => {
    const headers = {
      ...options.headers,
      'Authorization': `Bearer ${getAccessToken()}`,
    };
    if (_CSRF_METHODS.has(method) && !isExempt) {
      const csrf = await _getCsrfToken();
      if (csrf) headers[_CSRF_HEADER] = csrf;
    }
    return headers;
  };

  let res = await fetch(url, { ...options, headers: await makeHeaders() });

  if (res.status === 401) {
    const ok = await silentRefresh();
    if (ok) {
      res = await fetch(url, { ...options, headers: await makeHeaders() });
    }
    if (res.status === 401) {
      redirectToLogin();
    }
  }

  return res;
}

// ── Page guards ───────────────────────────────────────────────────────────────

function redirectToLogin() {
  clearTokens();
  window.location.replace('/login?next=' + encodeURIComponent(window.location.pathname));
}

/**
 * Call at the top of every protected page.
 * Verifies the token is present and not expired; starts the refresh scheduler.
 * Redirects to /login if unauthenticated.
 */
function requireAuth() {
  const token = getAccessToken();
  if (!token) { redirectToLogin(); return; }

  const expiresAt = tokenExpiresAt(token);
  if (expiresAt && Date.now() > expiresAt) {
    // Expired — try refresh before giving up
    silentRefresh().then(ok => {
      if (ok) scheduleRefresh();
      else redirectToLogin();
    });
    return;
  }

  scheduleRefresh();
}

/**
 * Call at the top of role-restricted pages.
 * Verifies the token is present, not expired, and carries the required role.
 * Redirects to /login if unauthenticated, or /dashboard if role is insufficient.
 *
 * Role hierarchy: user < trader < admin < superadmin
 */
const _ROLE_RANK = { user: 0, trader: 1, admin: 2, superadmin: 3 };

function requireRole(requiredRole) {
  const token = getAccessToken();
  if (!token) { redirectToLogin(); return; }

  const expiresAt = tokenExpiresAt(token);
  if (expiresAt && Date.now() > expiresAt) {
    silentRefresh().then(ok => {
      if (ok) {
        // Re-check role after refresh
        const freshRole = tokenRole(getAccessToken());
        if ((_ROLE_RANK[freshRole] ?? 0) < (_ROLE_RANK[requiredRole] ?? 99)) {
          // Redirect to the user's own landing page (not /login — they are authenticated)
          if (freshRole === 'admin') { window.location.replace('/audit'); }
          else { window.location.replace('/dashboard'); }
        } else {
          scheduleRefresh();
        }
      } else {
        redirectToLogin();
      }
    });
    return;
  }

  const role = tokenRole(token);
  if ((_ROLE_RANK[role] ?? 0) < (_ROLE_RANK[requiredRole] ?? 99)) {
    // Authenticated but insufficient role — redirect to the user's own landing
    // page rather than /login (they are logged in, just not privileged enough).
    if (role === 'admin') { window.location.replace('/audit'); return; }
    window.location.replace('/dashboard');
    return;
  }

  scheduleRefresh();
}

// ── Role-based redirect (used by login page) ──────────────────────────────────

/**
 * Redirect to the correct post-login landing page for the token's role.
 *
 * Role → destination mapping (must stay in sync with React Login.tsx
 * resolveDestination() and the React Router in App.tsx):
 *
 *   superadmin → /superadmin   (SuperAdmin React dashboard)
 *   admin      → /audit        (Admin audit log — AdminGuard-protected React page)
 *   trader/user → /dashboard   (Trader React dashboard)
 *
 * If an explicit `next` URL is provided (from ?next= query param) it is used
 * instead, so users land back on the page they were trying to reach.
 */
function roleRedirect(token, explicitNext) {
  if (explicitNext) { window.location.replace(explicitNext); return; }
  const role = tokenRole(token);
  if (role === 'superadmin') { window.location.replace('/superadmin'); return; }
  if (role === 'admin')      { window.location.replace('/audit');      return; }
  window.location.replace('/dashboard');
}
