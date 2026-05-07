/**
 * Register.tsx
 * Account creation with:
 * - Password strength indicator
 * - Show/hide password toggles
 * - Loading skeleton while submitting
 * - Granular validation error messages
 * - Plan pre-selection via ?plan= query param
 * - Referral code support via ?ref= query param
 */

import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useStore } from '../store';
import { authApi, prefetchCsrfToken } from '../hooks/useApi';
import { Eye, EyeOff, Activity, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';

// ── Plan badge ────────────────────────────────────────────────────────────────

const PLAN_LABELS: Record<string, { label: string; color: string }> = {
  starter:      { label: 'Starter — $1,800/mo',      color: '#22c55e' },
  professional: { label: 'Professional — $4,500/mo', color: '#3b82f6' },
  // legacy alias kept for URL backward-compat (?plan=pro)
  pro:          { label: 'Professional — $4,500/mo', color: '#3b82f6' },
  enterprise:   { label: 'Enterprise — $7,500/mo',   color: '#06b6d4' },
  elite:        { label: 'Elite — $10,000/mo',        color: '#a855f7' },
};

// ── Password strength ─────────────────────────────────────────────────────────

interface StrengthResult {
  score: number;   // 0–4
  label: string;
  color: string;
}

function measureStrength(pw: string): StrengthResult {
  if (!pw) return { score: 0, label: '', color: '#334155' };
  let score = 0;
  if (pw.length >= 8)  score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  score = Math.min(score, 4);
  const map: StrengthResult[] = [
    { score: 0, label: '',          color: '#334155' },
    { score: 1, label: 'Weak',      color: '#ef4444' },
    { score: 2, label: 'Fair',      color: '#f59e0b' },
    { score: 3, label: 'Good',      color: '#3b82f6' },
    { score: 4, label: 'Strong',    color: '#22c55e' },
  ];
  return map[score];
}

function PasswordStrengthBar({ password }: { password: string }) {
  const strength = useMemo(() => measureStrength(password), [password]);
  if (!password) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
        {[1, 2, 3, 4].map(i => (
          <div
            key={i}
            style={{
              flex: 1, height: 3, borderRadius: 2,
              background: i <= strength.score ? strength.color : '#1e293b',
              transition: 'background 0.2s',
            }}
          />
        ))}
      </div>
      {strength.label && (
        <span style={{ fontSize: 11, color: strength.color, fontWeight: 600 }}>
          {strength.label}
        </span>
      )}
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function shimBar(w: number | string, h: number, mb = 0): React.CSSProperties {
  return {
    width: w, height: h, marginBottom: mb, borderRadius: 6,
    background: 'linear-gradient(90deg,#1e293b 25%,#334155 50%,#1e293b 75%)',
    backgroundSize: '200% 100%',
    animation: 'shimmer 1.4s infinite',
  };
}

function SkeletonField() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div style={shimBar(60, 10, 8)} />
      <div style={shimBar('100%', 42)} />
    </div>
  );
}

// ── Error normaliser ──────────────────────────────────────────────────────────

function humaniseError(raw: string | undefined): string {
  if (!raw) return 'Registration failed. Please try again.';
  const l = raw.toLowerCase();
  if (l.includes('already') && l.includes('email'))
    return 'An account with this email already exists. Try logging in.';
  if (l.includes('already') && l.includes('username'))
    return 'That username is already taken. Please choose another.';
  if (l.includes('invalid email'))
    return 'Please enter a valid email address.';
  if (l.includes('password') && l.includes('short'))
    return 'Password must be at least 8 characters.';
  if (l.includes('rate limit') || l.includes('too many'))
    return 'Too many registration attempts. Please wait a minute.';
  return raw.length > 120 ? 'Registration failed. Please check your details and try again.' : raw;
}

// ── Component ─────────────────────────────────────────────────────────────────

const Register: React.FC = () => {
  const navigate       = useNavigate();
  const [params]       = useSearchParams();
  const plan           = params.get('plan') ?? 'starter';
  const refCode        = params.get('ref') ?? '';
  const setAuth        = useStore((s) => s.setAuth);

  const [email,     setEmail]     = useState('');
  const [username,  setUsername]  = useState('');
  const [password,  setPassword]  = useState('');
  const [confirm,   setConfirm]   = useState('');
  const [showPass,  setShowPass]  = useState(false);
  const [showConf,  setShowConf]  = useState(false);
  const [error,     setError]     = useState('');
  const [success,   setSuccess]   = useState('');
  const [loading,   setLoading]   = useState(false);
  const [focusField, setFocusField] = useState<string | null>(null);

  const planInfo = PLAN_LABELS[plan] ?? PLAN_LABELS.starter;

  useEffect(() => {
    const id = 'hopefx-shimmer';
    if (!document.getElementById(id)) {
      const st = document.createElement('style');
      st.id = id;
      st.textContent = '@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}';
      document.head.appendChild(st);
    }
    document.title = 'Create Account — HOPEFX';
    return () => { document.title = 'HOPEFX'; };
  }, []);

  const validate = (): string | null => {
    if (!email.trim())       return 'Email is required.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Please enter a valid email address.';
    if (!username.trim())    return 'Username is required.';
    if (username.length < 3) return 'Username must be at least 3 characters.';
    if (username.length > 30) return 'Username must be 30 characters or fewer.';
    if (!/^[a-zA-Z0-9_-]+$/.test(username))
      return 'Username may only contain letters, numbers, underscores, and hyphens.';
    if (!password)           return 'Password is required.';
    if (password.length < 8) return 'Password must be at least 8 characters.';
    if (password !== confirm) return 'Passwords do not match.';
    return null;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) { setError(validationError); return; }
    setError('');
    void _doRegister();
  };

  const handleButtonClick = () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError('');
    void _doRegister();
  };

  const _doRegister = async () => {
    setLoading(true);
    try {
      await authApi.register({
        email:    email.trim().toLowerCase(),
        username: username.trim(),
        password,
      });

      // Auto-login immediately after registration so we have the real user.id
      // (UUID) needed for activateFreeTier. The register endpoint only returns
      // {message} — it does not expose the user ID.
      try {
        const loginRes = await authApi.login({ email: email.trim().toLowerCase(), password });
        const { access_token, user } = loginRes.data;

        // Tokens are in httpOnly cookies set by the server.
        // Store access token in Zustand memory — axios interceptor reads it from there.
        setAuth(access_token, user);

        // Activate free tier using the real UUID from the login response.
        try {
          await authApi.activateFreeTier(user.id, refCode || undefined);
        } catch (tierErr: unknown) {
          console.warn('[Register] Free tier activation failed (non-fatal):', tierErr);
        }

        // Warm CSRF cache before navigating so the first POST after registration
        // (e.g. 2FA setup, onboarding) never races against a cold CSRF fetch.
        await prefetchCsrfToken();
        navigate('/dashboard', { replace: true });
        return;
      } catch (loginErr: unknown) {
        console.warn('[Register] Auto-login after registration failed:', loginErr);
      }

      setSuccess('Account created! Redirecting to login…');
      setTimeout(() => navigate('/login'), 2000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(humaniseError(detail));
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = (field: string): React.CSSProperties => ({
    ...s.input,
    border:    `1px solid ${focusField === field ? '#3b82f6' : '#334155'}`,
    boxShadow: focusField === field ? '0 0 0 3px rgba(59,130,246,0.15)' : 'none',
  });

  return (
    <div style={s.page}>
      <div style={s.card}>
        {/* Logo */}
        <Link to="/" style={s.logoLink}>
          <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
          <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        </Link>
        <p style={s.tagline}>Create your free account</p>

        {/* Plan badge */}
        <div style={{ ...s.planBadge, border: `1px solid ${planInfo.color}`, color: planInfo.color }}>
          {planInfo.label}
        </div>

        {success ? (
          <div style={s.successBox}>
            <CheckCircle2 size={18} style={{ flexShrink: 0 }} />
            <span>{success}</span>
          </div>
        ) : loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 8 }}>
            <SkeletonField />
            <SkeletonField />
            <SkeletonField />
            <SkeletonField />
            <div style={shimBar('100%', 46)} />
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={s.form} noValidate>
            {/* Email */}
            <div style={s.field}>
              <label style={s.label} htmlFor="email">Email</label>
              <input
                id="email" type="email" value={email}
                onChange={(e) => { setEmail(e.target.value); setError(''); }}
                onFocus={() => setFocusField('email')}
                onBlur={() => setFocusField(null)}
                style={inputStyle('email')}
                placeholder="trader@example.com"
                autoComplete="email" autoFocus
              />
            </div>

            {/* Username */}
            <div style={s.field}>
              <label style={s.label} htmlFor="username">Username</label>
              <input
                id="username" type="text" value={username}
                onChange={(e) => { setUsername(e.target.value); setError(''); }}
                onFocus={() => setFocusField('username')}
                onBlur={() => setFocusField(null)}
                style={inputStyle('username')}
                placeholder="goldtrader99"
                autoComplete="username"
              />
              {username && !/^[a-zA-Z0-9_-]+$/.test(username) && (
                <span style={s.fieldHint}>Only letters, numbers, _ and - allowed</span>
              )}
            </div>

            {/* Password */}
            <div style={s.field}>
              <label style={s.label} htmlFor="password">Password</label>
              <div style={{ position: 'relative' }}>
                <input
                  id="password"
                  type={showPass ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(''); }}
                  onFocus={() => setFocusField('password')}
                  onBlur={() => setFocusField(null)}
                  style={{ ...inputStyle('password'), paddingRight: 44 }}
                  placeholder="Min. 8 characters"
                  autoComplete="new-password"
                />
                <button
                  type="button" onClick={() => setShowPass(v => !v)}
                  style={s.eyeBtn} aria-label={showPass ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {showPass ? <EyeOff size={16} color="#64748b" /> : <Eye size={16} color="#64748b" />}
                </button>
              </div>
              <PasswordStrengthBar password={password} />
            </div>

            {/* Confirm password */}
            <div style={s.field}>
              <label style={s.label} htmlFor="confirm">Confirm Password</label>
              <div style={{ position: 'relative' }}>
                <input
                  id="confirm"
                  type={showConf ? 'text' : 'password'}
                  value={confirm}
                  onChange={(e) => { setConfirm(e.target.value); setError(''); }}
                  onFocus={() => setFocusField('confirm')}
                  onBlur={() => setFocusField(null)}
                  style={{
                    ...inputStyle('confirm'),
                    paddingRight: 44,
                    border: `1px solid ${
                      confirm && confirm !== password
                        ? 'rgba(248,113,113,0.5)'
                        : confirm && confirm === password
                          ? 'rgba(34,197,94,0.5)'
                          : focusField === 'confirm' ? '#3b82f6' : '#334155'
                    }`,
                  }}
                  placeholder="Repeat password"
                  autoComplete="new-password"
                />
                <button
                  type="button" onClick={() => setShowConf(v => !v)}
                  style={s.eyeBtn} aria-label={showConf ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {showConf ? <EyeOff size={16} color="#64748b" /> : <Eye size={16} color="#64748b" />}
                </button>
              </div>
              {confirm && confirm === password && (
                <span style={{ ...s.fieldHint, color: '#22c55e', marginTop: 4 }}>
                  ✓ Passwords match
                </span>
              )}
            </div>

            {/* Referral badge */}
            {refCode && (
              <div style={s.refBadge}>
                Referral code applied: <strong>{refCode}</strong>
              </div>
            )}

            {/* Error */}
            {error && (
              <div style={s.error} role="alert">
                <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                <span>{error}</span>
              </div>
            )}

            <button
              type="button"
              onClick={handleButtonClick}
              style={{ ...s.btn, opacity: loading ? 0.7 : 1 }}
              disabled={loading}
            >
              {loading
                ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Creating account…</>
                : 'Create Account'
              }
            </button>

            <p style={s.terms}>
              By registering you agree to our{' '}
              <Link to="/terms" style={s.link}>Terms of Service</Link> and{' '}
              <Link to="/privacy" style={s.link}>Privacy Policy</Link>.
              Paper trading is free — no credit card required.
            </p>
          </form>
        )}

        <div style={s.footer}>
          Already have an account?{' '}
          <Link to="/login" style={{ ...s.link, color: '#60a5fa' }}>Sign in →</Link>
        </div>
      </div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'radial-gradient(ellipse at 50% 0%,rgba(59,130,246,0.06) 0%,#0f172a 60%)',
    padding: 'clamp(12px, 4vw, 24px)',
  },
  card: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
    padding: 'clamp(20px, 6vw, 40px) clamp(16px, 5vw, 36px)',
    width: '100%', maxWidth: 440,
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  },
  logoLink: { display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', textDecoration: 'none', marginBottom: 4 },
  logoIcon: {
    width: 28, height: 28, borderRadius: 8,
    background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  },
  logo:    { fontSize: 24, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  tagline: { fontSize: 13, color: '#64748b', textAlign: 'center', margin: '4px 0 16px' },
  planBadge: {
    fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
    borderRadius: 20, padding: '4px 14px',
    width: 'fit-content', margin: '0 auto 24px',
    display: 'flex', justifyContent: 'center',
  } as React.CSSProperties,
  form:      { display: 'flex', flexDirection: 'column', gap: 14 },
  field:     { display: 'flex', flexDirection: 'column' },
  label:     { fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 },
  fieldHint: { fontSize: 11, color: '#64748b', marginTop: 4 },
  input: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '12px 14px',
    fontSize: 16, /* prevents iOS zoom on focus */
    color: '#f8fafc', outline: 'none',
    transition: 'border-color 0.15s,box-shadow 0.15s', width: '100%', boxSizing: 'border-box',
    WebkitAppearance: 'none',
  },
  eyeBtn: {
    position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
    background: 'none', border: 'none', cursor: 'pointer',
    minWidth: 44, minHeight: 44,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    touchAction: 'manipulation',
  },
  error: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)',
    borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#f87171', lineHeight: 1.5,
  },
  successBox: {
    display: 'flex', alignItems: 'center', gap: 10,
    background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)',
    borderRadius: 8, padding: '16px', fontSize: 14, color: '#22c55e',
    lineHeight: 1.6, marginBottom: 8,
  },
  refBadge: {
    background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.25)',
    borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#93c5fd',
  },
  btn: {
    background: 'linear-gradient(135deg,#3b82f6 0%,#2563eb 100%)',
    color: '#fff', border: 'none', borderRadius: 8, padding: '14px',
    fontSize: 15, fontWeight: 700, cursor: 'pointer', marginTop: 4,
    minHeight: 48, width: '100%',
    transition: 'opacity 0.15s',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    touchAction: 'manipulation',
  },
  terms:  { fontSize: 11, color: '#475569', textAlign: 'center', lineHeight: 1.6, margin: 0 },
  footer: { textAlign: 'center', marginTop: 20, fontSize: 13, color: '#64748b' },
  link:   { color: '#64748b', textDecoration: 'none', minHeight: 44, display: 'inline-flex', alignItems: 'center' },
};

export default Register;
