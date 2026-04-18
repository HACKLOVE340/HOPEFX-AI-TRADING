/**
 * ResetPassword.tsx
 * Sets a new password using the token from the reset email link.
 * URL format: /reset-password?token=<jwt>
 */

import React, { useState, useEffect } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { Activity, AlertCircle, CheckCircle2, Loader2, Eye, EyeOff, ArrowLeft } from 'lucide-react';
import { authApi } from '../hooks/useApi';

function measureStrength(pw: string): { score: number; label: string; color: string } {
  if (!pw) return { score: 0, label: '', color: '#334155' };
  let score = 0;
  if (pw.length >= 8)  score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  score = Math.min(score, 4);
  const map = [
    { score: 0, label: '',       color: '#334155' },
    { score: 1, label: 'Weak',   color: '#ef4444' },
    { score: 2, label: 'Fair',   color: '#f59e0b' },
    { score: 3, label: 'Good',   color: '#3b82f6' },
    { score: 4, label: 'Strong', color: '#22c55e' },
  ];
  return map[score];
}

const ResetPassword: React.FC = () => {
  const [params]    = useSearchParams();
  const navigate    = useNavigate();
  const token       = params.get('token') ?? '';

  const [password,  setPassword]  = useState('');
  const [confirm,   setConfirm]   = useState('');
  const [showPass,  setShowPass]  = useState(false);
  const [showConf,  setShowConf]  = useState(false);
  const [loading,   setLoading]   = useState(false);
  const [success,   setSuccess]   = useState(false);
  const [error,     setError]     = useState('');
  const [focusField, setFocusField] = useState<string | null>(null);

  const strength = measureStrength(password);

  useEffect(() => {
    document.title = 'Set New Password — HOPEFX';
    return () => { document.title = 'HOPEFX'; };
  }, []);

  // No token in URL — show error immediately
  if (!token) {
    return (
      <div style={s.page}>
        <div style={s.card}>
          <a href="/" style={s.logoLink}>
            <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
            <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
          </a>
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
              <AlertCircle size={32} color="#f87171" />
            </div>
            <h2 style={s.heading}>Invalid reset link</h2>
            <p style={s.subtext}>
              This password reset link is missing or invalid.
              Please request a new one.
            </p>
            <Link to="/forgot-password" style={s.btn as React.CSSProperties}>
              Request new link
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password)           { setError('New password is required.'); return; }
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return; }
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    setError('');
    setLoading(true);
    try {
      await authApi.resetPassword(token, password);
      setSuccess(true);
      setTimeout(() => navigate('/login'), 3000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const msg = detail?.toLowerCase() ?? '';
      if (msg.includes('expired') || msg.includes('invalid'))
        setError('This reset link has expired or already been used. Please request a new one.');
      else
        setError(detail ?? 'Failed to reset password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = (field: string): React.CSSProperties => ({
    ...s.input,
    borderColor: focusField === field ? '#3b82f6' : '#334155',
    boxShadow:   focusField === field ? '0 0 0 3px rgba(59,130,246,0.15)' : 'none',
  });

  return (
    <div style={s.page}>
      <div style={s.card}>
        <a href="/" style={s.logoLink}>
          <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
          <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        </a>

        {success ? (
          <div style={{ textAlign: 'center', padding: '8px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
              <CheckCircle2 size={32} color="#22c55e" />
            </div>
            <h2 style={s.heading}>Password updated</h2>
            <p style={s.subtext}>
              Your password has been changed successfully.
              Redirecting to sign in…
            </p>
            <Link to="/login" style={s.backLink}>
              <ArrowLeft size={12} /> Sign in now
            </Link>
          </div>
        ) : (
          <>
            <h2 style={s.heading}>Set new password</h2>
            <p style={s.subtext}>Choose a strong password for your account.</p>

            <form onSubmit={handleSubmit} style={s.form} noValidate>
              {/* New password */}
              <div style={s.field}>
                <label style={s.label} htmlFor="password">New password</label>
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
                    autoComplete="new-password" autoFocus
                  />
                  <button type="button" onClick={() => setShowPass(v => !v)} style={s.eyeBtn} tabIndex={-1}
                    aria-label={showPass ? 'Hide password' : 'Show password'}>
                    {showPass ? <EyeOff size={16} color="#64748b" /> : <Eye size={16} color="#64748b" />}
                  </button>
                </div>
                {/* Strength bar */}
                {password && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                      {[1,2,3,4].map(i => (
                        <div key={i} style={{
                          flex: 1, height: 3, borderRadius: 2,
                          background: i <= strength.score ? strength.color : '#1e293b',
                          transition: 'background 0.2s',
                        }} />
                      ))}
                    </div>
                    {strength.label && <span style={{ fontSize: 11, color: strength.color, fontWeight: 600 }}>{strength.label}</span>}
                  </div>
                )}
              </div>

              {/* Confirm */}
              <div style={s.field}>
                <label style={s.label} htmlFor="confirm">Confirm new password</label>
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
                      borderColor: confirm && confirm !== password
                        ? 'rgba(248,113,113,0.5)'
                        : confirm && confirm === password
                          ? 'rgba(34,197,94,0.5)'
                          : focusField === 'confirm' ? '#3b82f6' : '#334155',
                    }}
                    placeholder="Repeat password"
                    autoComplete="new-password"
                  />
                  <button type="button" onClick={() => setShowConf(v => !v)} style={s.eyeBtn} tabIndex={-1}
                    aria-label={showConf ? 'Hide password' : 'Show password'}>
                    {showConf ? <EyeOff size={16} color="#64748b" /> : <Eye size={16} color="#64748b" />}
                  </button>
                </div>
                {confirm && confirm === password && (
                  <span style={{ fontSize: 11, color: '#22c55e', marginTop: 4 }}>✓ Passwords match</span>
                )}
              </div>

              {error && (
                <div style={s.error} role="alert">
                  <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>{error}</span>
                </div>
              )}

              <button type="submit" style={{ ...s.btn, opacity: loading ? 0.7 : 1 }} disabled={loading}>
                {loading
                  ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Updating…</>
                  : 'Update password'
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
  logo:    { fontSize: 24, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  heading: { fontSize: 20, fontWeight: 700, color: '#f1f5f9', textAlign: 'center', margin: '0 0 8px' },
  subtext: { fontSize: 13, color: '#64748b', textAlign: 'center', lineHeight: 1.6, margin: '0 0 24px' },
  form:    { display: 'flex', flexDirection: 'column', gap: 16 },
  field:   { display: 'flex', flexDirection: 'column' },
  label:   { fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 },
  input: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '11px 14px', fontSize: 14, color: '#f8fafc', outline: 'none',
    transition: 'border-color 0.15s,box-shadow 0.15s', width: '100%', boxSizing: 'border-box',
  },
  eyeBtn: {
    position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
    background: 'none', border: 'none', cursor: 'pointer', padding: 4,
    display: 'flex', alignItems: 'center',
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
    transition: 'opacity 0.15s', textDecoration: 'none',
  },
  footer:   { display: 'flex', justifyContent: 'center', marginTop: 20 },
  backLink: { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#64748b', textDecoration: 'none' },
};

export default ResetPassword;
