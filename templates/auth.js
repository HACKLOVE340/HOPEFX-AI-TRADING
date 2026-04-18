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

function getAccessToken()  { return localStorage.getItem(AUTH_KEYS.accessToken)  || ''; }
function getRefreshToken() { return localStorage.getItem(AUTH_KEYS.refreshToken) || ''; }
function getUser()         { try { return JSON.parse(localStorage.getItem(AUTH_KEYS.user) || '{}'); } catch { return {}; } }

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

// ── Authenticated fetch ───────────────────────────────────────────────────────

/**
 * Drop-in replacement for fetch() that:
 * 1. Injects Authorization: Bearer <token>
 * 2. On 401, attempts a silent refresh and retries once
 * 3. On second 401, redirects to /login
 */
async function authFetch(url, options = {}) {
  const makeHeaders = () => ({
    ...options.headers,
    'Authorization': `Bearer ${getAccessToken()}`,
  });

  let res = await fetch(url, { ...options, headers: makeHeaders() });

  if (res.status === 401) {
    const ok = await silentRefresh();
    if (ok) {
      res = await fetch(url, { ...options, headers: makeHeaders() });
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

// ── Role-based redirect (used by login page) ──────────────────────────────────

function roleRedirect(token, explicitNext) {
  if (explicitNext) { window.location.replace(explicitNext); return; }
  const role = tokenRole(token);
  if (role === 'superadmin') { window.location.replace('/api/superadmin/'); return; }
  if (role === 'admin')      { window.location.replace('/api/admin/');      return; }
  window.location.replace('/paper-trading');
}
