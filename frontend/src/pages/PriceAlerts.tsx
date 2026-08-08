/**
 * Price Alert System UI.
 *
 * Create threshold alerts → notify via Discord/Telegram/email.
 * Shows active alerts list with enable/disable toggle and alert history.
 *
 * Wires to: GET    /api/alerts/
 *           POST   /api/alerts/
 *           DELETE /api/alerts/{id}
 *           POST   /api/alerts/{id}/pause
 *           POST   /api/alerts/{id}/resume
 *           GET    /api/alerts/history/triggers
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore, selectTriggeredAlerts, selectFeedLive } from '../store';
import { LiveFeedNotice } from '../components/ui/LiveFeedNotice';
import { extractApiError, toSlashSymbol } from '../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AlertCondition {
  type: string;
  threshold: number;
  threshold_2?: number;
}

interface Alert {
  id: string;
  name: string;
  symbol: string;
  conditions: AlertCondition[];
  status: 'active' | 'triggered' | 'paused' | 'expired' | 'cancelled';
  priority: string;
  /** Optional — absent on alerts created before channels existed (audit #40). */
  notification_channels?: string[];
  created_at: string;
  trigger_count: number;
}

interface AlertTrigger {
  alert_id: string;
  alert_name: string;
  triggered_at: string;
  symbol: string;
  trigger_value: number;
}

type ConditionType = 'price_above' | 'price_below' | 'price_cross_above' | 'price_cross_below' | 'rsi_overbought' | 'rsi_oversold';

// ── Helpers ───────────────────────────────────────────────────────────────────

const CONDITION_LABELS: Record<string, string> = {
  price_above:       'Price rises above',
  price_below:       'Price falls below',
  price_cross_above: 'Price crosses above',
  price_cross_below: 'Price crosses below',
  rsi_overbought:    'RSI overbought (>70)',
  rsi_oversold:      'RSI oversold (<30)',
};

const STATUS_COLOR: Record<string, string> = {
  active:    '#4ade80',
  triggered: '#f97316',
  paused:    '#94a3b8',
  expired:   '#475569',
  cancelled: '#475569',
};

const SYMBOLS   = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'ETHUSD'];
const CHANNELS  = ['discord', 'telegram', 'email', 'push'];

// ── Component ─────────────────────────────────────────────────────────────────

const PriceAlerts: React.FC = () => {
  const navigate = useNavigate();
  const [alerts, setAlerts]       = useState<Alert[]>([]);
  const [history, setHistory]     = useState<AlertTrigger[]>([]);
  const [loading, setLoading]     = useState(true);
  const [loadErr, setLoadErr]     = useState<string | null>(null);
  const [tab, setTab]             = useState<'active' | 'history' | 'live'>('active');
  // Live triggered alerts from WebSocket store
  const wsTriggered = useStore(selectTriggeredAlerts);
  // …and whether that socket is actually delivering. Without this the page
  // renders identically whether alerts are being watched for or not, which is
  // the one thing it exists to tell you (F1-02).
  const feedLive = useStore(selectFeedLive);
  const [showForm, setShowForm]   = useState(false);
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState('');
  const [actionErr, setActionErr] = useState<string | null>(null);

  const [form, setForm] = useState({
    name: '',
    symbol: 'XAUUSD',
    condition_type: 'price_above' as ConditionType,
    threshold: '',
    channels: ['discord'] as string[],
    priority: 'high',
  });

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const fetchAlerts = useCallback(async () => {
    setLoadErr(null);
    try {
      const [alertsRes, histRes] = await Promise.allSettled([
        api.get<Alert[]>('/alerts/'),
        api.get<AlertTrigger[]>('/alerts/history/triggers'),
      ]);
      if (!mountedRef.current) return;
      if (alertsRes.status === 'fulfilled') {
        setAlerts(alertsRes.value.data ?? []);
      } else {
        setLoadErr('Failed to load alerts. Ensure the alerts API is running.');
      }
      if (histRes.status === 'fulfilled') setHistory(histRes.value.data ?? []);
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setLoadErr(extractApiError(err, 'Failed to load alerts.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAlerts(); }, [fetchAlerts]);

  const handleCreate = async () => {
    if (!form.name || !form.threshold) { setError('Name and threshold are required'); return; }
    setSaving(true);
    setError('');
    try {
      await api.post('/alerts/', {
        name: form.name,
        symbol: form.symbol,
        conditions: [{ type: form.condition_type, threshold: parseFloat(form.threshold) }],
        notification_channels: form.channels,
        priority: form.priority,
      });
      setShowForm(false);
      setForm({ name: '', symbol: 'XAUUSD', condition_type: 'price_above', threshold: '', channels: ['discord'], priority: 'high' });
      await fetchAlerts();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Failed to create alert'));
    }
    setSaving(false);
  };

  const handleDelete = async (id: string) => {
    setActionErr(null);
    try {
      await api.delete(`/alerts/${id}`);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (err: unknown) {
      setActionErr(extractApiError(err, 'Failed to delete alert.'));
    }
  };

  const handleToggle = async (alert: Alert) => {
    const action = alert.status === 'paused' ? 'resume' : 'pause';
    setActionErr(null);
    try {
      await api.post(`/alerts/${alert.id}/${action}`);
      await fetchAlerts();
    } catch (err: unknown) {
      setActionErr(extractApiError(err, `Failed to ${action} alert.`));
    }
  };

  const toggleChannel = (ch: string) => {
    setForm((f) => ({
      ...f,
      channels: f.channels.includes(ch) ? f.channels.filter((c) => c !== ch) : [...f.channels, ch],
    }));
  };

  return (
    <div className="page-content">
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Price Alerts</h1>
          <p style={s.subtitle}>Get notified via Discord, Telegram, or email when price conditions are met.</p>
        </div>
        <button onClick={() => setShowForm(!showForm)} style={s.createBtn}>
          {showForm ? '✕ Cancel' : '+ Create Alert'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div style={s.card}>
          <h2 style={s.cardTitle}>New Alert</h2>
          {error && <div style={s.errorBox}>{error}</div>}

          <div style={s.formGrid}>
            <div>
              <label style={s.label}>Alert Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Gold breaks 2100" style={s.input} />
            </div>
            <div>
              <label style={s.label}>Symbol</label>
              <select value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} style={s.select}>
                {SYMBOLS.map((sym) => <option key={sym} value={sym}>{sym}</option>)}
              </select>
            </div>
            <div>
              <label style={s.label}>Condition</label>
              <select value={form.condition_type} onChange={(e) => setForm({ ...form, condition_type: e.target.value as ConditionType })} style={s.select}>
                {Object.entries(CONDITION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label style={s.label}>Price / Level</label>
              <input type="number" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })}
                placeholder="e.g. 2100.00" style={s.input} />
            </div>
          </div>

          <label style={s.label}>Notification Channels</label>
          <div style={s.channelRow}>
            {CHANNELS.map((ch) => (
              <button key={ch} onClick={() => toggleChannel(ch)}
                style={{ ...s.channelBtn, ...(form.channels.includes(ch) ? s.channelBtnActive : {}) }}>
                {ch}
              </button>
            ))}
          </div>

          <label style={s.label}>Priority</label>
          <div style={s.channelRow}>
            {['low', 'medium', 'high', 'critical'].map((p) => (
              <button key={p} onClick={() => setForm({ ...form, priority: p })}
                style={{ ...s.channelBtn, ...(form.priority === p ? s.channelBtnActive : {}) }}>
                {p}
              </button>
            ))}
          </div>

          <button onClick={handleCreate} disabled={saving} style={s.saveBtn}>
            {saving ? 'Creating…' : 'Create Alert'}
          </button>
        </div>
      )}

      {/* A dead socket means no alert will reach this screen, whatever the
          list below says about being active (F1-02). */}
      <LiveFeedNotice live={feedLive} what="alert triggers" className="mb-3" />

      {/* Load / action errors */}
      {loadErr && <div style={s.errorBox}>{loadErr}</div>}
      {actionErr && <div style={{ ...s.errorBox, marginBottom: 12 }}>{actionErr}</div>}

      {/* Tabs */}
      <div style={s.tabs}>
        <button onClick={() => setTab('active')} style={{ ...s.tab, ...(tab === 'active' ? s.tabActive : {}) }}>
          Active Alerts ({alerts.filter((a) => a.status !== 'cancelled').length})
        </button>
        <button onClick={() => setTab('live')} style={{ ...s.tab, ...(tab === 'live' ? s.tabActive : {}) }}>
          Live Triggers {wsTriggered.length > 0 && (
            <span style={{ marginLeft: 6, background: '#f97316', color: '#fff', borderRadius: 10, fontSize: 10, padding: '1px 6px', fontWeight: 700 }}>
              {wsTriggered.length}
            </span>
          )}
        </button>
        <button onClick={() => setTab('history')} style={{ ...s.tab, ...(tab === 'history' ? s.tabActive : {}) }}>
          Trigger History
        </button>
      </div>

      {/* Active alerts */}
      {tab === 'active' && (
        loading ? <div style={s.empty}>Loading…</div> :
        alerts.length === 0 ? (
          <div style={{ ...s.empty, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <div style={{ fontSize: 36 }}>🔔</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#94a3b8' }}>No alerts yet</div>
            <div style={{ fontSize: 13, color: '#64748b' }}>Use the form above to create your first price alert.</div>
            <button onClick={() => navigate('/watchlist')}
              style={{ padding: '7px 18px', background: 'rgba(251,191,36,0.15)', border: '1px solid rgba(251,191,36,0.4)', borderRadius: 8, color: '#fbbf24', fontSize: 13, fontWeight: 700, cursor: 'pointer', marginTop: 4 }}>
              👁 Watchlist
            </button>
          </div>
        ) :
        alerts.map((alert) => (
          <div key={alert.id} style={s.alertRow}>
            <div style={{ ...s.statusDot, background: STATUS_COLOR[alert.status] ?? '#475569' }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 14 }}>{alert.name}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                {alert.symbol} · {(alert.conditions ?? []).map((c) => `${CONDITION_LABELS[c.type] ?? c.type} ${c.threshold}`).join(', ')}
                {(alert.notification_channels?.length ?? 0) > 0 && <>{' · '}{alert.notification_channels!.join(', ')}</>}
              </div>
            </div>
            <div style={{ fontSize: 12, color: '#475569', marginRight: 12 }}>
              Triggered {alert.trigger_count}×
            </div>
            <button
              onClick={() => navigate('/trade', { state: { signal: { symbol: toSlashSymbol(alert.symbol) } } })}
              style={{ background: 'rgba(96,165,250,0.12)', border: '1px solid rgba(96,165,250,0.35)', borderRadius: 5, color: '#60a5fa', fontSize: 11, fontWeight: 700, padding: '4px 10px', cursor: 'pointer', marginRight: 6 }}
              title={`Trade ${alert.symbol}`}
            >
              ⚡ Trade
            </button>
            <button onClick={() => handleToggle(alert)} style={s.iconBtn}
              title={alert.status === 'paused' ? 'Resume' : 'Pause'}>
              {alert.status === 'paused' ? '▶' : '⏸'}
            </button>
            <button onClick={() => handleDelete(alert.id)}
              style={{ ...s.iconBtn, color: '#f87171' }} title="Delete">
              🗑
            </button>
          </div>
        ))
      )}

      {/* Live WS triggers */}
      {tab === 'live' && (
        wsTriggered.length === 0
          ? (
            // Empty vs unknown, the S10-01 distinction. "No live triggers yet"
            // is a statement about the market; with the socket down it is a
            // statement about the socket, and the two read identically.
            feedLive
              ? <div style={s.empty}>No live triggers yet. Alerts fire here in real-time via WebSocket.</div>
              : (
                <div style={{ ...s.empty, color: '#ffb800' }} role="status" aria-live="polite">
                  ⚠️ Live trigger feed is not connected. Alerts may have fired
                  without appearing here — check the Trigger History tab.
                </div>
              )
          )
          : wsTriggered.map((t) => (
            <div key={t.id} style={{ ...s.historyRow, background: '#1e293b', borderRadius: 8, padding: '10px 14px', marginBottom: 6 }}>
              <span style={{ color: '#f97316', fontSize: 16 }}>⚡</span>
              <div style={{ flex: 1 }}>
                <span style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 13 }}>{t.symbol}</span>
                <span style={{ color: '#64748b', fontSize: 12, marginLeft: 8 }}>{t.condition}</span>
                {t.message && <span style={{ color: '#94a3b8', fontSize: 12, marginLeft: 8 }}>{t.message}</span>}
              </div>
              <span style={{ fontSize: 12, color: '#475569' }}>
                {new Date(t.triggered_at).toLocaleString()}
              </span>
              <button
                onClick={() => navigate('/trade', { state: { signal: { symbol: toSlashSymbol(t.symbol) } } })}
                style={{ background: 'rgba(249,115,22,0.15)', border: '1px solid rgba(249,115,22,0.4)', borderRadius: 5, color: '#f97316', fontSize: 11, fontWeight: 800, padding: '4px 10px', cursor: 'pointer', marginLeft: 8 }}
              >
                ⚡ Trade Now
              </button>
            </div>
          ))
      )}

      {/* History */}
      {tab === 'history' && (
        history.length === 0 ? <div style={s.empty}>No triggers yet.</div> :
        history.slice(0, 50).map((t, i) => (
          <div key={i} style={s.historyRow}>
            <span style={{ color: '#f97316', fontSize: 13 }}>⚡</span>
            <div style={{ flex: 1 }}>
              <span style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 13 }}>{t.alert_name}</span>
              <span style={{ color: '#64748b', fontSize: 12, marginLeft: 8 }}>
                {t.symbol} @ {t.trigger_value}
              </span>
            </div>
            <span style={{ fontSize: 12, color: '#475569' }}>
              {new Date(t.triggered_at).toLocaleString()}
            </span>
          </div>
        ))
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:             { padding: 24, maxWidth: 900, margin: '0 auto' },
  header:           { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 },
  title:            { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:         { fontSize: 14, color: '#64748b', margin: 0 },
  createBtn:        { background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '10px 18px' },
  card:             { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24, marginBottom: 20 },
  cardTitle:        { fontSize: 18, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px' },
  formGrid:         { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 },
  label:            { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6, fontWeight: 500 },
  input:            { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14, boxSizing: 'border-box' },
  select:           { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14 },
  channelRow:       { display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' },
  channelBtn:       { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', padding: '6px 14px', fontSize: 13 },
  channelBtnActive: { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  saveBtn:          { background: '#059669', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '10px 24px', marginTop: 8 },
  tabs:             { display: 'flex', gap: 8, marginBottom: 16 },
  tab:              { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', padding: '8px 16px', fontSize: 13 },
  tabActive:        { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  alertRow:         { display: 'flex', alignItems: 'center', gap: 12, background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', marginBottom: 8 },
  statusDot:        { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  iconBtn:          { background: 'transparent', border: 'none', color: '#64748b', fontSize: 16, cursor: 'pointer', padding: '4px 6px' },
  historyRow:       { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid #1e293b' },
  errorBox:         { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '10px 14px', color: '#f87171', fontSize: 14, marginBottom: 16 },
  empty:            { textAlign: 'center', color: '#475569', padding: 40 },
};

export default PriceAlerts;
