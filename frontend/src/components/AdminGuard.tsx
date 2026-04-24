/**
 * AdminGuard.tsx
 * Blocks non-admin users from accessing admin-only pages.
 * Renders an access-denied screen instead of redirecting,
 * so the URL stays intact for debugging.
 *
 * Loading state: when the session is authenticated but user profile has not
 * yet been fetched (page refresh, silent token refresh in flight), user is
 * null. Show a spinner instead of the access-denied screen to avoid a false
 * rejection while AuthGuard's /me round-trip is still in progress.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore, selectUser, selectIsAuth } from '../store';
import { isAdmin } from '../lib/subscription';

interface Props {
  children: React.ReactNode;
}

const AdminGuard: React.FC<Props> = ({ children }) => {
  const user   = useStore(selectUser);
  const isAuth = useStore(selectIsAuth);
  const navigate = useNavigate();

  // Session is authenticated but user profile not yet loaded — wait for
  // AuthGuard's /me round-trip to complete before making an access decision.
  if (isAuth && !user) {
    return (
      <div style={{
        minHeight: '60vh', display: 'flex', alignItems: 'center',
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

  if (user && isAdmin(user.role)) return <>{children}</>;

  return (
    <div style={{
      minHeight: '60vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#0f172a', padding: 40,
    }}>
      <div style={{
        maxWidth: 420, textAlign: 'center',
        background: '#1e293b', border: '1px solid #7f1d1d',
        borderRadius: 16, padding: '40px 36px',
      }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%',
          background: '#450a0a', border: '2px solid #7f1d1d',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 20px', fontSize: 26,
        }}>
          🛡️
        </div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', margin: '0 0 10px' }}>
          Admin access required
        </h2>
        <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px', lineHeight: 1.6 }}>
          This area is restricted to administrators only.
          Your current role does not have permission to view this page.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            background: '#1e3a5f', border: '1px solid #1e3a5f', borderRadius: 8,
            color: '#60a5fa', cursor: 'pointer', fontSize: 14, fontWeight: 600,
            padding: '10px 24px',
          }}
        >
          Back to Dashboard
        </button>
      </div>
    </div>
  );
};

export default AdminGuard;
