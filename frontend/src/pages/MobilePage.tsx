/**
 * Mobile App — download links, QR codes, push-token registration, and active sessions.
 *
 * Wires to:
 *   GET    /api/mobile/config         — mobile app config (version, links, features)
 *   POST   /api/mobile/push-token     — register push notification token
 *   GET    /api/mobile/sessions       — active mobile sessions
 *   DELETE /api/mobile/sessions/:id   — revoke mobile session
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/Badge';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { EmptyState } from '../components/EmptyState';

interface MobileConfig {
  ios_version: string;
  android_version: string;
  ios_url: string;
  android_url: string;
  qr_ios: string;
  qr_android: string;
  features: string[];
}

interface MobileSession {
  session_id: string;
  device_name: string;
  device_os: string;
  last_active: string;
  ip_address: string;
  is_current?: boolean;
}

const DEFAULT_FEATURES = [
  'Live price alerts',
  'One-tap trade execution',
  'Real-time P&L tracking',
  'AI signal notifications',
  'Biometric authentication',
  'Portfolio overview',
  'Copy trading management',
  'Secure 2FA push approval',
];

// ── Platform download card ────────────────────────────────────────────────────

interface PlatformCardProps {
  platform: 'ios' | 'android';
  version: string;
  url: string;
  qr: string;
  loading: boolean;
}

const PlatformCard: React.FC<PlatformCardProps> = ({ platform, version, url, qr, loading }) => {
  const isIos = platform === 'ios';
  return (
    <div style={{
      background: '#0d1421', border: '1px solid #1e293b',
      borderRadius: 14, padding: '28px 24px', textAlign: 'center',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0,
    }}>
      <div style={{ fontSize: 52, marginBottom: 12 }}>{isIos ? '🍎' : '🤖'}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>
        {isIos ? 'iOS App' : 'Android App'}
      </div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 18 }}>
        {loading ? '…' : `v${version || 'N/A'}`} · {isIos ? 'iPhone & iPad' : 'Android 8+'}
      </div>

      {/* QR code */}
      <div style={{
        width: 128, height: 128, borderRadius: 10, marginBottom: 18,
        background: qr ? '#fff' : '#1e293b',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'hidden', padding: qr ? 4 : 0,
      }}>
        {qr
          ? <img src={qr} alt={`${platform} QR`} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
          : <span style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: 8 }}>QR code<br />available<br />after login</span>
        }
      </div>

      <a
        href={url || '#'}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => { if (!url) e.preventDefault(); }}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          width: '100%', background: isIos ? '#1c1c1e' : '#0f3460',
          border: `1px solid ${isIos ? '#3a3a3c' : '#1a5276'}`,
          borderRadius: 10, color: '#f1f5f9', fontSize: 13, fontWeight: 600,
          padding: '11px 0', textDecoration: 'none',
          opacity: url ? 1 : 0.5, cursor: url ? 'pointer' : 'not-allowed',
        }}
      >
        <span style={{ fontSize: 16 }}>{isIos ? '⬇' : '⬇'}</span>
        {isIos ? 'Download on App Store' : 'Get it on Google Play'}
      </a>
    </div>
  );
};

// ── Session row ───────────────────────────────────────────────────────────────

const SessionRow: React.FC<{
  session: MobileSession;
  revoking: boolean;
  onRevoke: () => void;
}> = ({ session, revoking, onRevoke }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 14,
    padding: '12px 0', borderBottom: '1px solid #1e293b',
  }}>
    <div style={{
      width: 38, height: 38, borderRadius: 10,
      background: '#1e293b', border: '1px solid #334155',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 18, flexShrink: 0,
    }}>
      {session.device_os?.toLowerCase().includes('ios') ? '📱' : '🤖'}
    </div>
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9', display: 'flex', alignItems: 'center', gap: 8 }}>
        {session.device_name || 'Unknown Device'}
        {session.is_current && (
          <span style={{ fontSize: 10, color: '#4ade80', background: '#14532d', border: '1px solid #166534', borderRadius: 4, padding: '1px 6px', fontWeight: 700 }}>
            Current
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <span>{session.device_os}</span>
        <span>IP: {session.ip_address}</span>
        <span>Last active: {new Date(session.last_active).toLocaleString()}</span>
      </div>
    </div>
    <button
      onClick={onRevoke}
      disabled={revoking || session.is_current}
      title={session.is_current ? 'Cannot revoke current session' : 'Revoke this session'}
      style={{
        background: 'transparent',
        border: `1px solid ${session.is_current ? '#1e293b' : '#7f1d1d'}`,
        borderRadius: 7, color: session.is_current ? '#334155' : '#f87171',
        cursor: session.is_current ? 'not-allowed' : 'pointer',
        fontSize: 12, padding: '5px 12px', flexShrink: 0,
        display: 'flex', alignItems: 'center', gap: 5,
      }}
    >
      {revoking ? <Spinner size="sm" /> : 'Revoke'}
    </button>
  </div>
);

// ── Cross-link card ───────────────────────────────────────────────────────────

const CrossLinkCard: React.FC<{ icon: string; label: string; desc: string; to: string }> = ({ icon, label, desc, to }) => (
  <Link
    to={to}
    style={{
      display: 'flex', alignItems: 'center', gap: 12,
      background: '#0d1421', border: '1px solid #1e293b',
      borderRadius: 10, padding: '12px 16px', textDecoration: 'none',
    }}
    onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
    onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
  >
    <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
    </div>
    <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
  </Link>
);

// ── Main component ────────────────────────────────────────────────────────────

const MobilePage: React.FC = () => {
  const [config, setConfig]       = useState<MobileConfig | null>(null);
  const [sessions, setSessions]   = useState<MobileSession[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [revoking, setRevoking]   = useState<string | null>(null);
  const [pushToken, setPushToken] = useState('');
  const [tokenMsg, setTokenMsg]   = useState('');
  const [tokenOk, setTokenOk]     = useState(false);
  const [registering, setRegistering] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [cfgRes, sessRes] = await Promise.allSettled([
        api.get<MobileConfig>('/mobile/config'),
        api.get<MobileSession[] | { sessions?: MobileSession[] }>('/mobile/sessions'),
      ]);
      if (!mountedRef.current) return;
      if (cfgRes.status === 'fulfilled') setConfig(cfgRes.value.data);
      if (sessRes.status === 'fulfilled') {
        const d = sessRes.value.data;
        setSessions(Array.isArray(d) ? d : (d.sessions ?? []));
      }
    } catch {
      if (!mountedRef.current) return;
      setError('Failed to load mobile configuration.');
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRevoke = async (sessionId: string) => {
    setRevoking(sessionId);
    try {
      await api.delete(`/mobile/sessions/${sessionId}`);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
    } catch { /* non-fatal */ }
    finally { setRevoking(null); }
  };

  const handleRegisterPushToken = async () => {
    if (!pushToken.trim()) return;
    setRegistering(true);
    setTokenMsg('');
    setTokenOk(false);
    try {
      await api.post('/mobile/push-token', { token: pushToken.trim(), platform: 'web' });
      setTokenMsg('Push token registered successfully.');
      setTokenOk(true);
      setPushToken('');
    } catch {
      setTokenMsg('Failed to register push token. Please try again.');
      setTokenOk(false);
    } finally { setRegistering(false); }
  };

  const features: string[] = Array.isArray(config?.features) && config!.features.length > 0
    ? config!.features
    : DEFAULT_FEATURES;

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 20px' }}>
      <PageHeader
        title="Mobile App"
        subtitle="Trade on the go with the HOPEFX mobile app for iOS and Android."
        breadcrumbs={[
          { label: 'Home',    href: '/home' },
          { label: 'Account', href: '/profile' },
          { label: 'Mobile App' },
        ]}
        badge={<Badge variant="info" style={{ fontSize: 11 }}>📱 Available Now</Badge>}
        actions={
          <button
            onClick={load}
            disabled={loading}
            style={{
              background: 'transparent', border: '1px solid #334155',
              borderRadius: 8, color: '#94a3b8', cursor: 'pointer',
              fontSize: 12, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {loading ? <Spinner size="sm" /> : '↻'} Refresh
          </button>
        }
      />

      {error && <ErrorBanner message={error} style={{ marginBottom: 20 }} />}

      {/* Download cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16, marginBottom: 28 }}>
        <PlatformCard
          platform="ios"
          version={config?.ios_version ?? ''}
          url={config?.ios_url ?? ''}
          qr={config?.qr_ios ?? ''}
          loading={loading}
        />
        <PlatformCard
          platform="android"
          version={config?.android_version ?? ''}
          url={config?.android_url ?? ''}
          qr={config?.qr_android ?? ''}
          loading={loading}
        />
      </div>

      {/* Features */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>⚡</span> Mobile Features
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {features.map(f => (
            <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#94a3b8' }}>
              <span style={{
                width: 20, height: 20, borderRadius: '50%',
                background: '#14532d', border: '1px solid #166534',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, color: '#4ade80', flexShrink: 0, fontWeight: 700,
              }}>✓</span>
              {f}
            </div>
          ))}
        </div>
      </div>

      {/* Push token registration */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>🔔</span> Push Notifications
        </h3>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 16px', lineHeight: 1.5 }}>
          Register a device push token to receive trade alerts, signal notifications, and account updates on your mobile device.
        </p>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            type="text"
            value={pushToken}
            onChange={e => setPushToken(e.target.value)}
            placeholder="Paste device push token…"
            style={{
              flex: 1, background: '#111827', border: '1px solid #334155',
              borderRadius: 8, color: '#f1f5f9', fontSize: 13, padding: '9px 14px',
              outline: 'none', fontFamily: 'JetBrains Mono, monospace',
            }}
            onKeyDown={e => { if (e.key === 'Enter') handleRegisterPushToken(); }}
          />
          <button
            onClick={handleRegisterPushToken}
            disabled={registering || !pushToken.trim()}
            style={{
              background: pushToken.trim() ? '#1d4ed8' : '#1e293b',
              border: `1px solid ${pushToken.trim() ? '#3b82f6' : '#334155'}`,
              borderRadius: 8, color: pushToken.trim() ? '#93c5fd' : '#475569',
              cursor: pushToken.trim() ? 'pointer' : 'not-allowed',
              fontSize: 13, fontWeight: 600, padding: '9px 18px',
              display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
            }}
          >
            {registering ? <Spinner size="sm" /> : 'Register'}
          </button>
        </div>
        {tokenMsg && (
          <div style={{
            marginTop: 10, fontSize: 12, padding: '8px 12px', borderRadius: 7,
            background: tokenOk ? '#052e16' : '#450a0a',
            border: `1px solid ${tokenOk ? '#166534' : '#7f1d1d'}`,
            color: tokenOk ? '#4ade80' : '#f87171',
          }}>
            {tokenMsg}
          </div>
        )}
      </div>

      {/* Active sessions */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px', marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📲</span> Active Mobile Sessions
          </h3>
          {sessions.length > 0 && (
            <span style={{ fontSize: 12, color: '#64748b' }}>{sessions.length} device{sessions.length !== 1 ? 's' : ''}</span>
          )}
        </div>

        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0', color: '#64748b', gap: 10 }}>
            <Spinner size="sm" /> Loading sessions…
          </div>
        ) : sessions.length === 0 ? (
          <EmptyState
            icon="📱"
            title="No active mobile sessions"
            description="Download the app and sign in to see your active mobile sessions here."
          />
        ) : (
          <div>
            {sessions.map(sess => (
              <SessionRow
                key={sess.session_id}
                session={sess}
                revoking={revoking === sess.session_id}
                onRevoke={() => handleRevoke(sess.session_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          <CrossLinkCard icon="🔐" label="Security"       desc="2FA and session management"     to="/settings?tab=security" />
          <CrossLinkCard icon="🔔" label="Notifications"  desc="Alert preferences"              to="/notifications" />
          <CrossLinkCard icon="👤" label="Profile"        desc="Account information"            to="/profile" />
          <CrossLinkCard icon="⚙️" label="Settings"       desc="Account preferences"            to="/settings" />
        </div>
      </div>
    </div>
  );
};

export default MobilePage;
