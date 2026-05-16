// settings/SystemSection.tsx — Admin-only system configuration
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { SystemSettings } from './types';
import { Card, SectionHeader, Field, Input, Select, Toggle, Button, StatusBadge, Divider, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: SystemSettings = {
  data_refresh_interval: 30,
  max_open_positions: 10,
  session_timeout_minutes: 60,
  log_level: 'info',
  enable_paper_trading: true,
  enable_live_trading: false,
  maintenance_mode: false,
  rate_limit_per_minute: 60,
  cache_ttl_seconds: 300,
  backup_enabled: true,
  backup_frequency: 'daily',
};

const SystemSection: React.FC = () => {
  const [form, setForm] = useState<SystemSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [backupRunning, setBackupRunning] = useState(false);
  const [backupMsg, setBackupMsg] = useState('');
  const [healthData, setHealthData] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    api.get<SystemSettings>('/admin/settings/system')
      .then((r) => setForm({ ...DEFAULT, ...r.data }))
      .catch((err: unknown) => console.warn('[Settings/System] load:', err))
      .finally(() => setLoading(false));

    api.get<Record<string, unknown>>('/health')
      .then((r) => setHealthData(r.data))
      .catch(() => {/* non-fatal */});
  }, []);

  const update = useCallback((patch: Partial<SystemSettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      await api.post('/admin/settings/system', form);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save system settings.'));
    } finally { setSaving(false); }
  };

  const triggerBackup = async () => {
    setBackupRunning(true); setBackupMsg('');
    try {
      await api.post('/admin/backup/trigger');
      setBackupMsg('Backup started successfully.');
    } catch { setBackupMsg('Backup failed to start.'); }
    finally { setBackupRunning(false); }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading system settings…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="⚙️" title="System" description="Platform-wide configuration. Changes affect all users." />

      {/* Health overview */}
      {healthData && (
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>System Health</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            {Object.entries(healthData).slice(0, 6).map(([k, v]) => (
              <div key={k} style={{ background: '#0f172a', borderRadius: 8, padding: '10px 14px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{k.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{String(v)}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Trading engine */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Trading Engine</h3>
        <Toggle id="paper-trading" label="Enable paper trading" description="Allow users to trade with simulated funds." checked={form.enable_paper_trading} onChange={(v) => update({ enable_paper_trading: v })} />
        <Toggle id="live-trading" label="Enable live trading" description="Allow users to execute real-money trades." checked={form.enable_live_trading} onChange={(v) => update({ enable_live_trading: v })} />
        <Toggle id="maintenance" label="Maintenance mode" description="Block all trading and show a maintenance banner to users." checked={form.maintenance_mode} onChange={(v) => update({ maintenance_mode: v })} />
        <Divider />
        <Field label="Max open positions per user">
          <Input type="number" min={1} max={100} value={form.max_open_positions} onChange={(e) => update({ max_open_positions: Number(e.target.value) })} />
        </Field>
      </Card>

      {/* Performance */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Performance</h3>
        <Field label="Data refresh interval (seconds)" description="How often the dashboard polls for new data.">
          <Input type="number" min={5} max={300} value={form.data_refresh_interval} onChange={(e) => update({ data_refresh_interval: Number(e.target.value) })} />
        </Field>
        <Field label="Cache TTL (seconds)">
          <Input type="number" min={10} max={3600} value={form.cache_ttl_seconds} onChange={(e) => update({ cache_ttl_seconds: Number(e.target.value) })} />
        </Field>
        <Field label="Rate limit (requests per minute per user)">
          <Input type="number" min={10} max={1000} value={form.rate_limit_per_minute} onChange={(e) => update({ rate_limit_per_minute: Number(e.target.value) })} />
        </Field>
        <Field label="Session timeout (minutes)">
          <Input type="number" min={5} max={1440} value={form.session_timeout_minutes} onChange={(e) => update({ session_timeout_minutes: Number(e.target.value) })} />
        </Field>
      </Card>

      {/* Logging */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>Logging</h3>
        <Field label="Log level">
          <Select
            value={form.log_level}
            onChange={(e) => update({ log_level: e.target.value as SystemSettings['log_level'] })}
            options={[
              { value: 'debug',   label: 'Debug — verbose, all events' },
              { value: 'info',    label: 'Info — standard operations' },
              { value: 'warning', label: 'Warning — anomalies only' },
              { value: 'error',   label: 'Error — failures only' },
            ]}
          />
        </Field>
      </Card>

      {/* Backup */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Backup</h3>
        <Toggle id="backup-enabled" label="Automated backups" description="Automatically back up the database on schedule." checked={form.backup_enabled} onChange={(v) => update({ backup_enabled: v })} />
        {form.backup_enabled && (
          <>
            <Divider />
            <Field label="Backup frequency">
              <Select
                value={form.backup_frequency}
                onChange={(e) => update({ backup_frequency: e.target.value as SystemSettings['backup_frequency'] })}
                options={[
                  { value: 'hourly', label: 'Hourly' },
                  { value: 'daily',  label: 'Daily' },
                  { value: 'weekly', label: 'Weekly' },
                ]}
              />
            </Field>
          </>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={triggerBackup} loading={backupRunning}>
            Run backup now
          </Button>
          {backupMsg && (
            <span style={{ fontSize: 13, color: backupMsg.includes('success') ? '#22c55e' : '#f87171' }}>
              {backupMsg}
            </span>
          )}
        </div>
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default SystemSection;
