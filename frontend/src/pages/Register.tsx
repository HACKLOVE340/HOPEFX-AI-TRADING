/**
 * Register page — account creation with plan pre-selection.
 * Linked from LandingPage via /register?plan=starter|pro|elite
 */

import React, { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useStore } from '../store';
import { authApi } from '../hooks/useApi';

// ── Plan badge ────────────────────────────────────────────────────────────────

const PLAN_LABELS: Record<string, { label: string; color: string }> = {
  starter: { label: 'Starter — Free',        color: '#22c55e' },
  pro:     { label: 'Pro — $49/mo',           color: '#3b82f6' },
  elite:   { label: 'Elite — $149/mo',        color: '#a855f7' },
};

// ── Component ─────────────────────────────────────────────────────────────────

const Register: React.FC = () => {
  const navigate       = useNavigate();
  const [params]       = useSearchParams();
  const plan           = params.get('plan') ?? 'starter';
  const refCode        = params.get('ref') ?? '';
  const setAuth        = useStore((s) => s.setAuth);

  const [email,    setEmail]    = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm,  setConfirm]  = useState('');
  const [error,    setError]    = useState('');
  const [success,  setSuccess]  = useState('');
  const [loading,  setLoading]  = useState(false);

  const planInfo = PLAN_LABELS[plan] ?? PLAN_LABELS.starter;

  const validate = (): string | null => {
    if (!email.trim())    return 'Email is required.';
    if (!email.includes('@')) return 'Enter a valid email address.';
    if (!username.trim()) return 'Username is required.';
    if (username.length < 3) return 'Username must be at least 3 characters.';
    if (!/^[a-zA-Z0-9_-]+$/.test(username))
      return 'Username may only contain letters, numbers, _ and -.';
    if (!password)        return 'Password is required.';
    if (password.length < 8) return 'Password must be at least 8 characters.';
    if (password !== confirm) return 'Passwords do not match.';
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) { setError(validationError); return; }

    setError('');
    setLoading(true);

    try {
      // 1. Register account
      await authApi.register({
        email:    email.trim().toLowerCase(),
        username: username.trim(),
        password,
      });

      // 2. Auto-assign free tier + track referral
      try {
        await authApi.activateFreeTier(username.trim(), refCode || undefined);
      } catch (tierErr: unknown) {
        // Non-fatal — tier activation can be retried on next login
        console.warn('[Register] Free tier activation failed (non-fatal):', tierErr);
      }

      // 3. Auto-login
      try {
        const loginRes = await authApi.login({ email: email.trim().toLowerCase(), password });
        setAuth(loginRes.data.access_token, loginRes.data.user);
        navigate('/dashboard', { replace: true });
        return;
      } catch (loginErr: unknown) {
        // Login failed after successful registration — fall through to success message
        console.warn('[Register] Auto-login after registration failed:', loginErr);
      }

      setSuccess('Account created! Redirecting to login…');
      setTimeout(() => navigate('/login'), 2000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail ?? 'Registration failed. Please try again.');
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
        <p style={s.tagline}>Create your free account</p>

        {/* Plan badge */}
        <div style={{ ...s.planBadge, borderColor: planInfo.color, color: planInfo.color }}>
          {planInfo.label}
        </div>

        {success ? (
          <div style={s.successBox}>{success}</div>
        ) : (
          <form onSubmit={handleSubmit} style={s.form} noValidate>
            <div style={s.field}>
              <label style={s.label} htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={s.input}
                placeholder="trader@example.com"
                autoComplete="email"
                autoFocus
              />
            </div>

            <div style={s.field}>
              <label style={s.label} htmlFor="username">Username</label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={s.input}
                placeholder="goldtrader99"
                autoComplete="username"
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
                placeholder="Min. 8 characters"
                autoComplete="new-password"
              />
            </div>

            <div style={s.field}>
              <label style={s.label} htmlFor="confirm">Confirm Password</label>
              <input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                style={s.input}
                placeholder="Repeat password"
                autoComplete="new-password"
              />
            </div>

            {refCode && (
              <div style={s.refBadge}>
                Referral code applied: <strong>{refCode}</strong>
              </div>
            )}

            {error && <div style={s.error}>{error}</div>}

            <button
              type="submit"
              style={{ ...s.btn, opacity: loading ? 0.7 : 1 }}
              disabled={loading}
            >
              {loading ? 'Creating account…' : 'Create Account'}
            </button>

            <p style={s.terms}>
              By registering you agree to our{' '}
              <a href="/terms" style={s.link}>Terms of Service</a> and{' '}
              <a href="/privacy" style={s.link}>Privacy Policy</a>.
              Paper trading is free — no credit card required.
            </p>
          </form>
        )}

        <div style={s.footer}>
          Already have an account?{' '}
          <Link to="/login" style={{ ...s.link, color: '#60a5fa' }}>Sign in →</Link>
        </div>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: '#0f172a', padding: '20px',
  },
  card: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
    padding: '40px 36px', width: '100%', maxWidth: 420,
    boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
  },
  logo:    { fontSize: 28, fontWeight: 800, color: '#f8fafc', textAlign: 'center', letterSpacing: -0.5 },
  tagline: { fontSize: 13, color: '#64748b', textAlign: 'center', margin: '4px 0 16px' },
  planBadge: {
    fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
    border: '1px solid', borderRadius: 20, padding: '4px 14px',
    width: 'fit-content', margin: '0 auto 24px',
    display: 'flex', justifyContent: 'center',
  } as React.CSSProperties,
  form:       { display: 'flex', flexDirection: 'column', gap: 14 },
  field:      { display: 'flex', flexDirection: 'column', gap: 6 },
  label:      { fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5 },
  input: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '10px 14px', fontSize: 14, color: '#f8fafc', outline: 'none',
  },
  error: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid rgba(248,113,113,0.3)',
    borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#f87171',
  },
  successBox: {
    background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)',
    borderRadius: 8, padding: '16px', fontSize: 14, color: '#22c55e',
    textAlign: 'center', lineHeight: 1.6,
  },
  refBadge: {
    background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)',
    borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#93c5fd',
  },
  btn: {
    background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8,
    padding: '12px', fontSize: 15, fontWeight: 600, cursor: 'pointer',
    marginTop: 4, transition: 'background 0.2s',
  },
  terms: { fontSize: 11, color: '#475569', textAlign: 'center', lineHeight: 1.6, margin: 0 },
  footer: { textAlign: 'center', marginTop: 20, fontSize: 13, color: '#64748b' },
  link:   { color: '#64748b', textDecoration: 'none' },
};

export default Register;
