/**
 * Replay page — historical market replay with step-by-step bar-by-bar playback.
 *
 * Wires to:
 *   GET  /api/replay/sessions           — list replay sessions
 *   POST /api/replay/sessions           — create session
 *   POST /api/replay/sessions/{id}/step — advance one bar
 *   POST /api/replay/sessions/{id}/run  — run N bars
 *   GET  /api/replay/sessions/{id}      — session state
 *   DELETE /api/replay/sessions/{id}    — delete session
 *
 * Requires: enterprise plan
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { replayApi } from '../hooks/useApi';

// Playback speed options (ms between auto-step ticks)
const SPEED_OPTIONS: { label: string; ms: number }[] = [
  { label: '0.25×', ms: 2000 },
  { label: '0.5×',  ms: 1000 },
  { label: '1×',    ms: 500  },
  { label: '2×',    ms: 250  },
  { label: '4×',    ms: 125  },
  { label: '8×',    ms: 60   },
];

// ── Types ─────────────────────────────────────────────────────────────────────

interface ReplaySession {
  session_id: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  current_bar: number;
  total_bars: number;
  status: 'created' | 'running' | 'paused' | 'completed';
  current_price: number;
  equity: number;
  pnl: number;
  trades: ReplayTrade[];
  bars: OHLCBar[];
  created_at: string;
}

interface OHLCBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface ReplayTrade {
  trade_id: string;
  side: 'buy' | 'sell';
  entry_price: number;
  exit_price: number | null;
  size: number;
  pnl: number | null;
  bar_opened: number;
  bar_closed: number | null;
}

// replayApi is imported from hooks/useApi

// ── Mini OHLC chart ───────────────────────────────────────────────────────────

function MiniChart({ bars, currentBar }: { bars: OHLCBar[]; currentBar: number }) {
  if (!bars.length) return (
    <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#475569', fontSize: 13 }}>No bars loaded</div>
  );

  const visible = bars.slice(Math.max(0, currentBar - 60), currentBar + 1);
  if (visible.length < 2) return null;

  const W = 700; const H = 180;
  const highs  = visible.map(b => b.high);
  const lows   = visible.map(b => b.low);
  const maxH   = Math.max(...highs);
  const minL   = Math.min(...lows);
  const range  = maxH - minL || 1;
  const barW   = W / visible.length;

  const scaleY = (v: number) => H - ((v - minL) / range) * H;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 200, background: '#0a0f1a', borderRadius: 8 }}>
      {visible.map((b, i) => {
        const x    = i * barW + barW * 0.1;
        const bw   = barW * 0.8;
        const bull = b.close >= b.open;
        const col  = bull ? '#22c55e' : '#ef4444';
        const oY   = scaleY(b.open);
        const cY   = scaleY(b.close);
        const hY   = scaleY(b.high);
        const lY   = scaleY(b.low);
        const bodyTop = Math.min(oY, cY);
        const bodyH   = Math.max(Math.abs(cY - oY), 1);
        return (
          <g key={i}>
            <line x1={x + bw / 2} y1={hY} x2={x + bw / 2} y2={lY} stroke={col} strokeWidth={1} />
            <rect x={x} y={bodyTop} width={bw} height={bodyH} fill={col} />
          </g>
        );
      })}
      {/* Current bar marker */}
      <line x1={W - barW / 2} y1={0} x2={W - barW / 2} y2={H}
        stroke="#f59e0b" strokeWidth={1} strokeDasharray="3,3" />
    </svg>
  );
}

// ── Session card ──────────────────────────────────────────────────────────────

function SessionCard({ session, selected, onClick }: {
  session: ReplaySession; selected: boolean; onClick: () => void;
}) {
  const pct = session.total_bars > 0 ? (session.current_bar / session.total_bars) * 100 : 0;
  return (
    <div onClick={onClick} style={{
      background: selected ? '#1a2744' : '#1e293b',
      border: `1px solid ${selected ? '#3b82f6' : '#334155'}`,
      borderRadius: 10, padding: '14px 16px', cursor: 'pointer',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>
          {session.symbol} · {session.timeframe}
        </span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          {session.current_bar}/{session.total_bars} bars
        </span>
      </div>
      <div style={{ height: 4, background: '#334155', borderRadius: 2, marginBottom: 8 }}>
        <div style={{ height: '100%', width: `${pct}%`, background: '#3b82f6', borderRadius: 2 }} />
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
        <span style={{ color: session.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
          P&L: {session.pnl >= 0 ? '+' : ''}{session.pnl.toFixed(2)}
        </span>
        <span style={{ color: '#64748b' }}>
          {session.start_date.slice(0, 10)} → {session.end_date.slice(0, 10)}
        </span>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const SYMBOLS    = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'US30', 'NAS100'];
const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];

const ReplayPage: React.FC = () => {
  const qc = useQueryClient();
  const [selected, setSelected]   = useState<ReplaySession | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [symbol, setSymbol]         = useState('XAUUSD');
  const [timeframe, setTimeframe]   = useState('H1');
  const [startDate, setStartDate]   = useState('2024-01-01');
  const [endDate, setEndDate]       = useState('2024-06-30');
  const [runBars, setRunBars]       = useState(10);
  const autoRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [autoPlay, setAutoPlay]     = useState(false);
  const [speedIdx, setSpeedIdx]     = useState(2); // default 1×
  const selectedRef = useRef<ReplaySession | null>(null);
  selectedRef.current = selected;

  const { data, isLoading } = useQuery({
    queryKey: ['replay-sessions'],
    queryFn: () => replayApi.listSessions().then(r => r.data as { sessions: ReplaySession[] }),
  });

  const createMut = useMutation({
    mutationFn: () => replayApi.createSession({ symbol, timeframe, start_date: startDate, end_date: endDate }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['replay-sessions'] });
      setSelected(res.data as ReplaySession);
      setShowCreate(false);
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err instanceof Error ? err.message : 'Failed to create session');
      console.error('[ReplayPage] createSession error:', msg);
    },
  });

  const stepMut = useMutation({
    mutationFn: (id: string) => replayApi.stepSession(id),
    onSuccess: (res) => setSelected(res.data as ReplaySession),
    onError: (err: unknown) => {
      console.error('[ReplayPage] stepSession error:', err);
    },
  });

  const runMut = useMutation({
    mutationFn: ({ id, bars }: { id: string; bars: number }) => replayApi.runSession(id, bars),
    onSuccess: (res) => setSelected(res.data as ReplaySession),
    onError: (err: unknown) => {
      console.error('[ReplayPage] runSession error:', err);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => replayApi.deleteSession(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['replay-sessions'] }); setSelected(null); },
    onError: (err: unknown) => {
      console.error('[ReplayPage] deleteSession error:', err);
    },
  });

  const stopAutoPlay = useCallback(() => {
    if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; }
    setAutoPlay(false);
  }, []);

  const startAutoPlay = useCallback((ms: number) => {
    if (autoRef.current) clearInterval(autoRef.current);
    setAutoPlay(true);
    autoRef.current = setInterval(() => {
      const s = selectedRef.current;
      if (!s || s.status === 'completed') { stopAutoPlay(); return; }
      stepMut.mutate(s.session_id);
    }, ms);
  }, [stepMut, stopAutoPlay]);

  const toggleAutoPlay = useCallback(() => {
    if (!selected) return;
    if (autoPlay) { stopAutoPlay(); }
    else { startAutoPlay(SPEED_OPTIONS[speedIdx].ms); }
  }, [autoPlay, selected, speedIdx, startAutoPlay, stopAutoPlay]);

  // When speed changes mid-play, restart interval at new speed
  const handleSpeedChange = useCallback((idx: number) => {
    setSpeedIdx(idx);
    if (autoPlay) { startAutoPlay(SPEED_OPTIONS[idx].ms); }
  }, [autoPlay, startAutoPlay]);

  // Keyboard navigation: Space=play/pause, →=step, ←=nothing (no rewind), Esc=close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.key === ' ' || e.key === 'Space') {
        e.preventDefault();
        toggleAutoPlay();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        const s = selectedRef.current;
        if (s && s.status !== 'completed') stepMut.mutate(s.session_id);
      } else if (e.key === 'Escape') {
        stopAutoPlay();
        setSelected(null);
      } else if (e.key === '+' || e.key === '=') {
        setSpeedIdx(i => { const n = Math.min(i + 1, SPEED_OPTIONS.length - 1); if (autoPlay) startAutoPlay(SPEED_OPTIONS[n].ms); return n; });
      } else if (e.key === '-') {
        setSpeedIdx(i => { const n = Math.max(i - 1, 0); if (autoPlay) startAutoPlay(SPEED_OPTIONS[n].ms); return n; });
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [toggleAutoPlay, stepMut, stopAutoPlay, autoPlay, startAutoPlay]);

  const sessions = data?.sessions ?? [];

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1300, margin: '0 auto' }}>
      <PageHeader
        title="Market Replay"
        subtitle="Bar-by-bar historical replay with live strategy testing — enterprise tier"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'Market Replay' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link to="/ai-chart"
              style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', color: '#60a5fa', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              📈 AI Charts
            </Link>
            <Link to="/walk-forward"
              style={{ padding: '7px 14px', background: 'rgba(167,139,250,0.12)', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              📊 Walk-Forward
            </Link>
            <Link to="/ai-strategy"
              style={{ padding: '7px 14px', background: 'rgba(52,211,153,0.12)', color: '#34d399', border: '1px solid rgba(52,211,153,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              🤖 AI Strategy
            </Link>
            <button onClick={() => setShowCreate((s: boolean) => !s)}
              style={{ padding: '7px 16px', background: '#3b82f6', color: '#fff', border: 'none',
                borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
              + New Session
            </button>
          </div>
        }
      />

      {/* Create form */}
      {showCreate && (
        <div style={{ background: '#1e293b', border: '1px solid #3b82f644', borderRadius: 12,
          padding: 20, marginBottom: 20 }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>New Replay Session</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              Symbol
              <select value={symbol} onChange={e => setSymbol(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a',
                  border: '1px solid #334155', borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
                {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              Timeframe
              <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a',
                  border: '1px solid #334155', borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              Start Date
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a',
                  border: '1px solid #334155', borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }} />
            </label>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              End Date
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a',
                  border: '1px solid #334155', borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={() => createMut.mutate()} disabled={createMut.isPending}
              style={{ padding: '8px 16px', background: '#3b82f6', color: '#fff', border: 'none',
                borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                opacity: createMut.isPending ? 0.5 : 1 }}>
              {createMut.isPending ? 'Creating…' : 'Create Session'}
            </button>
            <button onClick={() => setShowCreate(false)}
              style={{ padding: '8px 14px', background: '#334155', color: '#94a3b8', border: 'none',
                borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>Cancel</button>
            {createMut.isError && (
              <span style={{ fontSize: 12, color: '#f87171' }}>
                ⚠ {(createMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                  ?? (createMut.error instanceof Error ? createMut.error.message : 'Failed to create session')}
              </span>
            )}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '280px 1fr' : '1fr', gap: 20 }}>
        {/* Session list */}
        <div>
          {isLoading && <div style={{ color: '#64748b', fontSize: 13, padding: 20, textAlign: 'center' }}>Loading…</div>}
          {!isLoading && sessions.length === 0 && (
            <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
              padding: 40, textAlign: 'center' }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>📈</div>
              <div style={{ fontSize: 14, color: '#94a3b8', marginBottom: 8 }}>No replay sessions</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>Create a session to replay historical market data</div>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {sessions.map(s => (
              <SessionCard key={s.session_id} session={s}
                selected={selected?.session_id === s.session_id}
                onClick={() => setSelected(s)} />
            ))}
          </div>
        </div>

        {/* Replay player */}
        {selected && (
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24 }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div>
                <h2 style={{ margin: '0 0 2px', fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
                  {selected.symbol} · {selected.timeframe}
                </h2>
                <div style={{ fontSize: 12, color: '#64748b' }}>
                  Bar {selected.current_bar} / {selected.total_bars}
                  {' · '}
                  Price: <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{selected.current_price.toFixed(5)}</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {/* P&L */}
                <div style={{ fontSize: 14, fontWeight: 700,
                  color: selected.pnl >= 0 ? '#22c55e' : '#ef4444' }}>
                  {selected.pnl >= 0 ? '+' : ''}{selected.pnl.toFixed(2)}
                </div>
                <button onClick={() => deleteMut.mutate(selected.session_id)}
                  style={{ padding: '6px 10px', background: '#ef444422', color: '#ef4444',
                    border: '1px solid #ef444444', borderRadius: 6, fontSize: 11, cursor: 'pointer' }}>
                  Delete
                </button>
                <button onClick={() => setSelected(null)}
                  style={{ padding: '6px 10px', background: '#334155', color: '#94a3b8',
                    border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>✕</button>
              </div>
            </div>

            {/* Progress bar */}
            <div style={{ height: 4, background: '#334155', borderRadius: 2, marginBottom: 16 }}>
              <div style={{
                height: '100%', borderRadius: 2, background: '#3b82f6',
                width: `${selected.total_bars > 0 ? (selected.current_bar / selected.total_bars) * 100 : 0}%`,
                transition: 'width 0.2s',
              }} />
            </div>

            {/* Chart */}
            <div style={{ marginBottom: 16 }}>
              <MiniChart bars={selected.bars ?? []} currentBar={selected.current_bar} />
            </div>

            {/* Controls */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
              <button onClick={() => stepMut.mutate(selected.session_id)}
                disabled={stepMut.isPending || selected.status === 'completed'}
                title="Step one bar (→)"
                style={{ padding: '8px 16px', background: '#3b82f6', color: '#fff', border: 'none',
                  borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  opacity: (stepMut.isPending || selected.status === 'completed') ? 0.5 : 1 }}>
                ⏭ Step
              </button>
              <button onClick={toggleAutoPlay}
                disabled={selected.status === 'completed'}
                title="Play/Pause (Space)"
                style={{ padding: '8px 16px',
                  background: autoPlay ? '#ef4444' : '#22c55e',
                  color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  opacity: selected.status === 'completed' ? 0.5 : 1 }}>
                {autoPlay ? '⏸ Pause' : '▶ Play'}
              </button>

              {/* Speed selector */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, padding: '2px 4px' }}>
                {SPEED_OPTIONS.map((opt, i) => (
                  <button key={opt.label} onClick={() => handleSpeedChange(i)}
                    style={{
                      padding: '4px 8px', borderRadius: 4, border: 'none', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      background: speedIdx === i ? '#3b82f6' : 'transparent',
                      color: speedIdx === i ? '#fff' : '#64748b',
                    }}>
                    {opt.label}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="number" value={runBars} onChange={e => setRunBars(Number(e.target.value))}
                  min={1} max={500} style={{ width: 60, background: '#0f172a', border: '1px solid #334155',
                    borderRadius: 6, padding: '7px 8px', color: '#e2e8f0', fontSize: 13 }} />
                <button onClick={() => runMut.mutate({ id: selected.session_id, bars: runBars })}
                  disabled={runMut.isPending || selected.status === 'completed'}
                  style={{ padding: '8px 14px', background: '#f59e0b', color: '#000', border: 'none',
                    borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    opacity: (runMut.isPending || selected.status === 'completed') ? 0.5 : 1 }}>
                  Run {runBars}
                </button>
              </div>
              {selected.status === 'completed' && (
                <span style={{ fontSize: 12, color: '#22c55e', fontWeight: 600 }}>✓ Completed</span>
              )}
            </div>
            {/* Keyboard hint */}
            <div style={{ fontSize: 10, color: '#334155', marginBottom: 16 }}>
              Keyboard: <kbd style={{ background: '#1e293b', padding: '1px 5px', borderRadius: 3, color: '#64748b' }}>Space</kbd> play/pause ·
              <kbd style={{ background: '#1e293b', padding: '1px 5px', borderRadius: 3, color: '#64748b', marginLeft: 4 }}>→</kbd> step ·
              <kbd style={{ background: '#1e293b', padding: '1px 5px', borderRadius: 3, color: '#64748b', marginLeft: 4 }}>+/-</kbd> speed ·
              <kbd style={{ background: '#1e293b', padding: '1px 5px', borderRadius: 3, color: '#64748b', marginLeft: 4 }}>Esc</kbd> close
            </div>

            {/* Trade log */}
            {(selected.trades ?? []).length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 8,
                  textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Trades ({selected.trades.length})
                </div>
                <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {selected.trades.map(t => (
                    <div key={t.trade_id} style={{
                      display: 'flex', gap: 12, alignItems: 'center',
                      background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '8px 12px',
                      fontSize: 12,
                    }}>
                      <span style={{ color: t.side === 'buy' ? '#22c55e' : '#ef4444', fontWeight: 600,
                        textTransform: 'uppercase', width: 30 }}>{t.side}</span>
                      <span style={{ color: '#94a3b8' }}>@ {t.entry_price.toFixed(5)}</span>
                      {t.exit_price && <span style={{ color: '#64748b' }}>→ {t.exit_price.toFixed(5)}</span>}
                      {t.pnl !== null && (
                        <span style={{ marginLeft: 'auto', fontWeight: 700,
                          color: t.pnl >= 0 ? '#22c55e' : '#ef4444' }}>
                          {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReplayPage;
