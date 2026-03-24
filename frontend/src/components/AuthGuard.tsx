/**
 * AuthGuard — redirects unauthenticated users to /login.
 * Preserves the attempted URL so login can redirect back.
 */

import React from 'react';
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

const AuthGuard: React.FC<AuthGuardProps> = ({ children, requiredRole }) => {
  const isAuth  = useStore(selectIsAuth);
  const user    = useStore((s) => s.user);
  const location = useLocation();

  if (!isAuth) {
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
