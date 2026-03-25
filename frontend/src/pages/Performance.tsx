/**
 * Live Performance page — public paper trading results.
 *
 * Wires to: GET /api/performance/public
 *           GET /api/performance/equity-curve
 */

import React, { useEffect, useState, useCallback } from 'react';

interface PublicPerformance {
  total_trades: number;
  win_rate: number | null;
  avg_return_pct: number | null;
  sharpe: number | null;
  max_drawdown_pct: number;
  start_date: string;
  note: string;
}

interface EquityPoint {
  timestamp: string;
  equity: number;
}

// ── Mini equity chart (SVG) ───────────────────────────────────────────────────

const EquitySparkline: React.FC<{ points: EquityPoint[] }> = ({ points }) => {
  if (points.length < 2) return null;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const W = 600, H = 120;
  const coords = values.map((v, i) => ({
    x: (i / (values.length - 1)) * W,
    y: H - ((v - min) / range) * H,
  }));
  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ');
  const fill = `${path} L${W},${H} L0,${H} Z`;
  const up = values[values.length - 1] >= values[0];
  const color = up ? '#22c55e' : '#ef4444';

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 120 }}>
      <defs>
        <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={fill} fill="url(#eq-grad)" />
      <path d={path} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
};

// ── Stat card ─────────────────────────────────────────────────────────────────

const StatCard: React.FC<{ label: string; value: string; sub?: string; color?: string }> = ({
  label, value, sub, color = '#f1f5f9',
}) => (
  <div style={s.statCard}>
    <div style={s.statLabel}>{label}</div>
    <div style={{ ...s.statValue, color }}>{value}</div>
    {sub && <div style={s.statSub}>{sub}</div>}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const Performance: React.FC = () => {
  const [data, setData]         = useState<PublicPerformance | null>(null);
  const [equity, setEquity]     = useState<EquityPoint[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [perfRes, eqRes] = await Promise.all([
        fetch('/api/performance/public'),
        fetch('/api/performance/equity-curve'),
      ]);
      if (!perfRes.ok) throw new Error(`HTTP ${perfRes.status}`);
      setData(await perfRes.json());
      if (eqRes.ok) setEquity(await eqRes.json());
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Live Performance</h1>
          <p style={s.subtitle}>Real paper trading results — updated continuously</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastUpdated && <span style={{ fontSize: 12, color: '#475569' }}>Updated {lastUpdated}</span>}
          <button onClick={load} disabled={loading} style={s.refreshBtn}>
            {loading ? '⟳' : '↻'} Refresh
          </button>
        </div>
      </div>

      {error && (
        <div style={s.errorBox}>Failed to load performance data: {error}</div>
      )}

      {data && (
        <>
          {/* Stats grid */}
          <div style={s.statsGrid}>
            <StatCard
              label="Total Trades"
              value={data.total_trades.toString()}
              sub="Paper trading"
              color="#60a5fa"
            />
            <StatCard
              label="Win Rate"
              value={data.win_rate !== null ? `${data.win_rate}%` : '—'}
              sub={data.win_rate === null ? 'Need 50+ trades' : 'Winning trades'}
              color={data.win_rate !== null && data.win_rate >= 50 ? '#4ade80' : '#f87171'}
            />
            <StatCard
              label="Avg Return / Trade"
              value={data.avg_return_pct !== null
                ? `${data.avg_return_pct > 0 ? '+' : ''}${data.avg_return_pct}%`
                : '—'}
              sub="Per completed trade"
              color={data.avg_return_pct !== null && data.avg_return_pct >= 0 ? '#4ade80' : '#f87171'}
            />
            <StatCard
              label="Sharpe Ratio"
              value={data.sharpe !== null ? data.sharpe.toString() : '—'}
              sub={data.sharpe === null ? 'Need 50+ data points' : 'Annualised'}
              color="#a78bfa"
            />
            <StatCard
              label="Max Drawdown"
              value={`${data.max_drawdown_pct}%`}
              sub="Peak-to-trough"
              color="#f87171"
            />
          </div>

          {/* Transparency note */}
          <div style={s.noteBox}>
            <span style={{ color: '#fbbf24', marginRight: 8 }}>⏱</span>
            <span>
              <strong style={{ color: '#f1f5f9' }}>Transparency note: </strong>
              {data.note}
              {data.start_date !== '—' && ` Paper trading started: ${data.start_date}.`}
            </span>
          </div>

          {/* Equity chart */}
          {equity.length > 1 && (
            <div style={s.chartCard}>
              <h3 style={s.cardTitle}>Equity Curve</h3>
              <EquitySparkline points={equity} />
              <div style={s.chartFooter}>
                <span style={{ color: '#475569', fontSize: 12 }}>
                  {equity[0]?.timestamp ? new Date(equity[0].timestamp).toLocaleDateString() : ''}
                </span>
                <span style={{ color: '#475569', fontSize: 12 }}>
                  {equity[equity.length - 1]?.timestamp
                    ? new Date(equity[equity.length - 1].timestamp).toLocaleDateString()
                    : ''}
                </span>
              </div>
            </div>
          )}
        </>
      )}

      {loading && !data && (
        <div style={s.loading}>Loading performance data…</div>
      )}

      {/* Public API link */}
      <div style={s.apiNote}>
        Raw data available at{' '}
        <a href="/api/performance/public" target="_blank" rel="noopener noreferrer" style={s.apiLink}>
          /api/performance/public
        </a>{' '}
        — no authentication required.
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:       { padding: 24, maxWidth: 1000, margin: '0 auto' },
  header:     { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 },
  title:      { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:   { fontSize: 14, color: '#64748b', margin: 0 },
  refreshBtn: { background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '6px 12px' },
  errorBox:   { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, color: '#f87171', fontSize: 13, padding: '12px 16px', marginBottom: 16 },
  statsGrid:  { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 },
  statCard:   { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  statLabel:  { fontSize: 12, color: '#64748b', marginBottom: 6 },
  statValue:  { fontSize: 22, fontWeight: 700 },
  statSub:    { fontSize: 11, color: '#475569', marginTop: 4 },
  noteBox:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#94a3b8', marginBottom: 20 },
  chartCard:  { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 16, marginBottom: 20 },
  cardTitle:  { fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 12px' },
  chartFooter:{ display: 'flex', justifyContent: 'space-between', marginTop: 8 },
  loading:    { textAlign: 'center', color: '#475569', padding: 48 },
  apiNote:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#64748b' },
  apiLink:    { color: '#fbbf24', fontFamily: 'monospace' },
};

export default Performance;
