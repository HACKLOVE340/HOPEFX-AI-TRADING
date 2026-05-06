/**
 * TwoFactorSetup — TOTP 2FA management page.
 *
 * Flow:
 *   1. Click "Enable 2FA" → backend generates TOTP secret + QR URI
 *   2. User scans QR with Google Authenticator / Authy
 *   3. User enters 6-digit code → backend verifies and activates
 *   4. Show backup codes with download option
 *   5. Disable 2FA (requires current TOTP code)
 *
 * Wires to:
 *   POST /api/2fa/setup        — generate secret + QR URI
 *   POST /api/2fa/verify       — verify code and activate
 *   POST /api/2fa/disable      — disable 2FA
 *   GET  /api/2fa/backup-codes — generate one-time backup codes
 *   GET  /api/2fa/status       — check enabled state + codes remaining
 *
 * QR code is rendered inline via the otpauth_uri returned by the backend,
 * using the api.qrserver.com public service (same as backend). No external
 * library dependency required.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useStore } from '../store';
import { api, prefetchCsrfToken, resetCsrfCache } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';

// ── CSRF retry helper ─────────────────────────────────────────────────────────

async function withCsrfRetry<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 403) {
      resetCsrfCache();
      await prefetchCsrfToken();
      return fn();
    }
    throw err;
  }
}

// ── Types ─────────────────────────────────────────────────────────────────────

type Step = 'idle' | 'setup' | 'active' | 'backup';

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr_url: string;
}

interface StatusData {
  enabled: boolean;
  backup_codes_remaining: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractError(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (err as { message?: string })?.message ??
    fallback
  );
}

/** Build QR image URL from the otpauth URI returned by the backend. */
function buildQRUrl(otpauthUri: string): string {
  return (
    'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' +
    encodeURIComponent(otpauthUri) +
    '&bgcolor=1e293b&color=f1f5f9&margin=10'
  );
}

/** Download backup codes as a plain-text file. */
function downloadBackupCodes(codes: string[], userId: string): void {
  const lines = [
    'HOPEFX — 2FA Backup Codes',
    'Generated: ' + new Date().toISOString(),
    'Account: ' + userId,
    '',
    'Each code can only be used once.',
    'Store this file securely and delete it after printing.',
    '',
    ...codes.map((c, i) => (i + 1) + '. ' + c),
  ];
  const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = 'hopefx-backup-codes.txt';
  a.click();
  URL.revokeObjectURL(url);
}

/** Copy text to clipboard with a fallback for older browsers. */
async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

// ── Code input ────────────────────────────────────────────────────────────────

interface CodeInputProps {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

function CodeInput({ value, onChange, disabled, placeholder = '000000' }: CodeInputProps) {
  return (
    <input
      type="text"
      inputMode="numeric"
      maxLength={6}
      value={value}
      onChange={e => onChange(e.target.value.replace(/\D/g, ''))}
      placeholder={placeholder}
      disabled={disabled}
      style={{
        width: '100%', background: '#0f172a', border: '1px solid #334155',
        borderRadius: 8, color: '#f1f5f9', padding: '12px', fontSize: 28,
        textAlign: 'center', letterSpacing: 10, marginBottom: 16,
        boxSizing: 'border-box', fontFamily: 'monospace',
        opacity: disabled ? 0.5 : 1,
      }}
    />
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const TwoFactorSetup: React.FC = () => {
  const user = useStore(s => s.user);

  const [step, setStep]               = useState<Step>('idle');
  const [setupData, setSetupData]     = useState<SetupData | null>(null);
  const [status, setStatus]           = useState<StatusData>({ enabled: false, backup_codes_remaining: 0 });
  const [code, setCode]               = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [error, setError]             = useState('');
  const [loading, setLoading]         = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [qrError, setQrError]         = useState(false);
  const [featureDisabled, setFeatureDisabled] = useState(false);
  const qrRef = useRef<HTMLImageElement>(null);

  // Fetch 2FA status on mount
  useEffect(() => {
    api.get<StatusData>('/2fa/status')
      .then(r => setStatus({ enabled: r.data.enabled ?? false, backup_codes_remaining: r.data.backup_codes_remaining ?? 0 }))
      .catch((err: unknown) => {
        const s = (err as { response?: { status?: number } })?.response?.status;
        if (s === 404) setFeatureDisabled(true);
        else console.warn('[TwoFactorSetup] status fetch failed:', err);
      });
  }, []);

  const handleSetup = async () => {
    setLoading(true);
    setError('');
    setQrError(false);
    try {
      const res = await withCsrfRetry(() => api.post<SetupData>('/2fa/setup'));
      setSetupData(res.data);
      setStep('setup');
    } catch (e) {
      setError(extractError(e, 'Setup failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    if (code.length !== 6) { setError('Enter a 6-digit code'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await withCsrfRetry(() =>
        api.post<{ success: boolean; message?: string }>('/2fa/verify', { code })
      );
      if (res.data.success) {
        setStatus(s => ({ ...s, enabled: true }));
        setStep('active');
        setCode('');
      } else {
        setError(res.data.message ?? 'Invalid code. Please try again.');
      }
    } catch (e) {
      setError(extractError(e, 'Verification failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const handleGetBackupCodes = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get<{ codes: string[]; warning?: string }>('/2fa/backup-codes');
      setBackupCodes(res.data.codes ?? []);
      setStatus(s => ({ ...s, backup_codes_remaining: res.data.codes?.length ?? 0 }));
      setStep('backup');
    } catch (e) {
      setError(extractError(e, 'Failed to generate backup codes.'));
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    if (disableCode.length !== 6) { setError('Enter a 6-digit code'); return; }
    setLoading(true);
    setError('');
    try {
      const res = await withCsrfRetry(() =>
        api.post<{ success: boolean; message?: string }>('/2fa/disable', { code: disableCode })
      );
      if (res.data.success) {
        setStatus({ enabled: false, backup_codes_remaining: 0 });
        setStep('idle');
        setDisableCode('');
        setSetupData(null);
        setBackupCodes([]);
      } else {
        setError(res.data.message ?? 'Invalid code. Please try again.');
      }
    } catch (e) {
      setError(extractError(e, 'Disable failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const handleCopySecret = async () => {
    if (!setupData) return;
    await copyToClipboard(setupData.secret);
    setCopiedSecret(true);
    setTimeout(() => setCopiedSecret(false), 2500);
  };

  // ── Feature disabled state ────────────────────────────────────────────────
  if (featureDisabled) {
    return (
      <div style={s.page}>
        <PageHeader
          title="Two-Factor Authentication"
          subtitle="Secure your account with TOTP authentication."
          breadcrumbs={[
            { label: 'Dashboard', href: '/dashboard' },
            { label: 'Settings', href: '/settings' },
            { label: '2FA Setup' },
          ]}
        />
        <div style={{ ...s.card, textAlign: 'center', padding: '48px 32px' }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🔧</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 8 }}>
            2FA is not available
          </div>
          <div style={{ fontSize: 14, color: '#64748b', marginBottom: 24 }}>
            Two-factor authentication is not enabled on this instance.
            Contact your administrator to enable it.
          </div>
          <Link to="/settings" style={{
            display: 'inline-block', padding: '10px 24px', background: '#334155',
            color: '#e2e8f0', borderRadius: 8, textDecoration: 'none', fontSize: 14, fontWeight: 600,
          }}>
            Back to Settings
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div style={s.page}>
      <PageHeader
        title="Two-Factor Authentication"
        subtitle="Add an extra layer of security using an authenticator app."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Settings', href: '/settings' },
          { label: '2FA Setup' },
        ]}
        actions={
          <Link to="/settings" style={{
            fontSize: 13, color: '#64748b', textDecoration: 'none',
            padding: '6px 14px', border: '1px solid #334155', borderRadius: 6,
          }}>
            ← Settings
          </Link>
        }
      />

      {/* Status banner */}
      <div style={{
        ...s.statusBanner,
        background: status.enabled ? '#14532d' : '#1e293b',
        border: '1px solid ' + (status.enabled ? '#166534' : '#334155'),
      }}>
        <span style={{ fontSize: 22 }}>{status.enabled ? '🔒' : '🔓'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, color: status.enabled ? '#4ade80' : '#94a3b8' }}>
            2FA is {status.enabled ? 'ENABLED' : 'DISABLED'}
          </div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            {status.enabled
              ? 'Your account is protected with TOTP authentication.'
              : 'Enable 2FA to protect your account from unauthorized access.'}
          </div>
        </div>
        {status.enabled && status.backup_codes_remaining > 0 && (
          <div style={{ fontSize: 12, color: '#64748b', textAlign: 'right' }}>
            <div style={{ color: '#94a3b8', fontWeight: 600 }}>{status.backup_codes_remaining}</div>
            <div>backup codes</div>
          </div>
        )}
      </div>

      {error && (
        <div style={s.errorBox} role="alert">{error}</div>
      )}

      {/* ── IDLE ── */}
      {!status.enabled && step === 'idle' && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Enable Two-Factor Authentication</h2>
          <p style={s.cardText}>
            You'll need an authenticator app like{' '}
            <strong style={{ color: '#e2e8f0' }}>Google Authenticator</strong> or{' '}
            <strong style={{ color: '#e2e8f0' }}>Authy</strong>. After setup, you'll enter a
            6-digit code each time you log in.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            <a href="https://play.google.com/store/apps/details?id=com.google.android.apps.authenticator2"
              target="_blank" rel="noopener noreferrer" style={s.appLink}>
              Google Authenticator (Android)
            </a>
            <a href="https://apps.apple.com/app/google-authenticator/id388497605"
              target="_blank" rel="noopener noreferrer" style={s.appLink}>
              Google Authenticator (iOS)
            </a>
            <a href="https://authy.com/download/"
              target="_blank" rel="noopener noreferrer" style={s.appLink}>
              Authy
            </a>
          </div>
          <button onClick={handleSetup} disabled={loading} style={s.btn}>
            {loading ? 'Setting up…' : 'Enable 2FA'}
          </button>
        </div>
      )}

      {/* ── SETUP: QR code + manual entry ── */}
      {step === 'setup' && setupData && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Scan QR Code</h2>
          <p style={s.cardText}>
            Open your authenticator app and scan this QR code, or enter the secret manually.
          </p>

          {/* QR code */}
          <div style={s.qrContainer}>
            {!qrError ? (
              <img
                ref={qrRef}
                src={buildQRUrl(setupData.otpauth_uri)}
                alt="TOTP QR Code — scan with your authenticator app"
                style={{ width: 200, height: 200, borderRadius: 8, display: 'block' }}
                onError={() => setQrError(true)}
              />
            ) : (
              /* Fallback: show the otpauth URI as text when image fails */
              <div style={{
                width: 200, height: 200, background: '#0f172a', border: '1px solid #334155',
                borderRadius: 8, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', padding: 12, gap: 8,
              }}>
                <span style={{ fontSize: 32 }}>📷</span>
                <div style={{ fontSize: 11, color: '#64748b', textAlign: 'center' }}>
                  QR image unavailable — use manual entry below
                </div>
              </div>
            )}
          </div>

          {/* Manual secret */}
          <div style={s.secretBox}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={s.secretLabel}>Manual entry secret</span>
              <button onClick={handleCopySecret} style={s.copyBtn}>
                {copiedSecret ? '✅ Copied' : 'Copy'}
              </button>
            </div>
            <code style={s.secretCode}>{setupData.secret}</code>
          </div>

          {/* Issuer info */}
          <div style={{ fontSize: 12, color: '#475569', marginBottom: 20 }}>
            Issuer: <strong style={{ color: '#64748b' }}>HOPEFX</strong> ·
            Algorithm: SHA1 · Digits: 6 · Period: 30s
          </div>

          <label style={s.label}>Enter the 6-digit code from your app</label>
          <CodeInput value={code} onChange={setCode} disabled={loading} />
          <button
            onClick={handleVerify}
            disabled={loading || code.length !== 6}
            style={{ ...s.btn, opacity: code.length !== 6 ? 0.5 : 1 }}
          >
            {loading ? 'Verifying…' : 'Verify & Activate'}
          </button>
          <button onClick={() => { setStep('idle'); setSetupData(null); setCode(''); setError(''); }}
            style={{ ...s.btnSecondary, marginTop: 8 }}>
            Cancel
          </button>
        </div>
      )}

      {/* ── ACTIVE: just enabled ── */}
      {step === 'active' && (
        <div style={s.card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
            <span style={{ fontSize: 28 }}>✅</span>
            <div>
              <div style={{ fontWeight: 700, color: '#4ade80', fontSize: 16 }}>2FA Activated!</div>
              <div style={{ fontSize: 13, color: '#94a3b8' }}>Your account is now protected.</div>
            </div>
          </div>
          <p style={s.cardText}>
            Generate backup codes to regain access if you lose your authenticator device.
            Store them somewhere safe — each code can only be used once.
          </p>
          <button onClick={handleGetBackupCodes} disabled={loading}
            style={{ ...s.btn, background: '#1d4ed8' }}>
            {loading ? 'Generating…' : 'Generate Backup Codes'}
          </button>
          <button onClick={() => setStep('idle')} style={{ ...s.btnSecondary, marginTop: 8 }}>
            Skip for now
          </button>
        </div>
      )}

      {/* ── BACKUP CODES ── */}
      {step === 'backup' && backupCodes.length > 0 && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>Backup Codes</h2>
          <div style={{ background: '#451a03', border: '1px solid #92400e', borderRadius: 8,
            padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#fbbf24' }}>
            ⚠️ Save these codes now. They will not be shown again.
            Each code can only be used once.
          </div>
          <div style={s.codesGrid}>
            {backupCodes.map((c, i) => (
              <code key={i} style={s.backupCode}>{c}</code>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 20, flexWrap: 'wrap' }}>
            <button
              onClick={() => downloadBackupCodes(backupCodes, user?.id ?? user?.email ?? 'user')}
              style={{ ...s.btn, flex: 1, background: '#1d4ed8' }}
            >
              ⬇ Download codes
            </button>
            <button
              onClick={async () => {
                await copyToClipboard(backupCodes.join('\n'));
              }}
              style={{ ...s.btnSecondary, flex: 1 }}
            >
              Copy all
            </button>
          </div>
          <button onClick={() => setStep('idle')} style={{ ...s.btnSecondary, marginTop: 8, width: '100%' }}>
            Done
          </button>
        </div>
      )}

      {/* ── DISABLE 2FA ── */}
      {status.enabled && step !== 'active' && step !== 'backup' && (
        <div style={{ ...s.card, border: '1px solid #7f1d1d', marginTop: 8 }}>
          <h2 style={{ ...s.cardTitle, color: '#f87171' }}>Disable 2FA</h2>
          <p style={s.cardText}>
            Enter your current authenticator code to disable 2FA. This will remove all
            backup codes and your TOTP secret.
          </p>
          <label style={s.label}>Current TOTP code</label>
          <CodeInput value={disableCode} onChange={setDisableCode} disabled={loading} />
          <button
            onClick={handleDisable}
            disabled={loading || disableCode.length !== 6}
            style={{ ...s.btn, background: '#dc2626', opacity: disableCode.length !== 6 ? 0.5 : 1 }}
          >
            {loading ? 'Disabling…' : 'Disable 2FA'}
          </button>
          {status.enabled && (
            <button onClick={handleGetBackupCodes} disabled={loading}
              style={{ ...s.btnSecondary, marginTop: 8 }}>
              {loading ? 'Loading…' : 'View / Regenerate Backup Codes'}
            </button>
          )}
        </div>
      )}

      {/* Cross-links */}
      <div style={{ marginTop: 32, padding: '16px 0', borderTop: '1px solid #1e293b',
        display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        <Link to="/settings" style={s.crossLink}>← Account Settings</Link>
        <Link to="/profile" style={s.crossLink}>Profile</Link>
        <Link to="/dashboard" style={s.crossLink}>Dashboard</Link>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:         { padding: 24, maxWidth: 640, margin: '0 auto' },
  statusBanner: { display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px',
    borderRadius: 10, marginBottom: 20 },
  card:         { background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: 24, marginBottom: 16 },
  cardTitle:    { fontSize: 18, fontWeight: 700, color: '#f1f5f9', margin: '0 0 10px' },
  cardText:     { fontSize: 14, color: '#94a3b8', margin: '0 0 20px', lineHeight: 1.6 },
  btn:          { display: 'block', width: '100%', background: '#3b82f6', border: 'none',
    borderRadius: 8, color: '#fff', fontSize: 15, fontWeight: 600, cursor: 'pointer',
    padding: '12px 0', transition: 'opacity 0.15s' },
  btnSecondary: { display: 'block', width: '100%', background: '#334155', border: 'none',
    borderRadius: 8, color: '#94a3b8', fontSize: 14, fontWeight: 500, cursor: 'pointer',
    padding: '10px 0' },
  label:        { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6, fontWeight: 500 },
  qrContainer:  { display: 'flex', justifyContent: 'center', margin: '16px 0' },
  secretBox:    { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8,
    padding: '10px 14px', marginBottom: 16 },
  secretLabel:  { fontSize: 12, color: '#475569' },
  secretCode:   { fontSize: 13, color: '#60a5fa', letterSpacing: 2, wordBreak: 'break-all',
    display: 'block', marginTop: 4 },
  copyBtn:      { background: 'none', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', fontSize: 12, padding: '3px 10px', cursor: 'pointer' },
  codesGrid:    { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, margin: '16px 0' },
  backupCode:   { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 6,
    padding: '10px 12px', fontSize: 15, color: '#94a3b8', textAlign: 'center',
    letterSpacing: 3, fontFamily: 'monospace' },
  errorBox:     { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '10px 14px', color: '#f87171', fontSize: 14, marginBottom: 16 },
  appLink:      { fontSize: 12, color: '#60a5fa', textDecoration: 'none',
    padding: '4px 10px', border: '1px solid #1e3a5f', borderRadius: 6,
    background: '#0f172a' },
  crossLink:    { fontSize: 13, color: '#64748b', textDecoration: 'none' },
};

export default TwoFactorSetup;
