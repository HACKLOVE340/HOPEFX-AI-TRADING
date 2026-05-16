// settings/NotificationsSection.tsx — Discord, Slack, Telegram, Email, alert triggers
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { NotificationSettings } from './types';
import { Card, SectionHeader, Field, Input, Toggle, Button, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: NotificationSettings = {
  discord_enabled: false, discord_webhook_url: '',
  slack_enabled: false, slack_webhook_url: '',
  telegram_enabled: false, telegram_bot_token: '', telegram_chat_id: '',
  email_enabled: false, email_address: '',
  notify_on_trade: true, notify_on_signal: true,
  notify_on_error: true, notify_on_daily_summary: true,
};

const STORAGE_KEY = 'hopefx_notification_prefs';

type SafePrefs = Pick<NotificationSettings,
  'discord_enabled' | 'slack_enabled' | 'telegram_enabled' | 'email_enabled' |
  'notify_on_trade' | 'notify_on_signal' | 'notify_on_error' | 'notify_on_daily_summary'
>;

function loadLocalPrefs(): Partial<SafePrefs> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Partial<SafePrefs>;
  } catch { localStorage.removeItem(STORAGE_KEY); }
  return {};
}

function cacheLocalPrefs(s: NotificationSettings): void {
  const prefs: SafePrefs = {
    discord_enabled: s.discord_enabled, slack_enabled: s.slack_enabled,
    telegram_enabled: s.telegram_enabled, email_enabled: s.email_enabled,
    notify_on_trade: s.notify_on_trade, notify_on_signal: s.notify_on_signal,
    notify_on_error: s.notify_on_error, notify_on_daily_summary: s.notify_on_daily_summary,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

type TestState = 'idle' | 'sending' | 'ok' | 'fail';

const NotificationsSection: React.FC = () => {
  const [settings, setSettings] = useState<NotificationSettings>(() => ({
    ...DEFAULT, ...loadLocalPrefs(),
  }));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveErr, setSaveErr] = useState('');
  const [testStatus, setTestStatus] = useState<Record<string, TestState>>({
    discord: 'idle', slack: 'idle', telegram: 'idle',
  });

  useEffect(() => {
    api.get<NotificationSettings>('/settings/notifications')
      .then((r) => {
        const merged = { ...DEFAULT, ...r.data };
        setSettings(merged);
        cacheLocalPrefs(merged);
      })
      .catch((err: unknown) => console.warn('[Settings/Notifications] load:', err))
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((patch: Partial<NotificationSettings>) =>
    setSettings((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true);
    setSaveErr('');
    try {
      await api.post('/settings/notifications', settings);
      cacheLocalPrefs(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setSaveErr(extractApiError(err, 'Failed to save notification settings.'));
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async (channel: string) => {
    setTestStatus((prev) => ({ ...prev, [channel]: 'sending' }));
    try {
      await api.post('/notifications/test', { channel, settings });
      setTestStatus((prev) => ({ ...prev, [channel]: 'ok' }));
    } catch (err: unknown) {
      console.warn('[Settings/Notifications] test failed:', channel, err);
      setTestStatus((prev) => ({ ...prev, [channel]: 'fail' }));
    }
    setTimeout(() => setTestStatus((prev) => ({ ...prev, [channel]: 'idle' })), 4000);
  };

  const TestRow: React.FC<{ channel: string; disabled?: boolean }> = ({ channel, disabled }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => sendTest(channel)}
        loading={testStatus[channel] === 'sending'}
        disabled={disabled || testStatus[channel] === 'sending'}
      >
        Send test
      </Button>
      {testStatus[channel] === 'ok' && <span style={{ fontSize: 13, color: '#22c55e' }}>✅ Delivered</span>}
      {testStatus[channel] === 'fail' && <span style={{ fontSize: 13, color: '#f87171' }}>❌ Failed — check credentials</span>}
    </div>
  );

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading notification settings…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="🔔" title="Notifications" description="Configure where HOPEFX sends trade alerts, signals, and system events." />

      {/* Discord */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: settings.discord_enabled ? 16 : 0 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Discord</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Receive alerts in a Discord channel via webhook.</div>
          </div>
          <Toggle id="discord-toggle" label="" checked={settings.discord_enabled} onChange={(v) => update({ discord_enabled: v })} />
        </div>
        {settings.discord_enabled && (
          <>
            <Field label="Webhook URL" description="Server Settings → Integrations → Webhooks → New Webhook.">
              <Input
                type="url"
                placeholder="https://discord.com/api/webhooks/…"
                value={settings.discord_webhook_url}
                onChange={(e) => update({ discord_webhook_url: e.target.value })}
                spellCheck={false}
              />
            </Field>
            <TestRow channel="discord" disabled={!settings.discord_webhook_url} />
          </>
        )}
      </Card>

      {/* Slack */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: settings.slack_enabled ? 16 : 0 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Slack</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Post alerts to a Slack channel via incoming webhook.</div>
          </div>
          <Toggle id="slack-toggle" label="" checked={settings.slack_enabled} onChange={(v) => update({ slack_enabled: v })} />
        </div>
        {settings.slack_enabled && (
          <>
            <Field label="Webhook URL" description="api.slack.com/apps → Your App → Incoming Webhooks.">
              <Input
                type="url"
                placeholder="https://hooks.slack.com/services/…"
                value={settings.slack_webhook_url}
                onChange={(e) => update({ slack_webhook_url: e.target.value })}
                spellCheck={false}
              />
            </Field>
            <TestRow channel="slack" disabled={!settings.slack_webhook_url} />
          </>
        )}
      </Card>

      {/* Telegram */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: settings.telegram_enabled ? 16 : 0 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Telegram</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Send messages via a Telegram bot.</div>
          </div>
          <Toggle id="telegram-toggle" label="" checked={settings.telegram_enabled} onChange={(v) => update({ telegram_enabled: v })} />
        </div>
        {settings.telegram_enabled && (
          <>
            <Field label="Bot token" description="Create a bot via @BotFather and paste the token here.">
              <Input
                type="password"
                placeholder="1234567890:ABCdef…"
                value={settings.telegram_bot_token}
                onChange={(e) => update({ telegram_bot_token: e.target.value })}
                autoComplete="off"
              />
            </Field>
            <Field label="Chat ID" description="Your chat or group ID (e.g. -1001234567890).">
              <Input
                placeholder="-1001234567890"
                value={settings.telegram_chat_id}
                onChange={(e) => update({ telegram_chat_id: e.target.value })}
              />
            </Field>
            <TestRow channel="telegram" disabled={!settings.telegram_bot_token || !settings.telegram_chat_id} />
          </>
        )}
      </Card>

      {/* Email */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: settings.email_enabled ? 16 : 0 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Email</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Receive alerts and daily summaries by email.</div>
          </div>
          <Toggle id="email-toggle" label="" checked={settings.email_enabled} onChange={(v) => update({ email_enabled: v })} />
        </div>
        {settings.email_enabled && (
          <Field label="Email address">
            <Input
              type="email"
              placeholder="alerts@example.com"
              value={settings.email_address}
              onChange={(e) => update({ email_address: e.target.value })}
            />
          </Field>
        )}
      </Card>

      {/* Alert triggers */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 8 }}>Alert Triggers</h3>
        <Toggle id="notify-trade"   label="Trade executed"        checked={settings.notify_on_trade}         onChange={(v) => update({ notify_on_trade: v })} />
        <Toggle id="notify-signal"  label="New signal generated"  checked={settings.notify_on_signal}        onChange={(v) => update({ notify_on_signal: v })} />
        <Toggle id="notify-error"   label="System errors"         checked={settings.notify_on_error}         onChange={(v) => update({ notify_on_error: v })} />
        <Toggle id="notify-daily"   label="Daily P&L summary"     checked={settings.notify_on_daily_summary} onChange={(v) => update({ notify_on_daily_summary: v })} />
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveErr} />
    </div>
  );
};

export default NotificationsSection;
