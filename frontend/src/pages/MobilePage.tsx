/**
 * Mobile App — download links, QR codes, and mobile-specific settings.
 *
 * Wires to:
 *   GET  /api/mobile/config         — mobile app config (version, links)
 *   POST /api/mobile/push-token     — register push notification token
 *   GET  /api/mobile/sessions       — active mobile sessions
 *   DELETE /api/mobile/sessions/:id — revoke mobile session
 */
import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../hooks/useApi';

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
}

const MobilePage: React.FC = () => {
  const [config, setConfig]       = useState<MobileConfig | null>(null);
  const [sessions, setSessions]   = useState<MobileSession[]>([]);
  const [loading, setLoading]     = useState(true);
  const [revoking, setRevoking]   = useState<string | null>(null);
  const [pushToken, setPushToken] = useState('');
  const [tokenMsg, setTokenMsg]   = useState('');
  const [registering, setRegistering] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgRes, sessRes] = await Promise.allSettled([
        api.get<MobileConfig>('/mobile/config'),
        api.get<MobileSession[] | { sessions?: MobileSession[] }>('/mobile/sessions'),
      ]);
      if (cfgRes.status === 'fulfilled') setConfig(cfgRes.value.data);
      if (sessRes.status === 'fulfilled') {
        const d = sessRes.value.data;
        setSessions(Array.isArray(d) ? d : (d.sessions ?? []));
      }
    } catch { /* non-fatal */ }
    finally { setLoading(false); }
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
    try {
      await api.post('/mobile/push-token', { token: pushToken.trim(), platform: 'web' });
      setTokenMsg('Push token registered successfully.');
      setPushToken('');
    } catch {
      setTokenMsg('Failed to register push token.');
    } finally { setRegistering(false); }
  };

  const FEATURES = config?.features ?? [
    'Live price alerts',
    'One-tap trade execution',
    'Real-time P&L tracking',
    'AI signal notifications',
    'Biometric authentication',
    'Portfolio overview',
    'Copy trading management',
    'Secure 2FA push approval',
  ];

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: '#f1f5f9', margin: 0 }}>📱 Mobile App</h1>
        <p style={{ fontSize: 13, color: '#64748b', margin: '6px 0 0' }}>
          Trade on the go with the HOPEFX mobile app for iOS and Android.
        </p>
      </div>

      {/* Download cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 28 }}>
        {/* iOS */}
        <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '24px 20px', textAlign: 'center' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🍎</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>iOS App</div>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>
            Version {loading ? '…' : (config?.ios_version ?? 'N/A')} · iPhone & iPad
          </div>
          {config?.qr_ios && (
            <img src={config.qr_ios} alt="iOS QR" style={{ width: 120, height: 120, borderRadius: 8, marginBottom: 14, background: '#fff', padding: 4 }} />
          )}
          {!config?.qr_ios && (
            <div style={{ width: 120, height: 120, background: '#1e293b', borderRadius: 8, margin: '0 auto 14px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
              QR Code
            </div>
          )}
          <a
            href={config?.ios_url ?? '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: 'block', background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, fontWeight: 600, padding: '10px 0', textDecoration: 'none' }}
          >
            ↓ Download on App Store
          </a>
        </div>

        {/* Android */}
        <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '24px 20px', textAlign: 'center' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🤖</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>Android App</div>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>
            Version {loading ? '…' : (config?.android_version ?? 'N/A')} · Android 8+
          </div>
          {config?.qr_android && (
            <img src={config.qr_android} alt="Android QR" style={{ width: 120, height: 120, borderRadius: 8, marginBottom: 14, background: '#fff', padding: 4 }} />
          )}
          {!config?.qr_android && (
            <div style={{ width: 120, height: 120, background: '#1e293b', borderRadius: 8, margin: '0 auto 14px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 12 }}>
              QR Code
            </div>
          )}
          <a
            href={config?.android_url ?? '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: 'block', background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, fontWeight: 600, padding: '10px 0', textDecoration: 'none' }}
          >
            ↓ Get it on Google Play
          </a>
        </div>
      </div>

      {/* Features */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 14px' }}>Mobile Features</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {FEATURES.map(f => (
            <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#94a3b8' }}>
              <span style={{ color: '#4ade80', flexShrink: 0 }}>✓</span> {f}
            </div>
          ))}
        </div>
      </div>

      {/* Push token registration */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 8px' }}>Push Notifications</h3>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px' }}>
          Register a device push token to receive trade alerts and AI signals on your mobile device.
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="text"
            value={pushToken}
            onChange={e => setPushToken(e.target.value)}
            placeholder="Device push token…"
            style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, outline: 'none', padding: '8px 12px' }}
          />
          <button
            onClick={handleRegisterPushToken}
            disabled={!pushToken.trim() || registering}
            style={{ background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 16px' }}
          >
            {registering ? '…' : 'Register'}
          </button>
        </div>
        {tokenMsg && (
          <div style={{ fontSize: 13, color: tokenMsg.includes('Failed') ? '#f87171' : '#4ade80', marginTop: 8 }}>{tokenMsg}</div>
        )}
      </div>

      {/* Active mobile sessions */}
      <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '20px 24px' }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 14px' }}>
          Active Mobile Sessions ({sessions.length})
        </h3>
        {loading && <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>}
        {!loading && sessions.length === 0 && (
          <div style={{ color: '#475569', fontSize: 13 }}>No active mobile sessions.</div>
        )}
        {sessions.map(sess => (
          <div key={sess.session_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #1e293b' }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{sess.device_name}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                {sess.device_os} · {sess.ip_address} · Last active {new Date(sess.last_active).toLocaleString()}
              </div>
            </div>
            <button
              onClick={() => handleRevoke(sess.session_id)}
              disabled={revoking === sess.session_id}
              style={{ background: 'transparent', border: '1px solid #7f1d1d', borderRadius: 6, color: '#f87171', cursor: 'pointer', fontSize: 12, padding: '4px 10px' }}
            >
              {revoking === sess.session_id ? '…' : 'Revoke'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default MobilePage;
