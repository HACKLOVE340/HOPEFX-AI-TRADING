/**
 * AuthGuard — redirects unauthenticated users to /login.
 * Preserves the attempted URL so login can redirect back.
 *
 * On every mount it fetches /api/auth/me and syncs the user object
 * (including role) from the server. This ensures a role change (e.g.
 * admin → superadmin) is reflected immediately without requiring a
 * logout/login cycle, even when the old role is cached in localStorage.
 *
 * Also checks JWT expiry: if the persisted token is already expired the
 * store is cleared immediately, preventing stale isAuthenticated=true.
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
  if (!token) return true;
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

  // syncing=true while /api/auth/me is in-flight so guards don't render
  // with a stale cached role before the server response arrives.
  const synced  = useRef(false);
  const [syncing, setSyncing] = useState(!synced.current && isAuth && !isTokenExpired(token));

  useEffect(() => {
    if (isAuth && isTokenExpired(token)) {
      clearAuth();
      setSyncing(false);
      return;
    }
    // Fetch fresh user profile once per mount to pick up any role changes
    // that happened server-side since the token was issued / cached.
    if (isAuth && token && !synced.current) {
      synced.current = true;
      setSyncing(true);
      authApi.me()
        .then((res) => {
          const fresh = res.data;
          if (fresh && (fresh.role !== user?.role || fresh.email !== user?.email)) {
            setAuth(token, fresh);
          }
        })
        .catch(() => {
          // /me failed (expired / revoked token) — clear session
          clearAuth();
        })
        .finally(() => setSyncing(false));
    } else {
      setSyncing(false);
    }
  }, [isAuth, token, user, setAuth, clearAuth]);

  if (!isAuth || isTokenExpired(token)) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Hold rendering until role is confirmed from server — prevents SuperAdminGuard
  // from seeing a stale cached role and showing "Access Denied" on first load.
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

  if (requiredRole && user) {
    const userRank     = ROLE_RANK[user.role] ?? 0;
    const requiredRank = ROLE_RANK[requiredRole] ?? 0;
    if (userRank < requiredRank) {
      return (
        <div role="alert" style={{ padding: '2rem', textAlign: 'center' }}>
          <h2>Access Denied</h2>
          <p>This page requires the <strong>{requiredRole}</strong> role.</p>
          <p>Your current role does not have sufficient permissions.</p>
        </div>
      );
    }
  }

  return <>{children}</>;
};

export default AuthGuard;
