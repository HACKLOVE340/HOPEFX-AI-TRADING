/**
 * Two-Factor Authentication setup page.
 *
 * Flow:
 *   1. Click "Enable 2FA" → backend generates TOTP secret + QR code
 *   2. User scans QR with Google Authenticator / Authy
 *   3. User enters 6-digit code → backend verifies and activates
 *   4. Show backup codes
 *   5. Disable 2FA option (requires current TOTP code)
 *
 * Wires to: POST /api/2fa/setup
 *           POST /api/2fa/verify
 *           POST /api/2fa/disable
 *           GET  /api/2fa/backup-codes/{user_id}
 *           GET  /api/2fa/status/{user_id}
 */

import React, { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { extractApiError } from '../lib/utils';

type Step = 'idle' | 'setup' | 'verify' | 'active' | 'backup';

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr_placeholder: string;
}

const TwoFactorSetup: React.FC = () => {
  const token  = useStore((s) => s.token);
  const user   = useStore((s) => s.user);
  const userId = user?.id ?? 'demo-user';

  const [step, setStep]             = useState<Step>('idle');
  const [setupData, setSetupData]   = useState<SetupData | null>(null);
  const [code, setCode]             = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [error, setError]           = useState('');
  const [loading, setLoading]       = useState(false);
  const [is2FAEnabled, set2FAEnabled] = useState(false);

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  // Check current 2FA status on mount
  useEffect(() => {
    fetch(`/api/2fa/status/${userId}`, { headers })
      .then((r) => r.json())
      .then((d) => set2FAEnabled(d.enabled ?? false))
      .catch(() => {});
  }, [userId]);

  const handleSetup = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/2fa/setup', {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSetupData(data);
      setStep('setup');
    } catch (e: unknown) {
      setError(extractApiError(e, 'Setup failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    if (code.length !== 6) { setError('Enter a 6-digit code'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/2fa/verify', {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, code }),
      });
      const data = await res.json();
      if (data.success) {
        set2FAEnabled(true);
        setStep('active');
        setCode('');
      } else {
        setError(data.message ?? 'Invalid code');
      }
    } catch (e: unknown) {
      setError(extractApiError(e, 'Verify failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleGetBackupCodes = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`/api/2fa/backup-codes/${userId}`, { headers });
      const data = await res.json();
      setBackupCodes(data.codes ?? []);
      setStep('backup');
    } catch (e: unknown) {
      setError(extractApiError(e, 'Failed to get backup codes'));
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    if (disableCode.length !== 6) { setError('Enter a 6-digit code'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/2fa/disable', {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: userId, code: disableCode }),
      });
      const data = await res.json();
      if (data.success) {
        set2FAEnabled(false);
        setStep('idle');
        setDisableCode('');
        setSetupData(null);
      } else {
        setError(data.message ?? 'Invalid code');
      }
    } catch (e: unknown) {
      setError(extractApiError(e, 'Disable failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>Two-Factor Authentication</h1>
        <p style={s.subtitle}>
          Add an extra layer of security to your account using an authenticator app.
        </p>
      </div>

      {/* Status banner */}
      <div style={{ ...s.statusBanner, background: is2FAEnabled ? '#14532d' : '#1e293b', borderColor: is2FAEnabled ? '#166534' : '#334155' }}>
        <span style={{ fontSize: 20 }}>{is2FAEnabled ? '🔒' : '🔓'}</span>
        <div>
          <div style={{ fontWeight: 600, color: is2FAEnabled ? '#4ade80' : '#94a3b8' }}>
            2FA is {is2FAEnabled ? 'ENABLED' : 'DISABLED'}
          </div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            {is2FAEnabled
              ? 'Your account is protected with TOTP authentication.'
              : 'Enable 2FA to protect your account from unauthorized access.'}
          </div>
        </div>
      </div>

      {error && <div style={s.errorBox}>{error}</div>}

      {/* ── IDLE: not enabled ── */}
      {!is2FAEnabled && step === 'idle' && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Enable Two-Factor Authentication</h2>
          <p style={s.cardText}>
            You'll need an authenticator app like <strong>Google Authenticator</strong> or{' '}
            <strong>Authy</strong>. After setup, you'll enter a 6-digit code each time you log in.
          </p>
          <button onClick={handleSetup} disabled={loading} style={s.btn}>
            {loading ? 'Setting up…' : 'Enable 2FA'}
          </button>
        </div>
      )}

      {/* ── SETUP: show QR code ── */}
      {step === 'setup' && setupData && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Scan QR Code</h2>
          <p style={s.cardText}>
            Open your authenticator app and scan this QR code, or enter the secret manually.
          </p>

          <div style={s.qrContainer}>
            <img
              src={setupData.qr_placeholder}
              alt="TOTP QR Code"
              style={{ width: 200, height: 200, borderRadius: 8 }}
            />
          </div>

          <div style={s.secretBox}>
            <span style={s.secretLabel}>Manual entry secret:</span>
            <code style={s.secretCode}>{setupData.secret}</code>
          </div>

          <label style={s.label}>Enter the 6-digit code from your app</label>
          <input
            type="text"
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            placeholder="000000"
            style={s.codeInput}
          />
          <button onClick={handleVerify} disabled={loading || code.length !== 6} style={{ ...s.btn, opacity: code.length !== 6 ? 0.5 : 1 }}>
            {loading ? 'Verifying…' : 'Verify & Activate'}
          </button>
        </div>
      )}

      {/* ── ACTIVE: 2FA just enabled ── */}
      {step === 'active' && (
        <div style={s.card}>
          <div style={s.successBanner}>
            <span style={{ fontSize: 24 }}>✅</span>
            <div>
              <div style={{ fontWeight: 700, color: '#4ade80' }}>2FA Activated!</div>
              <div style={{ fontSize: 13, color: '#94a3b8' }}>Your account is now protected.</div>
            </div>
          </div>
          <button onClick={handleGetBackupCodes} disabled={loading} style={{ ...s.btn, background: '#1d4ed8', marginTop: 16 }}>
            {loading ? 'Generating…' : 'Generate Backup Codes'}
          </button>
        </div>
      )}

      {/* ── BACKUP CODES ── */}
      {step === 'backup' && backupCodes.length > 0 && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Backup Codes</h2>
          <p style={s.cardText}>
            Save these codes somewhere safe. Each code can only be used once if you lose access to your authenticator app.
          </p>
          <div style={s.codesGrid}>
            {backupCodes.map((c, i) => (
              <code key={i} style={s.backupCode}>{c}</code>
            ))}
          </div>
          <button onClick={() => setStep('idle')} style={{ ...s.btn, background: '#334155', marginTop: 16 }}>
            Done
          </button>
        </div>
      )}

      {/* ── DISABLE 2FA ── */}
      {is2FAEnabled && step !== 'active' && step !== 'backup' && (
        <div style={{ ...s.card, borderColor: '#7f1d1d' }}>
          <h2 style={{ ...s.cardTitle, color: '#f87171' }}>Disable 2FA</h2>
          <p style={s.cardText}>Enter your current authenticator code to disable 2FA.</p>
          <label style={s.label}>Current TOTP code</label>
          <input
            type="text"
            inputMode="numeric"
            maxLength={6}
            value={disableCode}
            onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ''))}
            placeholder="000000"
            style={s.codeInput}
          />
          <button onClick={handleDisable} disabled={loading || disableCode.length !== 6} style={{ ...s.btn, background: '#dc2626', opacity: disableCode.length !== 6 ? 0.5 : 1 }}>
            {loading ? 'Disabling…' : 'Disable 2FA'}
          </button>
          {is2FAEnabled && (
            <button onClick={handleGetBackupCodes} disabled={loading} style={{ ...s.btn, background: '#1d4ed8', marginTop: 8 }}>
              View Backup Codes
            </button>
          )}
        </div>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:         { padding: 24, maxWidth: 600, margin: '0 auto' },
  header:       { marginBottom: 24 },
  title:        { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 8px' },
  subtitle:     { fontSize: 14, color: '#64748b', margin: 0 },
  statusBanner: { display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px', borderRadius: 10, border: '1px solid', marginBottom: 20 },
  card:         { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24, marginBottom: 16 },
  cardTitle:    { fontSize: 18, fontWeight: 700, color: '#f1f5f9', margin: '0 0 10px' },
  cardText:     { fontSize: 14, color: '#94a3b8', margin: '0 0 20px', lineHeight: 1.6 },
  btn:          { display: 'block', width: '100%', background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 15, fontWeight: 600, cursor: 'pointer', padding: '12px 0' },
  label:        { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6, fontWeight: 500 },
  codeInput:    { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '12px', fontSize: 24, textAlign: 'center', letterSpacing: 8, marginBottom: 16, boxSizing: 'border-box' },
  qrContainer:  { display: 'flex', justifyContent: 'center', margin: '16px 0' },
  secretBox:    { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, padding: '10px 14px', marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 4 },
  secretLabel:  { fontSize: 12, color: '#475569' },
  secretCode:   { fontSize: 14, color: '#60a5fa', letterSpacing: 2, wordBreak: 'break-all' },
  successBanner:{ display: 'flex', alignItems: 'center', gap: 14 },
  codesGrid:    { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, margin: '16px 0' },
  backupCode:   { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 6, padding: '8px 12px', fontSize: 14, color: '#94a3b8', textAlign: 'center', letterSpacing: 2 },
  errorBox:     { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '10px 14px', color: '#f87171', fontSize: 14, marginBottom: 16 },
};

export default TwoFactorSetup;
