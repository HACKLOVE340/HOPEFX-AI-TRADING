// settings/SecuritySection.tsx — Password, 2FA, active sessions
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, prefetchCsrfToken, resetCsrfCache } from '../../hooks/useApi';
import type { SessionInfo } from './types';

/** Retry once after a 403 by refreshing the CSRF token. */
async function withCsrfRetry<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (err: unknown) {
    if ((err as { response?: { status?: number } })?.response?.status === 403) {
      resetCsrfCache();
      await prefetchCsrfToken();
      return fn();
    }
    throw err;
  }
}
import { Card, SectionHeader, Button, StatusBadge, Divider, Input, Field } from './ui';

const SecuritySection: React.FC = () => {
  const navigate = useNavigate();

  // Password change
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' });
  const [pwSaving, setPwSaving] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // 2FA
  const [is2FA, setIs2FA] = useState(false);
  const [twoFALoading, setTwoFALoading] = useState(true);

  // Sessions
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ enabled: boolean }>('/2fa/status')
      .then((r) => setIs2FA(r.data.enabled ?? false))
      .catch((err: unknown) => console.warn('[Settings/Security] 2FA status:', err))
      .finally(() => setTwoFALoading(false));

    api.get<{ sessions: SessionInfo[] }>('/auth/sessions')
      .then((r) => setSessions(r.data.sessions ?? []))
      .catch((err: unknown) => console.warn('[Settings/Security] sessions:', err))
      .finally(() => setSessionsLoading(false));
  }, []);

  const handlePasswordChange = async () => {
    if (pwForm.next !== pwForm.confirm) {
      setPwMsg({ type: 'err', text: 'New passwords do not match.' });
      return;
    }
    if (pwForm.next.length < 8) {
      setPwMsg({ type: 'err', text: 'Password must be at least 8 characters.' });
      return;
    }
    setPwSaving(true);
    setPwMsg(null);
    try {
      await withCsrfRetry(() => api.post('/auth/change-password', {
        current_password: pwForm.current,
        new_password: pwForm.next,
      }));
      setPwMsg({ type: 'ok', text: 'Password updated successfully.' });
      setPwForm({ current: '', next: '', confirm: '' });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setPwMsg({ type: 'err', text: detail ?? 'Failed to update password.' });
    } finally {
      setPwSaving(false);
    }
  };

  const revokeSession = async (sessionId: string) => {
    setRevokingId(sessionId);
    try {
      await withCsrfRetry(() => api.delete(`/auth/sessions/${sessionId}`));
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (err: unknown) {
      console.warn('[Settings/Security] revoke session:', err);
    } finally {
      setRevokingId(null);
    }
  };

  const revokeAllSessions = async () => {
    if (!window.confirm('Revoke all other sessions? You will remain logged in on this device.')) return;
    try {
      await withCsrfRetry(() => api.delete('/auth/sessions'));
      setSessions((prev) => prev.filter((s) => s.current));
    } catch (err: unknown) {
      console.warn('[Settings/Security] revoke all sessions:', err);
    }
  };

  return (
    <div>
      <SectionHeader icon="🔒" title="Security" description="Password, two-factor authentication, and active sessions." />

      {/* Password */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>
          Change Password
        </h3>
        <Field label="Current password">
          <Input
            type="password"
            value={pwForm.current}
            onChange={(e) => setPwForm((p) => ({ ...p, current: e.target.value }))}
            placeholder="••••••••"
            autoComplete="current-password"
          />
        </Field>
        <Field label="New password">
          <Input
            type="password"
            value={pwForm.next}
            onChange={(e) => setPwForm((p) => ({ ...p, next: e.target.value }))}
            placeholder="Min. 8 characters"
            autoComplete="new-password"
          />
        </Field>
        <Field label="Confirm new password">
          <Input
            type="password"
            value={pwForm.confirm}
            onChange={(e) => setPwForm((p) => ({ ...p, confirm: e.target.value }))}
            placeholder="Repeat new password"
            autoComplete="new-password"
          />
        </Field>
        {pwMsg && (
          <div style={{ fontSize: 13, color: pwMsg.type === 'ok' ? '#22c55e' : '#f87171', marginBottom: 12 }}>
            {pwMsg.type === 'ok' ? '✅' : '❌'} {pwMsg.text}
          </div>
        )}
        <Button
          onClick={handlePasswordChange}
          loading={pwSaving}
          disabled={!pwForm.current || !pwForm.next || !pwForm.confirm}
        >
          Update password
        </Button>
      </Card>

      {/* 2FA */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
              Two-Factor Authentication
            </h3>
            <p style={{ fontSize: 13, color: '#64748b', marginTop: 4, marginBottom: 0 }}>
              Protect your account with a TOTP authenticator app.
            </p>
          </div>
          {twoFALoading
            ? <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
            : <StatusBadge status={is2FA ? 'ok' : 'warning'} label={is2FA ? 'Enabled' : 'Disabled'} />
          }
        </div>
        <Divider />
        <Button
          variant={is2FA ? 'secondary' : 'primary'}
          onClick={() => navigate('/2fa-setup')}
        >
          {is2FA ? 'Manage 2FA' : 'Enable 2FA'}
        </Button>
      </Card>

      {/* Sessions */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
            Active Sessions
          </h3>
          {sessions.length > 1 && (
            <Button variant="danger" size="sm" onClick={revokeAllSessions}>
              Revoke all others
            </Button>
          )}
        </div>

        {sessionsLoading ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>Loading sessions…</div>
        ) : sessions.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No active sessions found.</div>
        ) : (
          sessions.map((session) => (
            <div key={session.session_id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '12px 0', borderBottom: '1px solid #1e293b',
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={{ fontSize: 14, color: '#e2e8f0', fontWeight: 500 }}>
                    {session.device_info || 'Unknown device'}
                  </span>
                  {session.current && <StatusBadge status="ok" label="This device" />}
                </div>
                <div style={{ fontSize: 12, color: '#64748b' }}>
                  {session.ip_address} · Last active {new Date(session.last_active).toLocaleDateString()}
                </div>
              </div>
              {!session.current && (
                <Button
                  variant="danger"
                  size="sm"
                  loading={revokingId === session.session_id}
                  onClick={() => revokeSession(session.session_id)}
                >
                  Revoke
                </Button>
              )}
            </div>
          ))
        )}
      </Card>
    </div>
  );
};

export default SecuritySection;
