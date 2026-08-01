// settings/AdminSettingsSection.tsx — Admin-only platform configuration
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { AdminSettings } from './types';
import { Card, SectionHeader, Field, Input, Select, Toggle, Button, StatusBadge, Divider, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';
import { ErrorBanner } from '../../components/ErrorBanner';

const DEFAULT: AdminSettings = {
  allow_new_registrations: true,
  require_email_verification: true,
  default_new_user_plan: 'free',
  max_users: 0,
  force_2fa_for_admins: true,
  ip_whitelist_enabled: false,
  ip_whitelist: [],
  global_kill_switch: false,
  announcement_banner: '',
  announcement_enabled: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_user: '',
  smtp_password: '',
  smtp_from: '',
  smtp_tls: true,
};

const AdminSettingsSection: React.FC = () => {
  const [form, setForm] = useState<AdminSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [ipInput, setIpInput] = useState('');
  const [smtpTesting, setSmtpTesting] = useState(false);
  const [smtpTestResult, setSmtpTestResult] = useState<'ok' | 'fail' | null>(null);
  const [killSwitchConfirm, setKillSwitchConfirm] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadFailed(false);
    api.get<AdminSettings>('/admin/settings')
      .then((r) => setForm({ ...DEFAULT, ...r.data }))
      .catch((err: unknown) => {
        console.warn('[Settings/Admin] load:', err);
        // Never leave DEFAULT on screen looking like saved configuration. This
        // form is saved wholesale, and DEFAULT reports global_kill_switch as
        // false — so a failed GET plus one unrelated edit could resume trading
        // platform-wide while the page looked entirely normal throughout.
        setLoadFailed(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const update = useCallback((patch: Partial<AdminSettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      // The kill switch is deliberately NOT part of this payload. It has its own
      // endpoint and its own confirmation; saving a settings object must never be
      // able to flip the control that halts trading as a side effect.
      const { global_kill_switch: _killSwitch, ...payload } = form;
      await api.post('/admin/settings', payload);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save admin settings.'));
    } finally { setSaving(false); }
  };

  const addIp = () => {
    const ip = ipInput.trim();
    if (!ip || form.ip_whitelist.includes(ip)) return;
    update({ ip_whitelist: [...form.ip_whitelist, ip] });
    setIpInput('');
  };

  const removeIp = (ip: string) =>
    update({ ip_whitelist: form.ip_whitelist.filter((x) => x !== ip) });

  const testSmtp = async () => {
    setSmtpTesting(true); setSmtpTestResult(null);
    try {
      await api.post('/admin/settings/test-smtp', {
        host: form.smtp_host, port: form.smtp_port,
        user: form.smtp_user, password: form.smtp_password,
        from: form.smtp_from, tls: form.smtp_tls,
      });
      setSmtpTestResult('ok');
    } catch { setSmtpTestResult('fail'); }
    finally { setSmtpTesting(false); }
  };

  const activateGlobalKillSwitch = async () => {
    if (!killSwitchConfirm) { setKillSwitchConfirm(true); return; }
    try {
      await api.post('/admin/kill-switch/global');
      update({ global_kill_switch: true });
      setKillSwitchConfirm(false);
    } catch (err: unknown) {
      console.warn('[Settings/Admin] global kill switch:', err);
    }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading admin settings…
    </div>
  );

  // Refuse to render an editable form we could not populate. Showing defaults
  // here is worse than showing nothing: they are indistinguishable from real
  // configuration, and saving replaces the real values with them.
  if (loadFailed) return (
    <div>
      <SectionHeader icon="🔧" title="Admin Settings" description="Platform-wide controls. Only visible to administrators." />
      <ErrorBanner message="Couldn't load admin settings. Nothing has been changed — reload to try again." />
      <div style={{ marginTop: 14 }}>
        <Button variant="secondary" onClick={load}>Retry</Button>
      </div>
    </div>
  );

  return (
    <div>
      <SectionHeader icon="🔧" title="Admin Settings" description="Platform-wide controls. Only visible to administrators." />

      {/* Registration */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>User Registration</h3>
        <Toggle id="allow-reg" label="Allow new registrations" description="When disabled, the register page returns a 403." checked={form.allow_new_registrations} onChange={(v) => update({ allow_new_registrations: v })} />
        <Toggle id="email-verify" label="Require email verification" description="New users must verify their email before logging in." checked={form.require_email_verification} onChange={(v) => update({ require_email_verification: v })} />
        <Toggle id="force-2fa" label="Force 2FA for admins" description="All admin accounts must have 2FA enabled." checked={form.force_2fa_for_admins} onChange={(v) => update({ force_2fa_for_admins: v })} />
        <Divider />
        <Field label="Default plan for new users">
          <Select
            value={form.default_new_user_plan}
            onChange={(e) => update({ default_new_user_plan: e.target.value })}
            options={[
              { value: 'free',         label: 'Free' },
              { value: 'starter',      label: 'Starter' },
              { value: 'professional', label: 'Professional' },
              { value: 'enterprise',   label: 'Enterprise' },
              { value: 'elite',        label: 'Elite' },
            ]}
          />
        </Field>
        <Field label="Max users (0 = unlimited)">
          <Input type="number" min={0} value={form.max_users} onChange={(e) => update({ max_users: Number(e.target.value) })} />
        </Field>
      </Card>

      {/* Announcement banner */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Announcement Banner</h3>
        <Toggle id="announcement" label="Show announcement banner" description="Display a banner at the top of the app for all users." checked={form.announcement_enabled} onChange={(v) => update({ announcement_enabled: v })} />
        {form.announcement_enabled && (
          <>
            <Divider />
            <Field label="Banner message">
              <Input
                value={form.announcement_banner}
                onChange={(e) => update({ announcement_banner: e.target.value })}
                placeholder="e.g. Scheduled maintenance on Saturday 02:00–04:00 UTC"
              />
            </Field>
            {form.announcement_banner && (
              <div style={{
                marginTop: 8, padding: '10px 14px', background: '#78350f',
                border: '1px solid #92400e', borderRadius: 8,
                fontSize: 13, color: '#fbbf24',
              }}>
                Preview: {form.announcement_banner}
              </div>
            )}
          </>
        )}
      </Card>

      {/* IP whitelist */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>IP Whitelist</h3>
        <Toggle id="ip-whitelist" label="Enable IP whitelist" description="Only allow logins from the listed IP addresses." checked={form.ip_whitelist_enabled} onChange={(v) => update({ ip_whitelist_enabled: v })} />
        {form.ip_whitelist_enabled && (
          <>
            <Divider />
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <Input
                value={ipInput}
                onChange={(e) => setIpInput(e.target.value)}
                placeholder="192.168.1.1 or 10.0.0.0/24"
                onKeyDown={(e) => e.key === 'Enter' && addIp()}
                style={{ flex: 1 }}
              />
              <Button variant="secondary" size="sm" onClick={addIp}>Add</Button>
            </div>
            {form.ip_whitelist.length === 0 ? (
              <div style={{ fontSize: 13, color: '#64748b' }}>No IPs added. All IPs are blocked when whitelist is enabled.</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {form.ip_whitelist.map((ip) => (
                  <div key={ip} style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    background: '#0f172a', border: '1px solid #334155',
                    borderRadius: 6, padding: '4px 10px', fontSize: 13, color: '#94a3b8',
                  }}>
                    {ip}
                    <button onClick={() => removeIp(ip)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1 }}>×</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {/* SMTP */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>SMTP / Email</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 12 }}>
          <Field label="SMTP Host"><Input value={form.smtp_host} onChange={(e) => update({ smtp_host: e.target.value })} placeholder="smtp.example.com" /></Field>
          <Field label="Port"><Input type="number" value={form.smtp_port} onChange={(e) => update({ smtp_port: Number(e.target.value) })} /></Field>
        </div>
        <Field label="Username"><Input value={form.smtp_user} onChange={(e) => update({ smtp_user: e.target.value })} placeholder="noreply@example.com" /></Field>
        <Field label="Password"><Input type="password" value={form.smtp_password} onChange={(e) => update({ smtp_password: e.target.value })} placeholder="••••••••" /></Field>
        <Field label="From address"><Input value={form.smtp_from} onChange={(e) => update({ smtp_from: e.target.value })} placeholder="HOPEFX <noreply@hopefx.io>" /></Field>
        <Toggle id="smtp-tls" label="Use TLS/STARTTLS" checked={form.smtp_tls} onChange={(v) => update({ smtp_tls: v })} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
          <Button variant="secondary" size="sm" onClick={testSmtp} loading={smtpTesting} disabled={!form.smtp_host}>
            Send test email
          </Button>
          {smtpTestResult === 'ok' && <StatusBadge status="ok" label="Sent" />}
          {smtpTestResult === 'fail' && <StatusBadge status="error" label="Failed" />}
        </div>
      </Card>

      {/* Global kill switch */}
      <Card danger>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#fca5a5', marginTop: 0, marginBottom: 8 }}>Global Kill Switch</h3>
        <p style={{ fontSize: 13, color: '#94a3b8', marginBottom: 14 }}>
          Immediately halt ALL automated trading across every user account on the platform.
          This cannot be undone without manual intervention.
        </p>
        {form.global_kill_switch ? (
          <StatusBadge status="error" label="GLOBAL KILL SWITCH ACTIVE" />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Button
              variant="danger"
              onClick={activateGlobalKillSwitch}
            >
              {killSwitchConfirm ? '⚠️ Confirm — halt all trading' : 'Activate global kill switch'}
            </Button>
            {killSwitchConfirm && (
              <button
                onClick={() => setKillSwitchConfirm(false)}
                style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 13 }}
              >
                Cancel
              </button>
            )}
          </div>
        )}
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default AdminSettingsSection;
