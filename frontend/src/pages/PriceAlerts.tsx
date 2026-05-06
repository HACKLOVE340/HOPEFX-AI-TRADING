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
import { Link } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
import { api } from '../hooks/useApi';
import { useStore, selectTriggeredAlerts } from '../store';
import { useToast } from '../components/Toast';

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
  notification_channels: string[];
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

// ── Alert timeline chart (SVG) ────────────────────────────────────────────────

const AlertTimelineChart: React.FC<{ history: AlertTrigger[] }> = ({ history }) => {
  if (history.length < 2) return (
    <div style={{ textAlign: 'center', color: '#475569', padding: '20px 0', fontSize: 12 }}>
      Need 2+ triggers to show timeline
    </div>
  );

  const W = 600; const H = 60;
  const sorted = [...history].sort((a, b) => new Date(a.triggered_at).getTime() - new Date(b.triggered_at).getTime());
  const minT = new Date(sorted[0]!.triggered_at).getTime();
  const maxT = new Date(sorted[sorted.length - 1]!.triggered_at).getTime();
  const rangeT = maxT - minT || 1;

  // Group by symbol for color
  const symbols = Array.from(new Set(sorted.map((t) => t.symbol)));
  const COLORS  = ['#3b82f6', '#00e676', '#f59e0b', '#a78bfa', '#f87171', '#38bdf8'];
  const symColor = Object.fromEntries(symbols.map((s, i) => [s, COLORS[i % COLORS.length]!]));

  return (
    <div>
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>Alert Trigger Timeline</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 60 }}>
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="#1e2d3d" strokeWidth={1} />
        {sorted.map((t, i) => {
          const x = ((new Date(t.triggered_at).getTime() - minT) / rangeT) * (W - 20) + 10;
          const color = symColor[t.symbol] ?? '#3b82f6';
          return (
            <g key={i}>
              <circle cx={x} cy={H / 2} r={5} fill={color} opacity={0.85}>
                <title>{t.symbol} @ {t.trigger_value} — {new Date(t.triggered_at).toLocaleString()}</title>
              </circle>
              <line x1={x} y1={H / 2 - 8} x2={x} y2={H / 2 + 8} stroke={color} strokeWidth={1.5} opacity={0.5} />
            </g>
          );
        })}
      </svg>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
        {symbols.map((sym) => (
          <span key={sym} style={{ fontSize: 10, color: symColor[sym], display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: symColor[sym], display: 'inline-block' }} />
            {sym}
          </span>
        ))}
      </div>
    </div>
  );
};

// ── Multi-condition row ───────────────────────────────────────────────────────

interface ConditionRow {
  type: ConditionType;
  threshold: string;
}

const MultiConditionBuilder: React.FC<{
  conditions: ConditionRow[];
  onChange: (c: ConditionRow[]) => void;
}> = ({ conditions, onChange }) => {
  const add = () => onChange([...conditions, { type: 'price_above', threshold: '' }]);
  const remove = (i: number) => onChange(conditions.filter((_, idx) => idx !== i));
  const update = (i: number, patch: Partial<ConditionRow>) =>
    onChange(conditions.map((c, idx) => idx === i ? { ...c, ...patch } : c));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {conditions.map((c, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {i > 0 && <span style={{ fontSize: 11, color: '#475569', width: 28, textAlign: 'center', flexShrink: 0 }}>AND</span>}
          {i === 0 && <span style={{ width: 28, flexShrink: 0 }} />}
          <select value={c.type} onChange={(e) => update(i, { type: e.target.value as ConditionType })} style={{ ...s.select, flex: 2 }}>
            {Object.entries(CONDITION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input
            type="number"
            value={c.threshold}
            onChange={(e) => update(i, { threshold: e.target.value })}
            placeholder="Level"
            style={{ ...s.input, flex: 1 }}
          />
          {conditions.length > 1 && (
            <button onClick={() => remove(i)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 16, padding: '0 4px' }}>×</button>
          )}
        </div>
      ))}
      <button onClick={add} style={{ alignSelf: 'flex-start', background: 'transparent', border: '1px dashed #334155', borderRadius: 6, color: '#64748b', fontSize: 12, cursor: 'pointer', padding: '4px 12px' }}>
        + Add condition
      </button>
    </div>
  );
};

// ── Channel selector with icons ───────────────────────────────────────────────

const CHANNEL_META: Record<string, { icon: string; label: string; color: string }> = {
  discord:  { icon: '💬', label: 'Discord',  color: '#5865f2' },
  telegram: { icon: '✈️',  label: 'Telegram', color: '#0088cc' },
  email:    { icon: '📧', label: 'Email',    color: '#10b981' },
  push:     { icon: '🔔', label: 'Push',     color: '#f59e0b' },
};

const ChannelSelector: React.FC<{
  selected: string[];
  onChange: (channels: string[]) => void;
}> = ({ selected, onChange }) => {
  const toggle = (ch: string) =>
    onChange(selected.includes(ch) ? selected.filter((c) => c !== ch) : [...selected, ch]);

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {Object.entries(CHANNEL_META).map(([ch, meta]) => {
        const active = selected.includes(ch);
        return (
          <button
            key={ch}
            onClick={() => toggle(ch)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
              border: `1px solid ${active ? meta.color : '#334155'}`,
              background: active ? `${meta.color}22` : 'transparent',
              color: active ? meta.color : '#64748b',
              fontSize: 12, fontWeight: 600, transition: 'all 0.15s',
            }}
          >
            <span>{meta.icon}</span> {meta.label}
            {active && <span style={{ fontSize: 10, color: meta.color }}>✓</span>}
          </button>
        );
      })}
    </div>
  );
};

// ── Component ─────────────────────────────────────────────────────────────────

const PriceAlerts: React.FC = () => {
  const toast = useToast();
  const [alerts, setAlerts]       = useState<Alert[]>([]);
  const [history, setHistory]     = useState<AlertTrigger[]>([]);
  const [loading, setLoading]     = useState(true);
  const [loadErr, setLoadErr]     = useState<string | null>(null);
  const [tab, setTab]             = useState<'active' | 'history' | 'live'>('active');
  // Live triggered alerts from WebSocket store
  const wsTriggered = useStore(selectTriggeredAlerts);
  const [showForm, setShowForm]   = useState(false);
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState('');
  const [actionErr, setActionErr] = useState<string | null>(null);

  const [form, setForm] = useState({
    name: '',
    symbol: 'XAUUSD',
    channels: ['discord'] as string[],
    priority: 'high',
  });
  const [conditions, setConditions] = useState<ConditionRow[]>([{ type: 'price_above', threshold: '' }]);

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
      const msg = err instanceof Error ? err.message : 'Failed to load alerts.';
      setLoadErr(msg);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAlerts(); }, [fetchAlerts]);

  const handleCreate = async () => {
    if (!form.name) { setError('Alert name is required'); return; }
    if (conditions.some((c) => !c.threshold)) { setError('All conditions need a threshold'); return; }
    setSaving(true);
    setError('');
    try {
      await api.post('/alerts/', {
        name: form.name,
        symbol: form.symbol,
        conditions: conditions.map((c) => ({ type: c.type, threshold: parseFloat(c.threshold) })),
        notification_channels: form.channels,
        priority: form.priority,
      });
      setShowForm(false);
      setForm({ name: '', symbol: 'XAUUSD', channels: ['discord'], priority: 'high' });
      setConditions([{ type: 'price_above', threshold: '' }]);
      toast.success('Alert created.');
      await fetchAlerts();
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message ?? 'Failed to create alert';
      setError(msg);
      toast.error(msg);
    }
    setSaving(false);
  };

  const handleDelete = async (id: string) => {
    setActionErr(null);
    try {
      await api.delete(`/alerts/${id}`);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      toast.success('Alert deleted.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to delete alert.';
      setActionErr(msg);
      toast.error(msg);
    }
  };

  const handleToggle = async (alert: Alert) => {
    const action = alert.status === 'paused' ? 'resume' : 'pause';
    setActionErr(null);
    try {
      await api.post(`/alerts/${alert.id}/${action}`);
      toast.success(`Alert ${action}d.`);
      await fetchAlerts();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : `Failed to ${action} alert.`;
      setActionErr(msg);
      toast.error(msg);
    }
  };

  return (
    <div style={s.page}>
      <PageHeader
        title="Price Alerts"
        subtitle="Get notified via Discord, Telegram, or email when price conditions are met."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Watchlist', href: '/watchlist' },
          { label: 'Price Alerts' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link to="/watchlist" style={{ padding: '6px 12px', background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.3)', borderRadius: 7, color: '#38bdf8', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>👁 Watchlist</Link>
            <Link to="/trade"     style={{ padding: '6px 12px', background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>⚡ Trade</Link>
            <button onClick={() => setShowForm(!showForm)} style={s.createBtn}>
              {showForm ? '✕ Cancel' : '+ Create Alert'}
            </button>
          </div>
        }
      />

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
          </div>

          <label style={{ ...s.label, marginBottom: 10 }}>Conditions (AND logic)</label>
          <MultiConditionBuilder conditions={conditions} onChange={setConditions} />

          <label style={{ ...s.label, marginTop: 16, marginBottom: 8 }}>Notification Channels</label>
          <ChannelSelector selected={form.channels} onChange={(channels) => setForm({ ...form, channels })} />

          <label style={{ ...s.label, marginTop: 16 }}>Priority</label>
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
          <EmptyState
            icon="🔔"
            title="No alerts yet"
            description="Create a price alert to get notified when your target levels are hit."
            action={
              <button
                onClick={() => setShowForm(true)}
                style={{ padding: '8px 18px', background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
              >
                + Create Alert
              </button>
            }
          />
        ) :
        alerts.map((alert) => (
          <div key={alert.id} style={s.alertRow}>
            <div style={{ ...s.statusDot, background: STATUS_COLOR[alert.status] ?? '#475569' }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 14 }}>{alert.name}</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                {alert.symbol} · {alert.conditions.map((c) => `${CONDITION_LABELS[c.type] ?? c.type} ${c.threshold}`).join(', ')}
                {' · '}{alert.notification_channels.join(', ')}
              </div>
            </div>
            <div style={{ fontSize: 12, color: '#475569', marginRight: 12 }}>
              Triggered {alert.trigger_count}×
            </div>
            <Link
              to="/trade"
              state={{ signal: { symbol: alert.symbol.slice(0, 3) + '/' + alert.symbol.slice(3) } }}
              style={{ background: 'rgba(96,165,250,0.12)', border: '1px solid rgba(96,165,250,0.35)', borderRadius: 5, color: '#60a5fa', fontSize: 11, fontWeight: 700, padding: '4px 10px', textDecoration: 'none', marginRight: 6 }}
              title={`Trade ${alert.symbol}`}
            >
              ⚡ Trade
            </Link>
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
          ? <div style={s.empty}>No live triggers yet. Alerts fire here in real-time via WebSocket.</div>
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
              <Link
                to="/trade"
                state={{ signal: { symbol: t.symbol.slice(0, 3) + '/' + t.symbol.slice(3) } }}
                style={{ background: 'rgba(249,115,22,0.15)', border: '1px solid rgba(249,115,22,0.4)', borderRadius: 5, color: '#f97316', fontSize: 11, fontWeight: 800, padding: '4px 10px', textDecoration: 'none', marginLeft: 8 }}
              >
                ⚡ Trade Now
              </Link>
            </div>
          ))
      )}

      {/* History */}
      {tab === 'history' && (
        history.length === 0 ? <div style={s.empty}>No triggers yet.</div> :
        <>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px', marginBottom: 16 }}>
            <AlertTimelineChart history={history} />
          </div>
          {history.slice(0, 50).map((t, i) => (
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
          ))}
        </>
      )}

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/calendar" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📅 Economic Calendar</Link>
        <Link to="/watchlist" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>👁️ Watchlist</Link>
        <Link to="/signals" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📡 Signal Feed</Link>
        <Link to="/trade" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>⚡ Trade</Link>
      </div>
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
