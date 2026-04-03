// settings/PrivacySection.tsx — Data sharing, leaderboard, analytics, retention
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { PrivacySettings } from './types';
import { Card, SectionHeader, Field, Input, Toggle, Button, SaveBar } from './ui';

const DEFAULT: PrivacySettings = {
  share_performance: false,
  share_trades: false,
  share_signals: false,
  allow_copy_trading: false,
  show_in_leaderboard: true,
  analytics_opt_in: true,
  marketing_emails: false,
  data_retention_days: 365,
};

const PrivacySection: React.FC = () => {
  const [form, setForm] = useState<PrivacySettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [exportLoading, setExportLoading] = useState(false);

  useEffect(() => {
    api.get<PrivacySettings>('/settings/privacy')
      .then((r) => setForm({ ...DEFAULT, ...r.data }))
      .catch((err: unknown) => console.warn('[Settings/Privacy] load:', err))
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((patch: Partial<PrivacySettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      await api.post('/settings/privacy', form);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Failed to save privacy settings.');
    } finally { setSaving(false); }
  };

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const res = await api.get('/settings/privacy/export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `hopefx-data-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      console.warn('[Settings/Privacy] export:', err);
    } finally { setExportLoading(false); }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading privacy settings…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="🔏" title="Privacy & Data" description="Control what you share with other traders and the platform." />

      {/* Social sharing */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Social Sharing</h3>
        <Toggle id="share-perf" label="Share performance stats" description="Allow other traders to see your win rate and returns." checked={form.share_performance} onChange={(v) => update({ share_performance: v })} />
        <Toggle id="share-trades" label="Share trade history" description="Make your closed trades visible on your public profile." checked={form.share_trades} onChange={(v) => update({ share_trades: v })} />
        <Toggle id="share-signals" label="Share AI signals" description="Publish the signals you act on to the community feed." checked={form.share_signals} onChange={(v) => update({ share_signals: v })} />
        <Toggle id="copy-trading" label="Allow copy trading" description="Let other traders copy your positions in real time." checked={form.allow_copy_trading} onChange={(v) => update({ allow_copy_trading: v })} />
        <Toggle id="leaderboard" label="Show on leaderboard" description="Include your account in the public performance leaderboard." checked={form.show_in_leaderboard} onChange={(v) => update({ show_in_leaderboard: v })} />
      </Card>

      {/* Platform data */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Platform Data</h3>
        <Toggle id="analytics" label="Usage analytics" description="Help improve HOPEFX by sharing anonymous usage data." checked={form.analytics_opt_in} onChange={(v) => update({ analytics_opt_in: v })} />
        <Toggle id="marketing" label="Marketing emails" description="Receive product updates, tips, and promotional offers." checked={form.marketing_emails} onChange={(v) => update({ marketing_emails: v })} />
      </Card>

      {/* Data retention */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>Data Retention</h3>
        <Field label="Keep trade history for (days)" description="Trades older than this will be archived. Minimum 30 days.">
          <Input
            type="number" min={30} max={3650}
            value={form.data_retention_days}
            onChange={(e) => update({ data_retention_days: Number(e.target.value) })}
          />
        </Field>
      </Card>

      {/* Data export */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 8 }}>Your Data</h3>
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 14 }}>
          Download a full export of your account data including trades, signals, settings, and profile.
        </p>
        <Button variant="secondary" onClick={handleExport} loading={exportLoading}>
          Download my data
        </Button>
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default PrivacySection;
