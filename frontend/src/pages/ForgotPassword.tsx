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
        <a href="/" style={s.logoLink}>
          <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
          <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        </a>

        {submitted ? (
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <div style={s.successIcon}>
              <CheckCircle2 size={32} color="#22c55e" />
            </div>
            <h2 style={s.heading}>Check your inbox</h2>
            <p style={s.subtext}>
              If an account exists for <strong style={{ color: '#94a3b8' }}>{email}</strong>,
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
                <label style={s.label} htmlFor="email">Email address</label>
                <input
                  id="email" type="email" value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(''); }}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  style={{
                    ...s.input,
                    borderColor: focused ? '#3b82f6' : '#334155',
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
    background: 'radial-gradient(ellipse at 50% 0%,rgba(59,130,246,0.06) 0%,#0f172a 60%)',
    padding: '20px',
  },
  card: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
    padding: '40px 36px', width: '100%', maxWidth: 400,
    boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
  },
  logoLink: { display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', textDecoration: 'none', marginBottom: 20 },
  logoIcon: {
    width: 28, height: 28, borderRadius: 8,
    background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  logo:        { fontSize: 24, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  successIcon: { display: 'flex', justifyContent: 'center', marginBottom: 16 },
  heading:     { fontSize: 20, fontWeight: 700, color: '#f1f5f9', textAlign: 'center', margin: '0 0 8px' },
  subtext:     { fontSize: 13, color: '#64748b', textAlign: 'center', lineHeight: 1.6, margin: '0 0 24px' },
  form:        { display: 'flex', flexDirection: 'column', gap: 16 },
  field:       { display: 'flex', flexDirection: 'column' },
  label:       { fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 },
  input: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '11px 14px', fontSize: 14, color: '#f8fafc', outline: 'none',
    transition: 'border-color 0.15s,box-shadow 0.15s', width: '100%', boxSizing: 'border-box',
  },
  error: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)',
    borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#f87171', lineHeight: 1.5,
  },
  btn: {
    background: 'linear-gradient(135deg,#3b82f6 0%,#2563eb 100%)',
    color: '#fff', border: 'none', borderRadius: 8, padding: '13px',
    fontSize: 15, fontWeight: 700, cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    transition: 'opacity 0.15s',
  },
  footer:   { display: 'flex', justifyContent: 'center', marginTop: 20 },
  backLink: { display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#64748b', textDecoration: 'none' },
  backBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    fontSize: 13, color: '#60a5fa', textDecoration: 'none', fontWeight: 500,
  },
};

export default ForgotPassword;
