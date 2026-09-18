/**
 * ForgotPassword.tsx
 * Requests a password reset email via POST /api/auth/forgot-password.
 * Always shows a success message after submit to prevent email enumeration.
 */

import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Activity, AlertCircle, CheckCircle2, Loader2, ArrowLeft } from 'lucide-react';
import { authApi } from '../hooks/useApi';

const ForgotPassword: React.FC = () => {
  const [email,     setEmail]     = useState('');
  const [loading,   setLoading]   = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error,     setError]     = useState('');
  const [focused,   setFocused]   = useState(false);

  useEffect(() => {
    document.title = 'Reset Password — HOPEFX';
    return () => { document.title = 'HOPEFX'; };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) { setError('Email address is required.'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Please enter a valid email address.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await authApi.forgotPassword(email.trim().toLowerCase());
    } catch {
      // Swallow errors — always show success to prevent enumeration
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  };

  return (
    <div style={s.page}>
      <div style={s.card}>
        {/* Logo */}
        <Link to="/" style={s.logoLink}>
          <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
          <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        </Link>

        {submitted ? (
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <div style={s.successIcon}>
              <CheckCircle2 size={32} color="#22c55e" />
            </div>
            <h2 style={s.heading}>Check your inbox</h2>
            <p style={s.subtext}>
              If an account exists for <strong style={{ color: 'var(--text-dim)' }}>{email}</strong>,
              you'll receive a password reset link within a few minutes.
              Check your spam folder if it doesn't arrive.
            </p>
            <Link to="/login" style={s.backBtn}>
              <ArrowLeft size={14} /> Back to sign in
            </Link>
          </div>
        ) : (
          <>
            <h2 style={s.heading}>Reset your password</h2>
            <p style={s.subtext}>
              Enter your account email and we'll send you a reset link.
            </p>

            <form onSubmit={handleSubmit} style={s.form} noValidate>
              <div style={s.field}>
                <label id="email-label" style={s.label} htmlFor="email">Email address</label>
                <input aria-labelledby="email-label"
                  id="email" type="email" value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(''); }}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  style={{
                    ...s.input,
                    border:    `1px solid ${focused ? '#3b82f6' : '#334155'}`,
                    boxShadow: focused ? '0 0 0 3px rgba(59,130,246,0.15)' : 'none',
                  }}
                  placeholder="trader@hopefx.io"
                  autoComplete="email" autoFocus disabled={loading}
                />
              </div>

              {error && (
                <div style={s.error} role="alert">
                  <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>{error}</span>
                </div>
              )}

              <button type="submit" style={{ ...s.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>
                {loading
                  ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Sending…</>
                  : 'Send reset link'
                }
              </button>
            </form>

            <div style={s.footer}>
              <Link to="/login" style={s.backLink}>
                <ArrowLeft size={12} /> Back to sign in
              </Link>
            </div>
          </>
        )}
      </div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'radial-gradient(ellipse at 50% 0%,rgba(59,130,246,0.06) 0%,var(--surface) 60%)',
    padding: 'clamp(12px, 4vw, 24px)',
  },
  card: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 16,
    padding: 'clamp(20px, 6vw, 40px) clamp(16px, 5vw, 36px)',
    width: '100%', maxWidth: 420,
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  },
  logoLink: { display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', textDecoration: 'none', marginBottom: 20 },
  logoIcon: {
    width: 28, height: 28, borderRadius: 8,
    background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  },
  logo:        { fontSize: 24, fontWeight: 800, color: 'var(--text-strong)', letterSpacing: -0.5 },
  successIcon: { display: 'flex', justifyContent: 'center', marginBottom: 16 },
  heading:     { fontSize: 20, fontWeight: 700, color: 'var(--text-strong)', textAlign: 'center', margin: '0 0 8px' },
  subtext:     { fontSize: 'var(--fs-body)', color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.6, margin: '0 0 24px' },
  form:        { display: 'flex', flexDirection: 'column', gap: 16 },
  field:       { display: 'flex', flexDirection: 'column' },
  label:       { fontSize: 'var(--fs-label)', fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 },
  input: {
    background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 8,
    padding: '12px 14px', fontSize: 16, /* prevents iOS zoom */
    color: 'var(--text-strong)', outline: 'none',
    transition: 'border-color 0.15s,box-shadow 0.15s', width: '100%', boxSizing: 'border-box',
    WebkitAppearance: 'none',
  },
  error: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)',
    borderRadius: 8, padding: '10px 14px', fontSize: 'var(--fs-body)', color: 'var(--loss)', lineHeight: 1.5,
  },
  btn: {
    background: 'linear-gradient(135deg,#3b82f6 0%,#2563eb 100%)',
    color: '#fff', border: 'none', borderRadius: 8, padding: '14px',
    fontSize: 'var(--fs-value)', fontWeight: 700, cursor: 'pointer',
    minHeight: 48, width: '100%',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    transition: 'opacity 0.15s', touchAction: 'manipulation',
  },
  footer:   { display: 'flex', justifyContent: 'center', marginTop: 20 },
  backLink: { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 'var(--fs-body)', color: 'var(--text-muted)', textDecoration: 'none', minHeight: 44 },
  backBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 44,
    fontSize: 'var(--fs-body)', color: 'var(--link)', textDecoration: 'none', fontWeight: 500,
  },
};

export default ForgotPassword;
