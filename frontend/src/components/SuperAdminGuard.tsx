/**
 * SuperAdminGuard.tsx
 * Blocks everyone except superadmin from accessing superadmin-only pages.
 * Admins see a specific "insufficient privilege" message.
 *
 * Must be rendered inside AuthGuard, which fetches /api/auth/me to confirm
 * the server-side role before rendering children. While user is null (role
 * not yet confirmed from the server) we show a loading spinner rather than
 * "Access Denied" to avoid a false rejection during the auth sync window.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore, selectUser } from '../store';
import { isSuperAdmin, isAdmin } from '../lib/subscription';

interface Props {
  children: React.ReactNode;
}

const SuperAdminGuard: React.FC<Props> = ({ children }) => {
  const user     = useStore(selectUser);
  const navigate = useNavigate();

  // user is null while AuthGuard is still syncing the role from /api/auth/me.
  // Render a spinner instead of "Access Denied" to avoid a false rejection.
  if (!user) {
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

  if (isSuperAdmin(user.role)) return <>{children}</>;

  const isAdminUser = isAdmin(user.role);

  return (
    <div style={{
      minHeight: '60vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#0f172a', padding: 40,
    }}>
      <div style={{
        maxWidth: 440, textAlign: 'center',
        background: '#1e293b', border: '1px solid #7f1d1d',
        borderRadius: 16, padding: '40px 36px',
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: '50%',
          background: 'linear-gradient(135deg, #450a0a, #7f1d1d)',
          border: '2px solid #dc2626',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 20px', fontSize: 28,
        }}>
          ⚡
        </div>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: '#450a0a', border: '1px solid #dc2626',
          borderRadius: 20, padding: '4px 12px', marginBottom: 16,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#ef4444' }} />
          <span style={{ fontSize: 11, fontWeight: 700, color: '#fca5a5', letterSpacing: '0.06em' }}>
            SUPERADMIN ONLY
          </span>
        </div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', margin: '0 0 10px' }}>
          {isAdminUser ? 'Insufficient privilege level' : 'Access denied'}
        </h2>
        <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px', lineHeight: 1.6 }}>
          {isAdminUser
            ? 'This area requires superadmin privileges. Admin accounts cannot access the master control center.'
            : 'This area is restricted to superadmin accounts only. Your current role does not have permission to view this page.'}
        </p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
          <button
            onClick={() => navigate('/dashboard')}
            style={{
              background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
              color: '#94a3b8', cursor: 'pointer', fontSize: 14, fontWeight: 600,
              padding: '10px 20px',
            }}
          >
            Dashboard
          </button>
          {isAdminUser && (
            <button
              onClick={() => navigate('/admin')}
              style={{
                background: '#1e3a5f', border: '1px solid #1e3a5f', borderRadius: 8,
                color: '#60a5fa', cursor: 'pointer', fontSize: 14, fontWeight: 600,
                padding: '10px 20px',
              }}
            >
              Admin Panel
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default SuperAdminGuard;
