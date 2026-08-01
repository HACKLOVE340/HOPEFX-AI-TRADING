// settings/DangerSection.tsx — Export data, close account, emergency stop
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, prefetchCsrfToken, resetCsrfCache } from '../../hooks/useApi';
import { useStore } from '../../store';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';

async function withCsrfRetry<T>(fn: () => Promise<T>): Promise<T> {
  try { return await fn(); }
  catch (err: unknown) {
    if ((err as { response?: { status?: number } })?.response?.status === 403) {
      resetCsrfCache(); await prefetchCsrfToken(); return fn();
    }
    throw err;
  }
}
import { Card, SectionHeader, Button, Divider } from './ui';
import { extractApiError } from '../../lib/utils';

const DangerSection: React.FC = () => {
  const navigate = useNavigate();
  const clearAuth = useStore((s) => s.clearAuth);
  const confirm   = useConfirm();
  const toast     = useToast();

  const [exportLoading, setExportLoading] = useState(false);
  const [emergencyLoading, setEmergencyLoading] = useState(false);
  // Server-reported halt state, not local optimism. A sticky local flag meant
  // that once the button was pressed the page read "✅ Trading halted" for the
  // rest of the session and the control disappeared — so if trading resumed
  // (supervisor restart, another operator, partial failure) the screen kept
  // asserting a halt that no longer held, with no way to retry.
  const [tradingHalted, setTradingHalted] = useState<boolean | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  /** Read the live kill-switch state. GET /settings/trading reports the engine,
   *  not a stored preference, so this is authoritative for a normal user. */
  const refreshHaltState = React.useCallback(async () => {
    try {
      const res = await api.get<{ kill_switch_enabled?: boolean }>('/settings/trading');
      setTradingHalted(res.data.kill_switch_enabled ?? false);
    } catch {
      // Unknown, and shown as unknown — never as "not halted".
      setTradingHalted(null);
    }
  }, []);

  React.useEffect(() => { void refreshHaltState(); }, [refreshHaltState]);

  const handleExportData = async () => {
    setExportLoading(true);
    try {
      // Was '/admin/audit-log/export' — an admin route behind a button in the
      // user's own Danger Zone, so every non-admin got a 403 and a "try again"
      // toast that could never work. This endpoint is user-scoped via the token
      // and scrubs broker secrets before returning.
      const res = await api.get('/settings/privacy/export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `hopefx-data-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Data export downloaded.');
    } catch (err: unknown) {
      toast.error(extractApiError(err, 'Export failed. Try again.'));
      console.warn('[Settings/Danger] export:', err);
    } finally {
      setExportLoading(false);
    }
  };

  const handleEmergencyStop = async () => {
    const ok = await confirm({
      title: 'Activate emergency stop?',
      description: 'This will immediately halt all automated trading and close all open positions. This action cannot be undone.',
      confirmLabel: 'Halt trading',
      variant: 'danger',
    });
    if (!ok) return;
    setEmergencyLoading(true);
    try {
      await withCsrfRetry(() => api.post('/trading/emergency-stop'));
      toast.success('Emergency stop activated — all trading halted.');
    } catch (err: unknown) {
      toast.error(extractApiError(err, 'Emergency stop failed. Contact support immediately.'));
      console.warn('[Settings/Danger] emergency stop:', err);
    } finally {
      setEmergencyLoading(false);
      // Read the outcome back rather than assuming it. A halt is the one thing
      // on this page you must not merely believe happened.
      void refreshHaltState();
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirm !== 'DELETE') {
      setDeleteError('Type DELETE to confirm.');
      return;
    }
    setDeleteLoading(true);
    setDeleteError('');
    try {
      await withCsrfRetry(() => api.delete('/auth/account'));
      clearAuth();
      navigate('/');
    } catch (err: unknown) {
      setDeleteError(extractApiError(err, 'Failed to delete account. Contact support.'));
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <div>
      <SectionHeader icon="⚠️" title="Danger Zone" description="Irreversible actions. Proceed with caution." />

      {/* Export data */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>Export your data</div>
            {/* Describes what the endpoint actually returns. It previously promised
                audit log, trades and account activity; /settings/privacy/export
                carries privacy, integration and accessibility settings only.
                Widening the export is follow-up work — the copy must not run
                ahead of it. */}
            <div style={{ fontSize: 13, color: '#64748b' }}>Download a JSON copy of your privacy, integration, and accessibility settings.</div>
          </div>
          <Button variant="secondary" onClick={handleExportData} loading={exportLoading}>
            Export JSON
          </Button>
        </div>
      </Card>

      {/* Emergency stop */}
      <Card danger>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', marginBottom: 4 }}>Emergency stop</div>
            <div style={{ fontSize: 13, color: '#94a3b8' }}>
              Immediately halt all automated trading and close all open positions.
            </div>
          </div>
          {/* The control stays available whatever the state says — losing it is
              how an operator ends up unable to retry a halt that silently
              lapsed. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {tradingHalted === true && (
              <span style={{ fontSize: 13, color: '#f87171', fontWeight: 600 }}>🛑 Trading halted</span>
            )}
            {tradingHalted === null && (
              <span style={{ fontSize: 12, color: '#94a3b8' }}>Status unavailable</span>
            )}
            <Button variant="danger" onClick={handleEmergencyStop} loading={emergencyLoading}>
              {tradingHalted === true ? 'Halt again' : 'Emergency stop'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Revoke all sessions */}
      <Card danger>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', marginBottom: 4 }}>Sign out everywhere</div>
            <div style={{ fontSize: 13, color: '#94a3b8' }}>
              Revoke all active sessions across all devices. You will be signed out here too.
            </div>
          </div>
          <Button
            variant="danger"
            onClick={async () => {
              const ok = await confirm({
                title: 'Sign out of all devices?',
                description: 'All active sessions will be revoked. You will be redirected to login.',
                confirmLabel: 'Sign out all',
                variant: 'danger',
              });
              if (!ok) return;
              // The one action on this page whose entire purpose is security —
              // a user reaches for it after losing a laptop. Swallowing the
              // failure told them it had worked while the other sessions stayed
              // live. It was also the only destructive action here not wrapped
              // in withCsrfRetry, so a stale CSRF token 403'd it, which is the
              // most likely way it failed.
              try {
                await withCsrfRetry(() => api.delete('/auth/sessions'));
              } catch (err: unknown) {
                toast.error(extractApiError(
                  err,
                  'Could not revoke your other sessions — they may still be signed in. Please try again.',
                ));
                return;   // stay signed in: the safer failure
              }
              clearAuth();
              navigate('/login');
            }}
          >
            Sign out all
          </Button>
        </div>
      </Card>

      <Divider />

      {/* Delete account */}
      <Card danger>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', marginBottom: 4 }}>Delete account</div>
          <div style={{ fontSize: 13, color: '#94a3b8' }}>
            Permanently delete your account, all data, positions, and settings. This cannot be undone.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <input
            type="text"
            value={deleteConfirm}
            onChange={(e) => { setDeleteConfirm(e.target.value); setDeleteError(''); }}
            placeholder='Type "DELETE" to confirm'
            style={{
              flex: 1, padding: '10px 12px', background: '#0f172a',
              border: `1px solid ${deleteError ? '#ef4444' : '#7f1d1d'}`,
              borderRadius: 8, color: '#f1f5f9', fontSize: 14, outline: 'none',
            }}
          />
          <Button
            variant="danger"
            onClick={handleDeleteAccount}
            loading={deleteLoading}
            disabled={deleteConfirm !== 'DELETE'}
          >
            Delete account
          </Button>
        </div>
        {deleteError && (
          <div style={{ fontSize: 13, color: '#f87171', marginTop: 8 }}>❌ {deleteError}</div>
        )}
      </Card>
    </div>
  );
};

export default DangerSection;
