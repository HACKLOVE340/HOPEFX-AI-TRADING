/**
 * NotFound — 404 page shown for any unmatched route.
 *
 * "Go to Dashboard" resolves to the role-appropriate landing page:
 *   superadmin → /superadmin
 *   admin      → /audit
 *   trader/user → /dashboard
 *
 * Unauthenticated visitors are sent to /login.
 */

import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useStore, selectIsAuth } from '../store';
import type { UserRole } from '../store';

function dashboardForRole(role: UserRole | undefined, isAuth: boolean): string {
  if (!isAuth) return '/login';
  if (role === 'superadmin') return '/superadmin';
  if (role === 'admin') return '/audit';
  return '/dashboard';
}

const NotFound: React.FC = () => {
  const navigate    = useNavigate();
  const location    = useLocation();
  const isAuth      = useStore(selectIsAuth);
  const user        = useStore((s) => s.user);

  const destination = dashboardForRole(user?.role, isAuth);
  const btnLabel    = isAuth ? 'Go to Dashboard' : 'Sign In';

  const quickLinks = isAuth
    ? [
        { label: '⚡ Trade',       path: '/trade' },
        { label: '📊 Dashboard',   path: '/home' },
        { label: '📓 Journal',     path: '/journal' },
        { label: '📈 Performance', path: '/performance' },
        { label: '🛡 Risk Calc',   path: '/risk-calculator' },
        { label: '💳 Wallet',      path: '/wallet' },
        { label: '⚙️ Settings',    path: '/settings' },
        { label: '📖 Docs',        path: '/docs' },
      ]
    : [
        { label: '🔑 Sign In',     path: '/login' },
        { label: '📝 Register',    path: '/register' },
        { label: '📖 Docs',        path: '/docs' },
        { label: '🟢 Status',      path: '/status' },
      ];

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', minHeight: '100vh',
      background: 'var(--bg, #0a0f1a)', color: 'var(--text, #f1f5f9)',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
      padding: '2rem', textAlign: 'center', gap: '1.5rem',
    }}>
      {/* Status code */}
      <div style={{
        fontSize: '7rem', fontWeight: 900, lineHeight: 1,
        background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
        WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        backgroundClip: 'text', userSelect: 'none',
      }}>
        404
      </div>

      {/* Heading */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#f1f5f9' }}>
          Page not found
        </h1>
        <p style={{ fontSize: '0.875rem', color: '#64748b', margin: 0 }}>
          <code style={{ background: '#1e2d3d', borderRadius: '4px', padding: '2px 6px', fontSize: '0.8rem', color: '#94a3b8' }}>
            {location.pathname}
          </code>{' '}
          does not exist.
        </p>
      </div>

      {/* Primary actions */}
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center' }}>
        <Link
          to={destination}
          style={{
            background: '#3b82f6', border: 'none', borderRadius: '8px',
            color: '#fff', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 600,
            padding: '10px 20px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.background = '#2563eb'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.background = '#3b82f6'; }}
        >
          {btnLabel}
        </Link>

        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'transparent', border: '1px solid #334155', borderRadius: '8px',
            color: '#94a3b8', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 600,
            padding: '10px 20px',
          }}
          onMouseEnter={e => { const b = e.currentTarget as HTMLButtonElement; b.style.borderColor = '#475569'; b.style.color = '#f1f5f9'; }}
          onMouseLeave={e => { const b = e.currentTarget as HTMLButtonElement; b.style.borderColor = '#334155'; b.style.color = '#94a3b8'; }}
        >
          ← Go Back
        </button>
      </div>

      {/* Quick links */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'center', marginTop: '0.5rem', maxWidth: 520 }}>
        {quickLinks.map(({ label, path }) => (
          <Link
            key={path}
            to={path}
            style={{
              background: 'rgba(59,130,246,0.08)', border: '1px solid #1e2d3d',
              borderRadius: '6px', color: '#64748b', fontSize: '0.75rem', fontWeight: 600,
              padding: '6px 12px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center',
            }}
            onMouseEnter={e => { const a = e.currentTarget as HTMLAnchorElement; a.style.borderColor = '#334155'; a.style.color = '#94a3b8'; }}
            onMouseLeave={e => { const a = e.currentTarget as HTMLAnchorElement; a.style.borderColor = '#1e2d3d'; a.style.color = '#64748b'; }}
          >
            {label}
          </Link>
        ))}
      </div>

      {/* Help text */}
      <p style={{ fontSize: '0.75rem', color: '#334155', margin: 0 }}>
        If you followed a link that should work,{' '}
        <Link to="/docs" style={{ color: '#475569', textDecoration: 'underline' }}>check the docs</Link>
        {' '}or view{' '}
        <Link to="/status" style={{ color: '#475569', textDecoration: 'underline' }}>system status</Link>.
      </p>
    </div>
  );
};

export default NotFound;
