/**
 * AuthGuard — redirects unauthenticated users to /login.
 * Preserves the attempted URL so login can redirect back.
 *
 * Also checks JWT expiry on every render: if the persisted token is already
 * expired the store is cleared immediately, preventing a stale
 * isAuthenticated=true from bypassing the guard after a page reload.
 */

import React, { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useStore, selectIsAuth } from '../store';

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

/** Return true when the JWT exp claim is in the past (or token is malformed). */
function isTokenExpired(token: string | null): boolean {
  if (!token) return true;
  try {
    // JWT is three base64url segments separated by dots
    const payload = token.split('.')[1];
    if (!payload) return true;
    // base64url → base64 → JSON
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    const { exp } = JSON.parse(json) as { exp?: number };
    if (!exp) return false; // no exp claim — treat as valid
    // exp is in seconds; add a 10-second clock-skew buffer
    return Date.now() / 1000 > exp - 10;
  } catch {
    return true;
  }
}

const AuthGuard: React.FC<AuthGuardProps> = ({ children, requiredRole }) => {
  const isAuth   = useStore(selectIsAuth);
  const token    = useStore((s) => s.token);
  const user     = useStore((s) => s.user);
  const clearAuth = useStore((s) => s.clearAuth);
  const location = useLocation();

  // Clear stale persisted auth on mount and whenever the token changes
  useEffect(() => {
    if (isAuth && isTokenExpired(token)) {
      clearAuth();
    }
  }, [isAuth, token, clearAuth]);

  // Synchronous guard: also block render immediately if token is expired
  if (!isAuth || isTokenExpired(token)) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user) {
    const userRank     = ROLE_RANK[user.role] ?? 0;
    const requiredRank = ROLE_RANK[requiredRole] ?? 0;
    if (userRank < requiredRank) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: '#f87171' }}>
          <h2>Access Denied</h2>
          <p>You need <strong>{requiredRole}</strong> role to view this page.</p>
        </div>
      );
    }
  }

  return <>{children}</>;
};

export default AuthGuard;
