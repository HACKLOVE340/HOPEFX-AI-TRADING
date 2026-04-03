// superadmin/PlatformSection.tsx — platform config, maintenance, broadcast
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, ActionBtn, Input, Select, Toggle,
  ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';

interface PlatformConfig {
  platform_name: string;
  support_email: string;
  max_users: number;
  allow_registrations: boolean;
  require_email_verification: boolean;
  default_new_user_plan: string;
  default_new_user_role: string;
  session_timeout_minutes: number;
  max_api_keys_per_user: number;
  rate_limit_per_minute: number;
  maintenance_mode: boolean;
  maintenance_message: string;
  announcement_enabled: boolean;
  announcement_text: string;
  announcement_type: string;
  force_2fa_for_admins: boolean;
  ip_whitelist_enabled: boolean;
  ip_whitelist: string;
}

const PlatformSection: React.FC = () => {
  const [cfg, setCfg]         = useState<PlatformConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState('');
  const [msg, setMsg]         = useState('');
  const [confirm, setConfirm] = useState<string | null>(null);
  const [broadcast, setBroadcast] = useState({ title: '', body: '', type: 'info' });

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await superadminApi.platformConfig();
      setCfg(res.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load config');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!cfg) return;
    setSaving(true); setMsg('');
    try {
      await superadminApi.updatePlatformConfig(cfg);
      setMsg('Configuration saved');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed');
    } finally { setSaving(false); }
  };

  const toggleMaintenance = async () => {
    if (!cfg) return;
    setSaving(true); setMsg('');
    try {
      await superadminApi.maintenanceMode(!cfg.maintenance_mode, cfg.maintenance_message);
      setCfg(c => c ? { ...c, maintenance_mode: !c.maintenance_mode } : c);
      setMsg(`Maintenance mode ${!cfg.maintenance_mode ? 'enabled' : 'disabled'}`);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed');
    } finally { setSaving(false); setConfirm(null); }
  };

  const sendBroadcast = async () => {
    setSaving(true); setMsg('');
    try {
      await superadminApi.broadcastMessage(broadcast);
      setMsg('Broadcast sent to all active users');
      setBroadcast({ title: '', body: '', type: 'info' });
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Broadcast failed');
    } finally { setSaving(false); }
  };

  const set = (k: keyof PlatformConfig, v: unknown) => setCfg(c => c ? { ...c, [k]: v } : c);

  if (loading) return <><SAStyles /><LoadingRows rows={10} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;
  if (!cfg)    return null;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {confirm === 'maintenance' && (
        <ConfirmDialog
          title={cfg.maintenance_mode ? 'Disable Maintenance Mode' : 'Enable Maintenance Mode'}
          message={cfg.maintenance_mode
            ? 'This will restore normal platform access for all users.'
            : 'This will show a maintenance page to all non-admin users. Confirm only if you intend to take the platform offline.'}
          confirmLabel={cfg.maintenance_mode ? 'Disable' : 'Enable'}
          variant={cfg.maintenance_mode ? 'warning' : 'danger'}
          onConfirm={toggleMaintenance}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* General */}
      <SectionCard title="General Settings" icon="⚙️" accent="#3b82f6"
        actions={<ActionBtn label={saving ? 'Saving…' : 'Save Changes'} onClick={save} variant="primary" loading={saving} size="sm" />}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Input label="Platform Name"   value={cfg.platform_name}   onChange={e => set('platform_name', e.target.value)} />
          <Input label="Support Email"   value={cfg.support_email}   onChange={e => set('support_email', e.target.value)} />
          <Input label="Max Users"       value={cfg.max_users}       onChange={e => set('max_users', Number(e.target.value))} type="number" />
          <Input label="Session Timeout (min)" value={cfg.session_timeout_minutes} onChange={e => set('session_timeout_minutes', Number(e.target.value))} type="number" />
          <Input label="Rate Limit / min" value={cfg.rate_limit_per_minute} onChange={e => set('rate_limit_per_minute', Number(e.target.value))} type="number" />
          <Input label="Max API Keys / User" value={cfg.max_api_keys_per_user} onChange={e => set('max_api_keys_per_user', Number(e.target.value))} type="number" />
          <Select label="Default New User Plan"
            value={cfg.default_new_user_plan}
            onChange={e => set('default_new_user_plan', e.target.value)}
            options={[
              { value: 'free', label: 'Free' }, { value: 'starter', label: 'Starter' },
              { value: 'pro', label: 'Pro' },   { value: 'elite', label: 'Elite' },
            ]}
          />
          <Select label="Default New User Role"
            value={cfg.default_new_user_role}
            onChange={e => set('default_new_user_role', e.target.value)}
            options={[
              { value: 'user', label: 'User' }, { value: 'trader', label: 'Trader' },
            ]}
          />
        </div>
        <div style={{ marginTop: 14, borderTop: '1px solid #1e293b', paddingTop: 14 }}>
          <Toggle label="Allow New Registrations"     checked={cfg.allow_registrations}          onChange={v => set('allow_registrations', v)} />
          <Toggle label="Require Email Verification"  checked={cfg.require_email_verification}   onChange={v => set('require_email_verification', v)} />
          <Toggle label="Force 2FA for Admins"        checked={cfg.force_2fa_for_admins}         onChange={v => set('force_2fa_for_admins', v)} accent="#f59e0b" />
          <Toggle label="IP Whitelist Enabled"        checked={cfg.ip_whitelist_enabled}         onChange={v => set('ip_whitelist_enabled', v)} accent="#ef4444" />
        </div>
        {cfg.ip_whitelist_enabled && (
          <div style={{ marginTop: 10 }}>
            <Input label="IP Whitelist (comma-separated)" value={cfg.ip_whitelist} onChange={e => set('ip_whitelist', e.target.value)} placeholder="192.168.1.1, 10.0.0.0/24" />
          </div>
        )}
      </SectionCard>

      {/* Maintenance */}
      <SectionCard title="Maintenance Mode" icon="🔧" accent="#f59e0b"
        subtitle={cfg.maintenance_mode ? '⚠️ Currently ACTIVE — users see downtime page' : 'Platform is live'}>
        <div style={{ marginBottom: 14 }}>
          <Input
            label="Maintenance Message (shown to users)"
            value={cfg.maintenance_message}
            onChange={e => set('maintenance_message', e.target.value)}
            placeholder="We're performing scheduled maintenance. Back shortly."
          />
        </div>
        <ActionBtn
          label={cfg.maintenance_mode ? 'Disable Maintenance Mode' : 'Enable Maintenance Mode'}
          onClick={() => setConfirm('maintenance')}
          variant={cfg.maintenance_mode ? 'success' : 'danger'}
          icon={cfg.maintenance_mode ? '✅' : '🔧'}
          loading={saving}
        />
      </SectionCard>

      {/* Announcement Banner */}
      <SectionCard title="Announcement Banner" icon="📢" accent="#8b5cf6">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <Select label="Type"
            value={cfg.announcement_type}
            onChange={e => set('announcement_type', e.target.value)}
            options={[
              { value: 'info', label: 'Info' }, { value: 'warning', label: 'Warning' },
              { value: 'success', label: 'Success' }, { value: 'error', label: 'Error' },
            ]}
          />
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <Toggle label="Show Banner" checked={cfg.announcement_enabled} onChange={v => set('announcement_enabled', v)} />
          </div>
        </div>
        <Input
          label="Announcement Text"
          value={cfg.announcement_text}
          onChange={e => set('announcement_text', e.target.value)}
          placeholder="Platform announcement visible to all users…"
        />
      </SectionCard>

      {/* Broadcast */}
      <SectionCard title="Broadcast Message" icon="📡" accent="#06b6d4"
        subtitle="Send an in-app notification to all active users">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <Input label="Title" value={broadcast.title} onChange={e => setBroadcast(b => ({ ...b, title: e.target.value }))} placeholder="Important update" />
          <Select label="Type"
            value={broadcast.type}
            onChange={e => setBroadcast(b => ({ ...b, type: e.target.value }))}
            options={[
              { value: 'info', label: 'Info' }, { value: 'warning', label: 'Warning' },
              { value: 'success', label: 'Success' }, { value: 'error', label: 'Error' },
            ]}
          />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500, display: 'block', marginBottom: 5 }}>Message Body</label>
          <textarea
            value={broadcast.body}
            onChange={e => setBroadcast(b => ({ ...b, body: e.target.value }))}
            placeholder="Message body…"
            rows={3}
            style={{
              width: '100%', background: '#1e293b', border: '1px solid #334155',
              borderRadius: 7, color: '#f1f5f9', fontSize: 13, padding: '8px 12px',
              resize: 'vertical', outline: 'none', boxSizing: 'border-box',
            }}
          />
        </div>
        <ActionBtn
          label="Send Broadcast"
          onClick={sendBroadcast}
          variant="primary"
          icon="📡"
          loading={saving}
          disabled={!broadcast.title || !broadcast.body}
        />
      </SectionCard>

      {msg && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginTop: 4,
          background: msg.includes('failed') || msg.includes('Failed') ? '#450a0a' : '#052e16',
          color: msg.includes('failed') || msg.includes('Failed') ? '#f87171' : '#4ade80',
          fontSize: 13, fontWeight: 600,
        }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default PlatformSection;
