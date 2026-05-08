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
  const [emergencyDone, setEmergencyDone] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const handleExportData = async () => {
    setExportLoading(true);
    try {
      const res = await api.get('/admin/audit-log/export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `hopefx-data-export-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Data export downloaded.');
    } catch (err: unknown) {
      toast.error('Export failed. Try again.');
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
      setEmergencyDone(true);
      toast.success('Emergency stop activated — all trading halted.');
    } catch (err: unknown) {
      toast.error('Emergency stop failed. Contact support immediately.');
      console.warn('[Settings/Danger] emergency stop:', err);
    } finally {
      setEmergencyLoading(false);
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
            <div style={{ fontSize: 13, color: '#64748b' }}>Download a CSV of your audit log, trades, and account activity.</div>
          </div>
          <Button variant="secondary" onClick={handleExportData} loading={exportLoading}>
            Export CSV
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
          {emergencyDone ? (
            <span style={{ fontSize: 13, color: '#22c55e', fontWeight: 600 }}>✅ Trading halted</span>
          ) : (
            <Button variant="danger" onClick={handleEmergencyStop} loading={emergencyLoading}>
              Emergency stop
            </Button>
          )}
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
              await api.delete('/auth/sessions').catch(() => {});
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
