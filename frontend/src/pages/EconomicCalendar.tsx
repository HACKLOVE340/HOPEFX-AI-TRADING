/**
 * Economic Calendar page.
 *
 * Shows upcoming high-impact events (NFP, CPI, FOMC) with:
 * - Countdown timers
 * - Impact ratings (red/amber/green)
 * - Auto-pause trading toggle
 *
 * Wires to: GET /api/calendar/upcoming
 *           GET /api/calendar/auto-pause
 *           POST /api/calendar/auto-pause
 */

import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../hooks/useApi';

// ── Types ─────────────────────────────────────────────────────────────────────

interface CalendarEvent {
  title: string;
  event_type: string;
  importance: 'low' | 'medium' | 'high' | 'critical';
  scheduled_time: string;
  country: string;
  currency: string | null;
  forecast: number | null;
  previous: number | null;
  actual: number | null;
  minutes_until: number;
  is_high_impact: boolean;
}

interface AutoPauseConfig {
  enabled: boolean;
  minutes_before: number;
  min_importance: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const IMPORTANCE_COLOR: Record<string, string> = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#eab308',
  low:      '#22c55e',
};

const IMPORTANCE_LABEL: Record<string, string> = {
  critical: '🔴 Critical',
  high:     '🟠 High',
  medium:   '🟡 Medium',
  low:      '🟢 Low',
};

const FLAG: Record<string, string> = {
  US: '🇺🇸', EU: '🇪🇺', UK: '🇬🇧', JP: '🇯🇵', CA: '🇨🇦',
  AU: '🇦🇺', NZ: '🇳🇿', CH: '🇨🇭', CN: '🇨🇳',
};

function formatCountdown(minutes: number): string {
  if (minutes <= 0) return 'Now';
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h < 24) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
}

// ── Component ─────────────────────────────────────────────────────────────────

const EconomicCalendar: React.FC = () => {
  const [events, setEvents]           = useState<CalendarEvent[]>([]);
  const [loading, setLoading]         = useState(true);
  const [filter, setFilter]           = useState<'all' | 'high'>('all');
  const [autoPause, setAutoPause]     = useState<AutoPauseConfig>({ enabled: false, minutes_before: 30, min_importance: 'high' });
  const [savingPause, setSavingPause] = useState(false);
  const [, setTick]                   = useState(0);

  const fetchEvents = useCallback(async () => {
    try {
      const url = filter === 'high' ? '/api/calendar/high-impact' : '/api/calendar/upcoming?hours=168';
      const res = await api.get<CalendarEvent[]>(url);
      setEvents(res.data);
    } catch { /* silent */ }
    setLoading(false);
  }, [filter]);

  const fetchAutoPause = useCallback(async () => {
    try {
      const res = await api.get<AutoPauseConfig>('/calendar/auto-pause');
      setAutoPause(res.data);
    } catch { /* silent */ }
  }, []);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);
  useEffect(() => { fetchAutoPause(); }, [fetchAutoPause]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const handleToggleAutoPause = async () => {
    setSavingPause(true);
    const next = { ...autoPause, enabled: !autoPause.enabled };
    try {
      const res = await api.post<AutoPauseConfig>('/calendar/auto-pause', next);
      setAutoPause(res.data);
    } catch { /* silent */ }
    setSavingPause(false);
  };

  // Group events by date
  const grouped = events.reduce<Record<string, CalendarEvent[]>>((acc, ev) => {
    const date = formatDate(ev.scheduled_time);
    if (!acc[date]) acc[date] = [];
    acc[date].push(ev);
    return acc;
  }, {});

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Economic Calendar</h1>
          <p style={s.subtitle}>Upcoming market-moving events. Red = high impact on gold/USD.</p>
        </div>

        {/* Auto-pause toggle */}
        <div style={s.autoPauseCard}>
          <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 4 }}>Auto-pause trading</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              onClick={handleToggleAutoPause}
              disabled={savingPause}
              style={{
                ...s.toggleBtn,
                background: autoPause.enabled ? '#166534' : '#334155',
                color: autoPause.enabled ? '#4ade80' : '#94a3b8',
              }}
            >
              {autoPause.enabled ? '⏸ ON' : '▶ OFF'}
            </button>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              {autoPause.enabled
                ? `Pauses ${autoPause.minutes_before}min before ${autoPause.min_importance}+ events`
                : 'Enable to auto-pause before high-impact events'}
            </span>
          </div>
        </div>
      </div>

      {/* Filter tabs */}
      <div style={s.tabs}>
        {(['all', 'high'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{ ...s.tab, ...(filter === f ? s.tabActive : {}) }}
          >
            {f === 'all' ? 'All Events (7 days)' : '🔴 High Impact Only'}
          </button>
        ))}
      </div>

      {/* Events */}
      {loading ? (
        <div style={s.empty}>Loading calendar…</div>
      ) : events.length === 0 ? (
        <div style={s.empty}>No events found.</div>
      ) : (
        Object.entries(grouped).map(([date, dayEvents]) => (
          <div key={date} style={s.dayGroup}>
            <div style={s.dayHeader}>{date}</div>
            {dayEvents.map((ev, i) => (
              <EventRow key={i} event={ev} />
            ))}
          </div>
        ))
      )}
    </div>
  );
};

// ── Event Row ─────────────────────────────────────────────────────────────────

const EventRow: React.FC<{ event: CalendarEvent }> = ({ event: ev }) => {
  const color = IMPORTANCE_COLOR[ev.importance] ?? '#64748b';
  const flag  = FLAG[ev.country] ?? '🌐';

  return (
    <div style={{ ...s.eventRow, borderLeft: `3px solid ${color}` }}>
      <div style={s.eventTime}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{formatTime(ev.scheduled_time)}</div>
        <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{formatCountdown(ev.minutes_until)}</div>
      </div>

      <div style={s.eventMain}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{flag}</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{ev.title}</span>
          {ev.currency && <span style={s.currencyBadge}>{ev.currency}</span>}
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
          {IMPORTANCE_LABEL[ev.importance]}
          {ev.minutes_until <= 60 && ev.minutes_until > 0 && (
            <span style={{ color: '#f97316', marginLeft: 8 }}>⚠ Approaching</span>
          )}
        </div>
      </div>

      <div style={s.eventData}>
        {ev.forecast !== null && (
          <div style={s.dataItem}>
            <span style={s.dataLabel}>Forecast</span>
            <span style={s.dataValue}>{ev.forecast}</span>
          </div>
        )}
        {ev.previous !== null && (
          <div style={s.dataItem}>
            <span style={s.dataLabel}>Previous</span>
            <span style={s.dataValue}>{ev.previous}</span>
          </div>
        )}
        {ev.actual !== null && (
          <div style={s.dataItem}>
            <span style={s.dataLabel}>Actual</span>
            <span style={{
              ...s.dataValue,
              color: ev.forecast !== null
                ? ev.actual > ev.forecast ? '#4ade80' : '#f87171'
                : '#f1f5f9',
            }}>{ev.actual}</span>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: 24, maxWidth: 900, margin: '0 auto' },
  header:        { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 16 },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:      { fontSize: 14, color: '#64748b', margin: 0 },
  autoPauseCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 16px', minWidth: 260 },
  toggleBtn:     { border: 'none', borderRadius: 6, cursor: 'pointer', padding: '6px 14px', fontWeight: 700, fontSize: 13 },
  tabs:          { display: 'flex', gap: 8, marginBottom: 20 },
  tab:           { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', padding: '8px 16px', fontSize: 13 },
  tabActive:     { background: '#1e3a5f', borderColor: '#3b82f6', color: '#60a5fa' },
  dayGroup:      { marginBottom: 24 },
  dayHeader:     { fontSize: 13, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8, paddingBottom: 6, borderBottom: '1px solid #1e293b' },
  eventRow:      { display: 'flex', alignItems: 'center', gap: 16, background: '#1e293b', borderRadius: 8, padding: '12px 16px', marginBottom: 6 },
  eventTime:     { minWidth: 60, textAlign: 'center' },
  eventMain:     { flex: 1 },
  eventData:     { display: 'flex', gap: 16 },
  dataItem:      { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 60 },
  dataLabel:     { fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: 0.5 },
  dataValue:     { fontSize: 14, fontWeight: 600, color: '#f1f5f9', marginTop: 2 },
  currencyBadge: { background: '#0f172a', border: '1px solid #334155', borderRadius: 4, color: '#94a3b8', fontSize: 11, padding: '1px 6px' },
  empty:         { textAlign: 'center', color: '#475569', padding: 40 },
};

export default EconomicCalendar;
