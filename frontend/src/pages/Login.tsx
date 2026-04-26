/**
 * Login.tsx
 *
 * Supports email or username login, optional TOTP, show/hide password,
 * loading skeleton, granular error messages, and role-based post-login routing.
 *
 * Role landing pages:
 *   superadmin → /superadmin
 *   admin      → /audit
 *   trader     → /dashboard
 *   user       → /dashboard
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useStore } from '../store';
import { authApi, prefetchCsrfToken } from '../hooks/useApi';
import type { UserRole } from '../store';
import { Eye, EyeOff, Activity, AlertCircle, Loader2, ShieldCheck } from 'lucide-react';

// ── Error normaliser ──────────────────────────────────────────────────────────

function humaniseError(raw: string | undefined): string {
  if (!raw) return 'Invalid credentials. Please try again.';
  const l = raw.toLowerCase();
  if (l.includes('invalid credentials') || l.includes('incorrect') || l.includes('wrong password'))
    return 'Invalid credentials. Please check your email/username and password.';
  if (l.includes('not found') || l.includes('no user'))
    return 'No account found with that email or username.';
  if (l.includes('disabled') || l.includes('suspended') || l.includes('banned'))
    return 'Your account has been suspended. Contact support@hopefx.io.';
  if (l.includes('email') && l.includes('verif'))
    return 'Please verify your email address before logging in.';
  if (l.includes('too many') || l.includes('rate limit') || l.includes('locked'))
    return 'Too many login attempts. Please wait a minute and try again.';
  if (l.includes('2fa') || l.includes('two-factor') || l.includes('otp') || l.includes('totp'))
    return 'Two-factor authentication code is invalid or expired. Check your authenticator app.';
  if (l.includes('service unavailable') || l.includes('503'))
    return 'Authentication service is temporarily unavailable. Try again shortly.';
  return raw.length > 120 ? 'Login failed. Please check your credentials and try again.' : raw;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SkeletonField() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div style={shimBar(60, 10, 8)} />
      <div style={shimBar('100%', 42)} />
    </div>
  );
}

function shimBar(w: number | string, h: number, mb = 0): React.CSSProperties {
  return {
    width: w, height: h, marginBottom: mb, borderRadius: 6,
    background: 'linear-gradient(90deg,#1e293b 25%,#334155 50%,#1e293b 75%)',
    backgroundSize: '200% 100%',
    animation: 'shimmer 1.4s infinite',
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function looksLikeEmail(val: string): boolean {
  return val.includes('@');
}

// ── Component ─────────────────────────────────────────────────────────────────

const Login: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth  = useStore((s) => s.setAuth);

  const [identifier,  setIdentifier]  = useState('');
  const [password,    setPassword]    = useState('');
  const [totpCode,    setTotpCode]    = useState('');
  const [showTotp,    setShowTotp]    = useState(false);
  const [showPass,    setShowPass]    = useState(false);
  const [error,       setError]       = useState('');
  const [loading,     setLoading]     = useState(false);
  const [focusField,  setFocusField]  = useState<string | null>(null);

  // Honour ?next= param set by the 401 interceptor in useApi.ts
  const params        = new URLSearchParams(location.search);
  const nextParam     = params.get('next');
  const requestedFrom = nextParam
    || (location.state as { from?: { pathname: string } })?.from?.pathname;

  useEffect(() => {
    const id = 'hopefx-shimmer';
    if (!document.getElementById(id)) {
      const st = document.createElement('style');
      st.id = id;
      st.textContent = '@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}';
      document.head.appendChild(st);
    }
    document.title = 'Sign In — HOPEFX';
    return () => { document.title = 'HOPEFX'; };
  }, []);

  function resolveDestination(role: UserRole): string {
    if (requestedFrom && requestedFrom !== '/login') {
      const isSuperAdminRoute = requestedFrom.startsWith('/superadmin');
      const isAdminRoute      = ['/audit', '/security', '/auto-heal', '/whitelabel'].some(
        (p) => requestedFrom.startsWith(p),
      );
      const canAccess =
        (isSuperAdminRoute && role === 'superadmin') ||
        (isAdminRoute      && (role === 'admin' || role === 'superadmin')) ||
        (!isSuperAdminRoute && !isAdminRoute);
      if (canAccess) return requestedFrom;
    }
    if (role === 'superadmin') return '/superadmin';
    if (role === 'admin')      return '/audit';
    return '/dashboard';
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const id = identifier.trim();
    if (!id)       { setError('Email or username is required.'); return; }
    if (!password) { setError('Password is required.'); return; }
    setError('');
    setLoading(true);

    try {
      const payload = looksLikeEmail(id)
        ? { email: id.toLowerCase(), password, totp_code: totpCode || undefined }
        : { username: id, password, totp_code: totpCode || undefined };

      const res = await authApi.login(payload);

      // Tokens are in httpOnly cookies set by the server.
      // Store the access token in Zustand memory only — never localStorage.
      setAuth(res.data.access_token, res.data.user);
      // Fire CSRF prefetch without awaiting — it runs in the background so
      // navigation is instant. The interceptor will retry on the first POST
      // if the token isn't ready yet.
      void prefetchCsrfToken();
      navigate(resolveDestination(res.data.user.role as UserRole), { replace: true });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setLoading(false);

      // Reveal TOTP field when server signals 2FA is required.
      if (detail && (detail.toLowerCase().includes('2fa') || detail.toLowerCase().includes('totp'))) {
        setShowTotp(true);
      }

      setError(humaniseError(detail));
    }
  };

  const inputStyle = (field: string): React.CSSProperties => ({
    ...s.input,
    border: `1px solid ${
      error && !loading
        ? (focusField === field ? '#ef4444' : '#7f1d1d')
        : (focusField === field ? '#3b82f6' : '#334155')
    }`,
    boxShadow: focusField === field
      ? (error && !loading ? '0 0 0 3px rgba(239,68,68,0.15)' : '0 0 0 3px rgba(59,130,246,0.15)')
      : 'none',
  });

  return (
    <div style={s.page}>
      <div style={s.card}>
        {/* Logo */}
        <a href="/" style={s.logoLink}>
          <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
          <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        </a>
        <p style={s.tagline}>AI-Powered Trading Platform</p>

        {loading && !error ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 8 }}>
            <SkeletonField />
            <SkeletonField />
            <div style={shimBar('100%', 46)} />
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={s.form} noValidate>

            {/* Email or Username */}
            <div style={s.field}>
              <label style={s.label} htmlFor="identifier">Email or Username</label>
              <input
                id="identifier"
                type="text"
                value={identifier}
                onChange={(e) => { setIdentifier(e.target.value); setError(''); setShowTotp(false); }}
                onFocus={() => setFocusField('identifier')}
                onBlur={() => setFocusField(null)}
                style={inputStyle('identifier')}
                placeholder="trader@hopefx.io or username"
                autoComplete="username"
                autoFocus
                disabled={loading}
                inputMode={looksLikeEmail(identifier) ? 'email' : 'text'}
              />
            </div>

            {/* Password */}
            <div style={s.field}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={s.label} htmlFor="password">Password</label>
                <Link to="/forgot-password" style={s.forgotLink}>Forgot password?</Link>
              </div>
              <div style={{ position: 'relative' }}>
                <input
                  id="password"
                  type={showPass ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(''); }}
                  onFocus={() => setFocusField('password')}
                  onBlur={() => setFocusField(null)}
                  style={{ ...inputStyle('password'), paddingRight: 44 }}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPass(v => !v)}
                  style={s.eyeBtn}
                  aria-label={showPass ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {showPass
                    ? <EyeOff size={16} color="#64748b" />
                    : <Eye    size={16} color="#64748b" />}
                </button>
              </div>
            </div>

            {/* TOTP — revealed when server signals 2FA is required */}
            {showTotp && (
              <div style={s.field}>
                <label style={s.label} htmlFor="totp">
                  <ShieldCheck size={11} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                  Authenticator Code
                </label>
                <input
                  id="totp"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6,8}"
                  maxLength={8}
                  value={totpCode}
                  onChange={(e) => { setTotpCode(e.target.value.replace(/\D/g, '')); setError(''); }}
                  onFocus={() => setFocusField('totp')}
                  onBlur={() => setFocusField(null)}
                  style={{ ...inputStyle('totp'), letterSpacing: 4, fontFamily: 'monospace', fontSize: 18 }}
                  placeholder="000000"
                  autoComplete="one-time-code"
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                  disabled={loading}
                />
                <p style={s.totpHint}>Enter the 6-digit code from your authenticator app.</p>
              </div>
            )}

            {/* Error */}
            {error && (
              <div style={s.error} role="alert" aria-live="assertive">
                <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              style={{ ...s.btn, opacity: loading ? 0.7 : 1 }}
              disabled={loading}
            >
              {loading
                ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Signing in…</>
                : 'Sign In'}
            </button>
          </form>
        )}

        <div style={s.footer}>
          <Link to="/register" style={s.link}>Create account</Link>
          <span style={{ color: '#334155' }}>·</span>
          <Link to="/forgot-password" style={s.link}>Forgot password</Link>
          <span style={{ color: '#334155' }}>·</span>
          <Link to="/status" style={s.link}>System Status</Link>
          <span style={{ color: '#334155' }}>·</span>
          <a href="mailto:support@hopefx.io" style={s.link}>Support</a>
        </div>
      </div>
      <style>{`
        @keyframes spin    { to { transform: rotate(360deg); } }
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
      `}</style>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'radial-gradient(ellipse at 50% 0%, rgba(59,130,246,0.06) 0%, #0f172a 60%)',
    padding: '20px',
  },
  card: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 16,
    padding: '40px 36px',
    width: '100%',
    maxWidth: 400,
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  },
  logoLink: {
    display: 'flex', alignItems: 'center', gap: 8,
    justifyContent: 'center', textDecoration: 'none', marginBottom: 4,
  },
  logoIcon: {
    width: 28, height: 28, borderRadius: 8,
    background: 'rgba(59,130,246,0.15)',
    border: '1px solid rgba(59,130,246,0.3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  logo:    { fontSize: 24, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  tagline: { fontSize: 13, color: '#64748b', textAlign: 'center', margin: '4px 0 28px' },
  form:    { display: 'flex', flexDirection: 'column', gap: 16 },
  field:   { display: 'flex', flexDirection: 'column' },
  label: {
    fontSize: 11, fontWeight: 700, color: '#94a3b8',
    textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6,
  },
  input: {
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 8,
    padding: '11px 14px',
    fontSize: 14,
    color: '#f8fafc',
    outline: 'none',
    transition: 'border-color 0.15s, box-shadow 0.15s',
    width: '100%',
    boxSizing: 'border-box',
  },
  eyeBtn: {
    position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
    background: 'none', border: 'none', cursor: 'pointer', padding: 4,
    display: 'flex', alignItems: 'center',
  },
  forgotLink: { fontSize: 12, color: '#60a5fa', textDecoration: 'none', fontWeight: 500 },
  totpHint:   { fontSize: 11, color: '#64748b', marginTop: 6 },
  error: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    background: 'rgba(248,113,113,0.08)',
    border: '1px solid rgba(248,113,113,0.25)',
    borderRadius: 8, padding: '10px 14px',
    fontSize: 13, color: '#f87171', lineHeight: 1.5,
  },
  btn: {
    background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
    color: '#fff', border: 'none', borderRadius: 8,
    padding: '13px', fontSize: 15, fontWeight: 700,
    cursor: 'pointer', marginTop: 4,
    transition: 'opacity 0.15s, transform 0.15s',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
  },
  footer: { display: 'flex', justifyContent: 'center', gap: 12, marginTop: 24, fontSize: 13 },
  link:   { color: '#64748b', textDecoration: 'none' },
};

export default Login;
