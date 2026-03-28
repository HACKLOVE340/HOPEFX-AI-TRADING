import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../hooks/useApi';

// ── Types ─────────────────────────────────────────────────────────────────────

interface NotificationSettings {
  discord_enabled: boolean;
  discord_webhook_url: string;
  slack_enabled: boolean;
  slack_webhook_url: string;
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  email_enabled: boolean;
  email_address: string;
  notify_on_trade: boolean;
  notify_on_signal: boolean;
  notify_on_error: boolean;
  notify_on_daily_summary: boolean;
}

const DEFAULT_SETTINGS: NotificationSettings = {
  discord_enabled: false,
  discord_webhook_url: '',
  slack_enabled: false,
  slack_webhook_url: '',
  telegram_enabled: false,
  telegram_bot_token: '',
  telegram_chat_id: '',
  email_enabled: false,
  email_address: '',
  notify_on_trade: true,
  notify_on_signal: true,
  notify_on_error: true,
  notify_on_daily_summary: true,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'hopefx_notification_prefs';

/**
 * Non-sensitive boolean preferences that are safe to cache locally.
 * Webhook URLs and bot tokens are NEVER written to localStorage — they are
 * loaded from and saved to the backend API only.
 */
type SafePrefs = Pick<
  NotificationSettings,
  | 'discord_enabled'
  | 'slack_enabled'
  | 'telegram_enabled'
  | 'email_enabled'
  | 'notify_on_trade'
  | 'notify_on_signal'
  | 'notify_on_error'
  | 'notify_on_daily_summary'
>;

function loadLocalPrefs(): Partial<SafePrefs> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Partial<SafePrefs>;
  } catch (_) {}
  return {};
}

function cacheLocalPrefs(s: NotificationSettings): void {
  const prefs: SafePrefs = {
    discord_enabled:        s.discord_enabled,
    slack_enabled:          s.slack_enabled,
    telegram_enabled:       s.telegram_enabled,
    email_enabled:          s.email_enabled,
    notify_on_trade:        s.notify_on_trade,
    notify_on_signal:       s.notify_on_signal,
    notify_on_error:        s.notify_on_error,
    notify_on_daily_summary: s.notify_on_daily_summary,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface ToggleProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}

const Toggle: React.FC<ToggleProps> = ({ id, label, checked, onChange }) => (
  <label htmlFor={id} style={styles.toggleRow}>
    <span style={styles.toggleLabel}>{label}</span>
    <div
      id={id}
      role="switch"
      aria-checked={checked}
      tabIndex={0}
      onClick={() => onChange(!checked)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onChange(!checked)}
      style={{
        ...styles.toggleTrack,
        background: checked ? '#22c55e' : '#374151',
      }}
    >
      <div
        style={{
          ...styles.toggleThumb,
          transform: checked ? 'translateX(20px)' : 'translateX(2px)',
        }}
      />
    </div>
  </label>
);

interface WebhookFieldProps {
  label: string;
  placeholder: string;
  value: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  onChange: (v: string) => void;
  onTest: () => void;
  testStatus: 'idle' | 'sending' | 'ok' | 'fail';
  helpText?: string;
}

const WebhookField: React.FC<WebhookFieldProps> = ({
  label, placeholder, value, enabled, onToggle, onChange, onTest, testStatus, helpText,
}) => (
  <div style={styles.card}>
    <div style={styles.cardHeader}>
      <span style={styles.cardTitle}>{label}</span>
      <Toggle id={`toggle-${label}`} label="" checked={enabled} onChange={onToggle} />
    </div>
    {enabled && (
      <>
        <input
          type="url"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={styles.input}
          spellCheck={false}
        />
        {helpText && <p style={styles.helpText}>{helpText}</p>}
        <div style={styles.testRow}>
          <button
            onClick={onTest}
            disabled={!value || testStatus === 'sending'}
            style={{
              ...styles.testBtn,
              opacity: !value || testStatus === 'sending' ? 0.5 : 1,
            }}
          >
            {testStatus === 'sending' ? 'Sending…' : 'Send test message'}
          </button>
          {testStatus === 'ok' && <span style={styles.statusOk}>✅ Delivered</span>}
          {testStatus === 'fail' && <span style={styles.statusFail}>❌ Failed — check URL</span>}
        </div>
      </>
    )}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  // Seed initial state from cached non-sensitive prefs only; credentials start blank
  const [settings, setSettings] = useState<NotificationSettings>(() => ({
    ...DEFAULT_SETTINGS,
    ...loadLocalPrefs(),
  }));
  const [saved,    setSaved]    = useState(false);
  const [loading,  setLoading]  = useState(true);
  const [saveErr,  setSaveErr]  = useState('');
  const [testStatus, setTestStatus] = useState<Record<string, 'idle' | 'sending' | 'ok' | 'fail'>>({
    discord: 'idle',
    slack:   'idle',
    telegram:'idle',
  });

  // Load full settings (including credentials) from API on mount.
  // Credentials are never read from localStorage — only from the server.
  useEffect(() => {
    api.get<NotificationSettings>('/api/settings/notifications')
      .then((res) => {
        const merged = { ...DEFAULT_SETTINGS, ...res.data };
        setSettings(merged);
        // Cache only non-sensitive prefs for faster initial render next time
        cacheLocalPrefs(merged);
      })
      .catch(() => {
        // API unavailable — keep non-sensitive prefs already in state;
        // credential fields remain blank (safe default)
      })
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((patch: Partial<NotificationSettings>) =>
    setSettings((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaveErr('');
    try {
      await api.post('/api/settings/notifications', settings);
      // Only cache non-sensitive prefs after a successful server save
      cacheLocalPrefs(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setSaveErr(detail ?? 'Failed to save settings. Please try again.');
    }
  };

  const sendTest = async (channel: string) => {
    setTestStatus((prev) => ({ ...prev, [channel]: 'sending' }));
    try {
      await api.post('/notifications/test', { channel, settings });
      setTestStatus((prev) => ({ ...prev, [channel]: 'ok' }));
    } catch (_) {
      setTestStatus((prev) => ({ ...prev, [channel]: 'fail' }));
    }
    setTimeout(() => setTestStatus((prev) => ({ ...prev, [channel]: 'idle' })), 4000);
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.heading}>Settings</h1>

      {/* ── Notification Channels ─────────────────────────────────────────── */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Notification Channels</h2>
        <p style={styles.sectionDesc}>
          Configure where HOPEFX sends trade alerts, signals, and system events.
        </p>

        {/* Discord */}
        <WebhookField
          label="Discord"
          placeholder="https://discord.com/api/webhooks/…"
          value={settings.discord_webhook_url}
          enabled={settings.discord_enabled}
          onToggle={(v) => update({ discord_enabled: v })}
          onChange={(v) => update({ discord_webhook_url: v })}
          onTest={() => sendTest('discord')}
          testStatus={testStatus.discord}
          helpText="Create a webhook in Discord: Server Settings → Integrations → Webhooks → New Webhook."
        />

        {/* Slack */}
        <WebhookField
          label="Slack"
          placeholder="https://hooks.slack.com/services/…"
          value={settings.slack_webhook_url}
          enabled={settings.slack_enabled}
          onToggle={(v) => update({ slack_enabled: v })}
          onChange={(v) => update({ slack_webhook_url: v })}
          onTest={() => sendTest('slack')}
          testStatus={testStatus.slack}
          helpText="Create an Incoming Webhook at api.slack.com/apps → Your App → Incoming Webhooks."
        />

        {/* Telegram */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <span style={styles.cardTitle}>Telegram</span>
            <Toggle
              id="toggle-telegram"
              label=""
              checked={settings.telegram_enabled}
              onChange={(v) => update({ telegram_enabled: v })}
            />
          </div>
          {settings.telegram_enabled && (
            <>
              <input
                type="text"
                placeholder="Bot token (from @BotFather)"
                value={settings.telegram_bot_token}
                onChange={(e) => update({ telegram_bot_token: e.target.value })}
                style={{ ...styles.input, marginBottom: 8 }}
              />
              <input
                type="text"
                placeholder="Chat ID (e.g. -1001234567890)"
                value={settings.telegram_chat_id}
                onChange={(e) => update({ telegram_chat_id: e.target.value })}
                style={styles.input}
              />
              <div style={styles.testRow}>
                <button
                  onClick={() => sendTest('telegram')}
                  disabled={!settings.telegram_bot_token || !settings.telegram_chat_id || testStatus.telegram === 'sending'}
                  style={{
                    ...styles.testBtn,
                    opacity: (!settings.telegram_bot_token || !settings.telegram_chat_id) ? 0.5 : 1,
                  }}
                >
                  {testStatus.telegram === 'sending' ? 'Sending…' : 'Send test message'}
                </button>
                {testStatus.telegram === 'ok' && <span style={styles.statusOk}>✅ Delivered</span>}
                {testStatus.telegram === 'fail' && <span style={styles.statusFail}>❌ Failed — check token/chat ID</span>}
              </div>
            </>
          )}
        </div>

        {/* Email */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <span style={styles.cardTitle}>Email</span>
            <Toggle
              id="toggle-email"
              label=""
              checked={settings.email_enabled}
              onChange={(v) => update({ email_enabled: v })}
            />
          </div>
          {settings.email_enabled && (
            <input
              type="email"
              placeholder="alerts@example.com"
              value={settings.email_address}
              onChange={(e) => update({ email_address: e.target.value })}
              style={styles.input}
            />
          )}
        </div>
      </section>

      {/* ── Alert Triggers ────────────────────────────────────────────────── */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Alert Triggers</h2>
        <div style={styles.card}>
          <Toggle
            id="notify-trade"
            label="Trade executed"
            checked={settings.notify_on_trade}
            onChange={(v) => update({ notify_on_trade: v })}
          />
          <Toggle
            id="notify-signal"
            label="New signal generated"
            checked={settings.notify_on_signal}
            onChange={(v) => update({ notify_on_signal: v })}
          />
          <Toggle
            id="notify-error"
            label="System errors"
            checked={settings.notify_on_error}
            onChange={(v) => update({ notify_on_error: v })}
          />
          <Toggle
            id="notify-daily"
            label="Daily P&L summary"
            checked={settings.notify_on_daily_summary}
            onChange={(v) => update({ notify_on_daily_summary: v })}
          />
        </div>
      </section>

      {/* ── Save ─────────────────────────────────────────────────────────── */}
      <div style={styles.saveRow}>
        <button onClick={handleSave} style={{ ...styles.saveBtn, opacity: loading ? 0.6 : 1 }} disabled={loading}>
          {loading ? 'Loading…' : saved ? '✅ Saved' : 'Save settings'}
        </button>
        {saveErr && (
          <span style={{ fontSize: 12, color: '#fbbf24', marginLeft: 12 }}>
            ⚠️ {saveErr}
          </span>
        )}
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 680,
    margin: '0 auto',
    padding: '32px 16px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#f1f5f9',
    background: '#0f172a',
    minHeight: '100vh',
  },
  heading: { fontSize: 28, fontWeight: 700, marginBottom: 32, color: '#f8fafc' },
  section: { marginBottom: 40 },
  sectionTitle: { fontSize: 18, fontWeight: 600, marginBottom: 6, color: '#e2e8f0' },
  sectionDesc: { fontSize: 14, color: '#94a3b8', marginBottom: 16 },
  card: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 10,
    padding: '16px 20px',
    marginBottom: 12,
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 0,
  },
  cardTitle: { fontSize: 15, fontWeight: 600, color: '#e2e8f0' },
  input: {
    width: '100%',
    marginTop: 12,
    padding: '10px 12px',
    background: '#0f172a',
    border: '1px solid #475569',
    borderRadius: 6,
    color: '#f1f5f9',
    fontSize: 14,
    boxSizing: 'border-box',
    outline: 'none',
  },
  helpText: { fontSize: 12, color: '#64748b', marginTop: 6, marginBottom: 0 },
  testRow: { display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 },
  testBtn: {
    padding: '8px 16px',
    background: '#3b82f6',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    fontSize: 13,
    cursor: 'pointer',
    fontWeight: 500,
  },
  statusOk: { fontSize: 13, color: '#22c55e' },
  statusFail: { fontSize: 13, color: '#ef4444' },
  toggleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 0',
    cursor: 'pointer',
    userSelect: 'none',
  },
  toggleLabel: { fontSize: 14, color: '#cbd5e1' },
  toggleTrack: {
    width: 44,
    height: 24,
    borderRadius: 12,
    position: 'relative',
    cursor: 'pointer',
    transition: 'background 0.2s',
    flexShrink: 0,
  },
  toggleThumb: {
    position: 'absolute',
    top: 2,
    width: 20,
    height: 20,
    borderRadius: '50%',
    background: '#fff',
    transition: 'transform 0.2s',
    boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
  },
  saveRow: { display: 'flex', justifyContent: 'flex-end', marginTop: 8 },
  saveBtn: {
    padding: '12px 28px',
    background: '#22c55e',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 600,
    cursor: 'pointer',
  },
};

export default Settings;
