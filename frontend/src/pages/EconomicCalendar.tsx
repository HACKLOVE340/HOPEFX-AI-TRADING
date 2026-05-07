/**
 * Economic Calendar page.
 *
 * Shows upcoming high-impact events (NFP, CPI, FOMC) with:
 * - Countdown timers
 * - Impact ratings (red/amber/green)
 * - Auto-pause trading toggle
 * - MacroCalendar panel (data-layer events with gold impact scores)
 *
 * Wires to:
 *   GET  /api/calendar/upcoming        — CalendarEvent[]
 *   GET  /api/calendar/high-impact     — CalendarEvent[]
 *   GET  /api/calendar/auto-pause      — AutoPauseConfig
 *   POST /api/calendar/auto-pause      — AutoPauseConfig
 *   GET  /api/data-layer/macro         — MacroResponse (via useMacro hook)
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
import { useToast } from '../components/Toast';
import { calendarApi } from '../hooks/useApi';
import { useMacro } from '../hooks/useOrchestratorData';
import { useStore, selectMacro } from '../store';
import { MacroCalendar } from '../components/panels/MacroCalendar';
import { PanelSkeleton } from '../components/ui/Skeleton';

// ── Types ─────────────────────────────────────────────────────────────────────

interface CalendarEvent {
  title:          string;
  event_type:     string;
  importance:     'low' | 'medium' | 'high' | 'critical';
  scheduled_time: string;
  country:        string;
  currency:       string | null;
  forecast:       number | null;
  previous:       number | null;
  actual:         number | null;
  minutes_until:  number;
  is_high_impact: boolean;
}

interface AutoPauseConfig {
  enabled:        boolean;
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

// ── Event Row ─────────────────────────────────────────────────────────────────

// ── Live countdown hook ───────────────────────────────────────────────────────

function useLiveCountdown(scheduledTime: string): string {
  const [display, setDisplay] = useState('');
  useEffect(() => {
    const update = () => {
      const diff = Math.floor((new Date(scheduledTime).getTime() - Date.now()) / 1000);
      if (diff <= 0) { setDisplay('Now'); return; }
      const h = Math.floor(diff / 3600);
      const m = Math.floor((diff % 3600) / 60);
      const s = diff % 60;
      if (h > 0) setDisplay(`${h}h ${m}m`);
      else if (m > 0) setDisplay(`${m}m ${s}s`);
      else setDisplay(`${s}s`);
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [scheduledTime]);
  return display;
}

const EventRow: React.FC<{ event: CalendarEvent; subscribed: boolean; onSubscribe: () => void }> = ({ event: ev, subscribed, onSubscribe }) => {
  const color      = IMPORTANCE_COLOR[ev.importance] ?? '#64748b';
  const flag       = FLAG[ev.country] ?? '🌐';
  const isHigh     = ev.importance === 'high' || ev.importance === 'critical';
  const countdown  = useLiveCountdown(ev.scheduled_time);
  const isImminent = ev.minutes_until > 0 && ev.minutes_until <= 30;

  return (
    <div style={{
      ...s.eventRow,
      borderLeft: `3px solid ${color}`,
      background: isImminent ? 'rgba(249,115,22,0.04)' : undefined,
    }}>
      <div style={s.eventTime}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{formatTime(ev.scheduled_time)}</div>
        <div style={{
          fontSize: 11, marginTop: 2, fontWeight: isImminent ? 700 : 400,
          color: isImminent ? '#f97316' : '#475569',
          fontFamily: 'monospace',
        }}>
          {countdown}
        </div>
      </div>

      <div style={s.eventMain}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16 }}>{flag}</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{ev.title}</span>
          {ev.currency && <span style={s.currencyBadge}>{ev.currency}</span>}
          {isImminent && <span style={{ fontSize: 10, color: '#f97316', fontWeight: 700 }}>⚠ IMMINENT</span>}
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
          {IMPORTANCE_LABEL[ev.importance]}
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
        <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          {isHigh && (
            <Link
              to="/trade"
              style={{ padding: '3px 10px', borderRadius: 4, background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', color: '#60a5fa', fontSize: 10, fontWeight: 700, textDecoration: 'none', whiteSpace: 'nowrap' }}
              title="Plan a trade around this event"
            >
              ⚡ Trade
            </Link>
          )}
          <button
            onClick={onSubscribe}
            style={{
              padding: '3px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 10, fontWeight: 700,
              background: subscribed ? 'rgba(0,230,118,0.1)' : 'transparent',
              border: `1px solid ${subscribed ? 'rgba(0,230,118,0.4)' : '#334155'}`,
              color: subscribed ? '#00e676' : '#64748b',
              whiteSpace: 'nowrap',
            }}
            title={subscribed ? 'Unsubscribe from this event' : 'Subscribe to get notified'}
          >
            {subscribed ? '🔔 On' : '🔕 Off'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

type Tab = 'calendar' | 'macro';

type ImpactFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';

const EconomicCalendar: React.FC = () => {
  const toast = useToast();
  const [tab, setTab]               = useState<Tab>('calendar');
  const [events, setEvents]         = useState<CalendarEvent[]>([]);
  const [loading, setLoading]       = useState(true);
  const [fetchErr, setFetchErr]     = useState<string | null>(null);
  const [filter, setFilter]         = useState<'all' | 'high'>('all');
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>('all');
  const [subscribed, setSubscribed] = useState<Set<string>>(new Set());
  const [autoPause, setAutoPause]   = useState<AutoPauseConfig>({ enabled: false, minutes_before: 30, min_importance: 'high' });
  const [pauseErr, setPauseErr]     = useState<string | null>(null);
  const [savingPause, setSavingPause] = useState(false);
  const [, setTick]                 = useState(0);

  // Data-layer macro events (via TanStack Query + Zustand)
  useMacro();
  const macro = useStore(selectMacro);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setFetchErr(null);
    try {
      const res = filter === 'high'
        ? await calendarApi.highImpact()
        : await calendarApi.upcoming(168);
      if (!mountedRef.current) return;
      const raw = res.data as CalendarEvent[] | { events?: CalendarEvent[] };
      setEvents(Array.isArray(raw) ? raw : (raw.events ?? []));
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setEvents([]);
      setFetchErr(err instanceof Error ? err.message : 'Failed to load calendar events.');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [filter]);

  const fetchAutoPause = useCallback(async () => {
    try {
      const res = await calendarApi.autoPause();
      if (!mountedRef.current) return;
      setAutoPause(res.data);
    } catch {
      // Auto-pause config is optional — silently default to disabled
    }
  }, []);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);
  useEffect(() => { fetchAutoPause(); }, [fetchAutoPause]);

  // Refresh countdown every 30s
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const handleToggleAutoPause = async () => {
    setSavingPause(true);
    setPauseErr(null);
    const next = { ...autoPause, enabled: !autoPause.enabled };
    try {
      const res = await calendarApi.setAutoPause(next);
      setAutoPause(res.data);
    } catch (err: unknown) {
      setPauseErr(err instanceof Error ? err.message : 'Failed to update auto-pause setting.');
    } finally {
      setSavingPause(false);
    }
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
      <PageHeader
        title="Economic Calendar"
        icon="📅"
        subtitle="Upcoming market-moving events. Red = high impact on gold/USD."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Economic Calendar' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Link to="/geopolitical" style={{ padding: '6px 12px', background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>🌍 Geopolitical</Link>
            <Link to="/correlation"  style={{ padding: '6px 12px', background: 'rgba(96,165,250,0.1)',  border: '1px solid rgba(96,165,250,0.3)',  borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>📊 Correlation</Link>
            <Link to="/trade"        style={{ padding: '6px 12px', background: 'rgba(74,222,128,0.1)',  border: '1px solid rgba(74,222,128,0.3)',  borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>⚡ Trade</Link>
          </div>
        }
      />

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
                color:      autoPause.enabled ? '#4ade80' : '#94a3b8',
                opacity:    savingPause ? 0.6 : 1,
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
          {pauseErr && (
            <div style={{ fontSize: 12, color: '#f87171', marginTop: 6 }}>{pauseErr}</div>
          )}
        </div>

      {/* Blackout banner */}
      {macro?.is_blackout && (
        <div style={{
          background: '#450a0a', border: '1px solid #dc2626', borderRadius: 8,
          padding: '10px 16px', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 10,
          color: '#f87171', fontSize: 13, fontWeight: 600,
        }}>
          🔴 Trading Blackout Active — high-impact event imminent. Order submission is paused.
          {macro.impact_score != null && (
            <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 400, color: '#fca5a5' }}>
              Impact score: {(macro.impact_score * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}

      {/* Tab bar */}
      <div style={s.tabs}>
        {(['calendar', 'macro'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}
          >
            {t === 'calendar' ? '📅 Calendar' : '📊 Macro Data Layer'}
          </button>
        ))}
      </div>

      {/* ── Calendar tab ──────────────────────────────────────────────────── */}
      {tab === 'calendar' && (
        <>
          {/* Filter row: legacy high/all + impact chips */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {(['all', 'high'] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} style={{ ...s.tab, ...(filter === f ? s.tabActive : {}) }}>
                {f === 'all' ? 'All Events' : '🔴 High Impact'}
              </button>
            ))}
            <span style={{ color: '#334155', fontSize: 12 }}>|</span>
            {(['all', 'critical', 'high', 'medium', 'low'] as ImpactFilter[]).map((imp) => {
              const active = impactFilter === imp;
              const color  = imp === 'all' ? '#64748b' : (IMPORTANCE_COLOR[imp] ?? '#64748b');
              return (
                <button
                  key={imp}
                  onClick={() => setImpactFilter(imp)}
                  style={{
                    padding: '4px 12px', borderRadius: 20, cursor: 'pointer', fontSize: 11, fontWeight: 600,
                    border: `1px solid ${active ? color : '#334155'}`,
                    background: active ? `${color}22` : 'transparent',
                    color: active ? color : '#64748b',
                    transition: 'all 0.15s',
                  }}
                >
                  {imp === 'all' ? 'All Impact' : IMPORTANCE_LABEL[imp]}
                </button>
              );
            })}
          </div>

          {loading ? (
            <PanelSkeleton rows={5} />
          ) : fetchErr ? (
            <div style={s.errorBox}>{fetchErr}</div>
          ) : events.length === 0 ? (
            <EmptyState
              icon="📅"
              title="No events found"
              description="No economic events match the current filter. Try changing the impact level or date range."
              compact
            />
          ) : (
            Object.entries(grouped)
              .map(([date, dayEvents]) => {
                const filtered = dayEvents.filter((ev) =>
                  impactFilter === 'all' || ev.importance === impactFilter,
                );
                if (filtered.length === 0) return null;
                return (
                  <div key={date} style={s.dayGroup}>
                    <div style={s.dayHeader}>{date}</div>
                    {filtered.map((ev, i) => {
                      const key = `${ev.title}-${ev.scheduled_time}`;
                      return (
                        <EventRow
                          key={i}
                          event={ev}
                          subscribed={subscribed.has(key)}
                          onSubscribe={() => {
                            setSubscribed((prev) => {
                              const next = new Set(prev);
                              if (next.has(key)) {
                                next.delete(key);
                                toast.info(`Unsubscribed from ${ev.title}`);
                              } else {
                                next.add(key);
                                toast.success(`Subscribed to ${ev.title}`);
                              }
                              return next;
                            });
                          }}
                        />
                      );
                    })}
                  </div>
                );
              })
              .filter(Boolean)
          )}
        </>
      )}

      {/* ── Macro data layer tab ───────────────────────────────────────────── */}
      {tab === 'macro' && (
        <div style={{ maxWidth: 700 }}>
          <MacroCalendar />
        </div>
      )}

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/geopolitical" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🌍 Geopolitical</Link>
        <Link to="/correlation" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🔗 Correlation</Link>
        <Link to="/signals" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📡 Signal Feed</Link>
        <Link to="/trade" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>⚡ Trade</Link>
        <Link to="/alerts" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🔔 Price Alerts</Link>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: 24, maxWidth: 960, margin: '0 auto' },
  header:        { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 16 },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:      { fontSize: 14, color: '#64748b', margin: 0 },
  autoPauseCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 16px', minWidth: 260 },
  toggleBtn:     { border: 'none', borderRadius: 6, cursor: 'pointer', padding: '6px 14px', fontWeight: 700, fontSize: 13 },
  tabs:          { display: 'flex', gap: 8, marginBottom: 20 },
  tab:           { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', padding: '8px 16px', fontSize: 13 },
  tabActive:     { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
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
  errorBox:      { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '10px 14px', color: '#f87171', fontSize: 14, marginBottom: 16 },
};

export default EconomicCalendar;
