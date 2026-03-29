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
  const isAuth  = useStore(selectIsAuth);
  const token   = useStore((s) => s.token);
  const user    = useStore((s) => s.user);
  const clearAuth = useStore((s) => s.clearAuth);
  const location  = useLocation();

  useEffect(() => {
    if (isAuth && isTokenExpired(token)) {
      clearAuth();
    }
  }, [isAuth, token, clearAuth]);

  if (!isAuth || isTokenExpired(token)) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user) {
    const userRank     = ROLE_RANK[user.role] ?? 0;
    const requiredRank = ROLE_RANK[requiredRole] ?? 0;
    if (userRank < requiredRank) {
      return <Navigate to="/dashboard" replace />;
    }
  }

  return <>{children}</>;
};

export default AuthGuard;
