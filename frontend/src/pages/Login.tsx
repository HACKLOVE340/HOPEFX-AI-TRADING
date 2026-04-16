/**
 * Login page — JWT authentication with form validation.
 * Superadmin accounts are redirected to /superadmin after login.
 * All other roles go to the originally requested page or /dashboard.
 */

import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useStore } from '../store';
import { authApi } from '../hooks/useApi';
import type { UserRole } from '../store';

const Login: React.FC = () => {
  const navigate  = useNavigate();
  const location  = useLocation();
  const setAuth   = useStore((s) => s.setAuth);

  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const requestedFrom = (location.state as { from?: { pathname: string } })?.from?.pathname;

  /** Resolve the post-login destination based on role. */
  function resolveDestination(role: UserRole): string {
    // If the user was trying to reach a specific page, honour it —
    // unless they have no permission (e.g. a non-superadmin hitting /superadmin).
    if (requestedFrom && requestedFrom !== '/login') {
      const isSuperAdminRoute = requestedFrom.startsWith('/superadmin');
      if (!isSuperAdminRoute || role === 'superadmin') return requestedFrom;
    }
    // Role-based home page
    if (role === 'superadmin') return '/superadmin';
    if (role === 'admin')      return '/admin';
    return '/dashboard';
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Email and password are required.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const res = await authApi.login({ email: email.trim().toLowerCase(), password });
      // Persist refresh token for silent renewal; access token lives in Zustand
      if (res.data.refresh_token) {
        localStorage.setItem('hopefx_refresh_token', res.data.refresh_token);
      }
      setAuth(res.data.access_token, res.data.user);
      navigate(resolveDestination(res.data.user.role as UserRole), { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Invalid credentials. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={s.page}>
      <div style={s.card}>
        {/* Logo */}
        <div style={s.logo}>
          HOPE<span style={{ color: '#3b82f6' }}>FX</span>
        </div>
        <p style={s.tagline}>AI-Powered Trading Platform</p>

        <form onSubmit={handleSubmit} style={s.form}>
          <div style={s.field}>
            <label style={s.label} htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={s.input}
              placeholder="trader@hopefx.io"
              autoComplete="email"
              autoFocus
            />
          </div>

          <div style={s.field}>
            <label style={s.label} htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={s.input}
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>

          {error && <div style={s.error}>{error}</div>}

          <button type="submit" style={{ ...s.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div style={s.footer}>
          <a href="/register" style={s.link}>Create account</a>
          <span style={{ color: '#334155' }}>·</span>
          <a href="/status" style={s.link}>System Status</a>
          <span style={{ color: '#334155' }}>·</span>
          <a href="mailto:support@hopefx.io" style={s.link}>Support</a>
        </div>
      </div>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page:    { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a' },
  card:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 16, padding: '40px 36px', width: '100%', maxWidth: 400, boxShadow: '0 20px 60px rgba(0,0,0,0.4)' },
  logo:    { fontSize: 28, fontWeight: 800, color: '#f8fafc', textAlign: 'center', letterSpacing: -0.5 },
  tagline: { fontSize: 13, color: '#64748b', textAlign: 'center', margin: '4px 0 28px' },
  form:    { display: 'flex', flexDirection: 'column', gap: 16 },
  field:   { display: 'flex', flexDirection: 'column', gap: 6 },
  label:   { fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5 },
  input:   {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '10px 14px', fontSize: 14, color: '#f8fafc', outline: 'none',
    transition: 'border-color 0.2s',
  },
  error:   { background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.3)', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#f87171' },
  btn:     {
    background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8,
    padding: '12px', fontSize: 15, fontWeight: 600, cursor: 'pointer',
    marginTop: 4, transition: 'background 0.2s',
  },
  footer:  { display: 'flex', justifyContent: 'center', gap: 12, marginTop: 24, fontSize: 13 },
  link:    { color: '#64748b', textDecoration: 'none' },
};

export default Login;
