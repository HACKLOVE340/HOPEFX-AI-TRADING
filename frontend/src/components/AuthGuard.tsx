/**
 * AuthGuard — redirects unauthenticated users to /login.
 * Preserves the attempted URL so login can redirect back.
 *
 * Session-restore flow (page refresh)
 * ------------------------------------
 * The access token is intentionally NOT persisted to localStorage.
 * After a page refresh isAuthenticated=true but token=null.
 * We call /api/auth/me immediately — the 401 response interceptor in
 * useApi.ts will transparently call /auth/refresh with the httpOnly
 * refresh-token cookie, obtain a new access token, update Zustand, and
 * retry the /me request.  AuthGuard stays in the spinner ("syncing") until
 * the /me round-trip (including any silent refresh) completes.
 *
 * This prevents the page-refresh-kicks-to-/login bug without persisting
 * the access token to localStorage.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useStore, selectIsAuth } from '../store';
import { authApi } from '../hooks/useApi';

interface AuthGuardProps {
  children: React.ReactNode;
  requiredRole?: import('../store').UserRole;
}

const ROLE_RANK: Record<import('../store').UserRole, number> = {
  user:       0,
  trader:     1,
  admin:      2,
  superadmin: 3,
};

function isTokenExpired(token: string | null): boolean {
  if (!token) return false; // null token = not restored yet, not expired
  try {
    const payload = JSON.parse(atob(token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp === 'number' && payload.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

export const AuthGuard: React.FC<AuthGuardProps> = ({ children, requiredRole }) => {
  const isAuth    = useStore(selectIsAuth);
  const token     = useStore((s) => s.token);
  const user      = useStore((s) => s.user);
  const setAuth   = useStore((s) => s.setAuth);
  const clearAuth = useStore((s) => s.clearAuth);
  const location  = useLocation();

  // syncing=true for any authenticated session until the server confirms the
  // user profile.  Covers both first-load (token already in memory) and
  // page-refresh (token=null, silent refresh running in interceptor).
  //
  // synced tracks the token value that was last verified so re-login within
  // the same session (new token) always triggers a fresh /me fetch.
  const syncedToken = useRef<string | null | undefined>(undefined);

  // A returning session is detected by a persisted user in the store even
  // when isAuth=false (isAuthenticated is reset to false on rehydration so
  // no component trusts it before the silent-refresh round-trip completes).
  // Start syncing if we have a persisted user OR if isAuth is already true
  // (covers the case where setAuth was called before this component mounts).
  const [syncing, setSyncing] = useState(isAuth || user !== null);

  useEffect(() => {
    // No session at all — nothing to sync.
    if (!isAuth && user === null) {
      syncedToken.current = undefined;
      setSyncing(false);
      return;
    }

    // Token is present but has expired → clear session immediately.
    // token=null is NOT expired — it means the access token hasn't been
    // restored from the refresh cookie yet (silent refresh in flight).
    if (token && isTokenExpired(token)) {
      clearAuth();
      setSyncing(false);
      return;
    }

    // Fetch fresh user profile whenever the token changes (covers login,
    // silent refresh, and re-login within the same session).
    // undefined means "never synced"; null means "token not yet restored".
    if (syncedToken.current !== token) {
      syncedToken.current = token;
      setSyncing(true);
      // Cold load / refresh: the in-memory token was cleared but a session is
      // persisted. The httpOnly access-token cookie makes /me succeed WITHOUT
      // triggering the 401→silent-refresh path, so the in-memory token (and
      // isAuthenticated) would never be restored and the user would be bounced
      // to /login. Restore the session from the refresh cookie first so the
      // token + isAuthenticated are re-established before we decide.
      const ensureSession: Promise<string | null> = token
        ? Promise.resolve(token)
        : authApi.restoreSession();

      ensureSession
        .then((restored) => {
          if (!restored) {
            // No valid session could be restored → force re-login.
            clearAuth();
            return;
          }
          return authApi.me()
            .then((res) => {
              const fresh = res.data;
              // Grab the token after restoreSession / the interceptor set it.
              const currentToken = useStore.getState().token;
              if (fresh && currentToken) {
                const changed =
                  fresh.role  !== user?.role  ||
                  fresh.email !== user?.email ||
                  fresh.plan  !== user?.plan;
                if (changed) setAuth(currentToken, fresh);
              }
            })
            .catch((meErr: unknown) => {
              // Only force logout if the token was EXPLICITLY rejected (401).
              // A transient /me failure (network blip, timeout, 5xx) must NOT
              // log the user out right after a successful login — we still hold
              // a valid token, and the response interceptor handles genuine 401s
              // (with a silent refresh). Logging out on any error caused an
              // "logged in then immediately kicked out" bug when the machine was
              // busy (feeds/WS churn) and /me timed out.
              const status = (meErr as { response?: { status?: number } })?.response?.status;
              if (status === 401) clearAuth();
            });
        })
        .catch(() => {
          // ensureSession (silent refresh on a cold load) failed → no session.
          clearAuth();
        })
        .finally(() => setSyncing(false));
    }
  }, [isAuth, token, user, setAuth, clearAuth]);

  // While restoring session or fetching fresh profile, show a neutral spinner.
  if (syncing) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center',
        justifyContent: 'center', background: '#0f172a',
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          border: '3px solid #1e293b', borderTopColor: '#3b82f6',
          animation: 'spin 0.7s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // Not authenticated after all restoration attempts → send to login.
  if (!isAuth) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user) {
    const userRank     = ROLE_RANK[user.role] ?? 0;
    const requiredRank = ROLE_RANK[requiredRole] ?? 0;
    if (userRank < requiredRank) {
      return (
        <div
          role="alert"
          style={{
            minHeight: '100vh', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            background: '#0f172a', color: '#f1f5f9',
            fontFamily: 'Inter, system-ui, sans-serif', gap: 12,
          }}
        >
          <span style={{ fontSize: 40 }}>🔒</span>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#f1f5f9' }}>
            Access Denied
          </h2>
          <p style={{ margin: 0, fontSize: 14, color: '#94a3b8', textAlign: 'center', maxWidth: 360 }}>
            This page requires the{' '}
            <span style={{ color: '#60a5fa', fontWeight: 600 }}>{requiredRole}</span>{' '}
            role. Your current role (<span style={{ color: '#94a3b8', fontWeight: 600 }}>{user.role}</span>)
            does not have sufficient permissions.
          </p>
        </div>
      );
    }
  }

  return <>{children}</>;
};

export default AuthGuard;
