/**
 * Walk-Forward Validation Results
 *
 * Displays fold-by-fold performance from walk-forward backtesting:
 * - Equity curve per fold (overlaid)
 * - Per-fold metrics table (dates, accuracy, Sharpe, max drawdown)
 * - Stability score across folds
 * - Monte Carlo simulation results (if available)
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChart, LineSeries, type IChartApi, type UTCTimestamp } from 'lightweight-charts';
import { api } from '../hooks/useApi';

// ─── Types ────────────────────────────────────────────────────────────────────

interface FoldResult {
  fold: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  accuracy: number;
  sharpe: number;
  max_drawdown: number;
  total_return: number;
  total_trades: number;
  win_rate: number;
  equity_curve: { time: string; value: number }[];
}

interface WalkForwardData {
  run_id: string;
  strategy: string;
  symbol: string;
  folds: FoldResult[];
  stability_score: number;
  avg_sharpe: number;
  avg_accuracy: number;
  avg_drawdown: number;
  monte_carlo?: MonteCarloResult;
}

interface MonteCarloResult {
  median_equity: number;
  p5_equity: number;
  p95_equity: number;
  probability_of_ruin: number;
  simulations: number;
}

// ─── Fold colours ─────────────────────────────────────────────────────────────

const FOLD_COLORS = [
  '#60a5fa', '#4ade80', '#f59e0b', '#f87171', '#a78bfa',
  '#34d399', '#fb923c', '#e879f9', '#38bdf8', '#84cc16',
];

// ─── Equity chart ─────────────────────────────────────────────────────────────

const EquityChart: React.FC<{ folds: FoldResult[]; visibleFolds: Set<number> }> = ({
  folds, visibleFolds,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid:   { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width:  containerRef.current.clientWidth,
      height: 300,
      timeScale: { borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });
    chartRef.current = chart;

    folds.forEach((fold) => {
      if (!visibleFolds.has(fold.fold)) return;
      const series = chart.addSeries(LineSeries, {
        color: FOLD_COLORS[(fold.fold - 1) % FOLD_COLORS.length],
        lineWidth: 2,
        title: `Fold ${fold.fold}`,
      });
      series.setData(fold.equity_curve.map(p => ({ time: (p.time as unknown) as UTCTimestamp, value: p.value })));
    });

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    // Disconnect observer before removing chart so a chart.remove() error
    // cannot prevent the observer from being cleaned up (memory leak).
    return () => { ro.disconnect(); chart.remove(); };
  }, [folds, visibleFolds]);

  return <div ref={containerRef} style={{ width: '100%', height: 300 }} />;
};

// ─── Stability badge ──────────────────────────────────────────────────────────

const StabilityBadge: React.FC<{ score: number }> = ({ score }) => {
  const color =
    score >= 75 ? '#4ade80' :
    score >= 50 ? '#facc15' :
    '#f87171';
  const label =
    score >= 75 ? 'Stable' :
    score >= 50 ? 'Moderate' :
    'Unstable';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        width: 80, height: 80, borderRadius: '50%',
        border: `4px solid ${color}`,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}>
        <span style={{ fontSize: 20, fontWeight: 800, color }}>{score.toFixed(0)}</span>
        <span style={{ fontSize: 10, color: '#64748b' }}>/ 100</span>
      </div>
      <div>
        <div style={{ fontSize: 16, fontWeight: 700, color }}>{label}</div>
        <div style={{ fontSize: 12, color: '#64748b', maxWidth: 180 }}>
          Consistency of returns across all folds
        </div>
      </div>
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

const WalkForward: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData]            = useState<WalkForwardData | null>(null);
  const [loading, setLoading]      = useState(true);
  const [apiError, setApiError]    = useState<string | null>(null);
  const [visibleFolds, setVisible] = useState<Set<number>>(new Set());
  const [runId, setRunId]          = useState('');
  const [inputId, setInputId]      = useState('');

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async (id?: string) => {
    setLoading(true);
    setApiError(null);
    try {
      const endpoint = id
        ? `/backtesting/walk-forward/${id}`
        : '/backtesting/walk-forward/latest';
      const res = await api.get(endpoint);
      if (!mountedRef.current) return;
      setData(res.data);
      setVisible(new Set(res.data.folds.map((f: FoldResult) => f.fold)));
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setApiError('No walk-forward results yet. Run a backtest first via the Backtesting page.');
      } else {
        setApiError('Failed to load walk-forward results. Check your connection.');
      }
      setData(null);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleFold = (fold: number) => {
    setVisible((prev) => {
      const next = new Set(prev);
      next.has(fold) ? next.delete(fold) : next.add(fold);
      return next;
    });
  };

  if (loading) return <div style={s.loading}>Loading walk-forward results…</div>;

  if (apiError || !data) {
    return (
      <div style={s.page}>
        <h1 style={s.title}>Walk-Forward Analysis</h1>
        <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '24px', color: '#94a3b8', textAlign: 'center' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
          <div style={{ fontSize: 16, color: '#e2e8f0', marginBottom: 8 }}>
            {apiError ?? 'No walk-forward data available.'}
          </div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            Go to the Backtesting page and run a walk-forward analysis to see results here.
          </div>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginTop: 16 }}>
            <button onClick={() => load()} style={{ background: '#3b82f6', border: 'none', color: '#fff', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontSize: 14 }}>
              ↻ Retry
            </button>
            <button onClick={() => navigate('/backtest')} style={{ background: 'transparent', border: '1px solid #334155', color: '#94a3b8', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontSize: 14 }}>
              📊 Go to Backtesting
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (!data)   return <div style={s.loading}>No walk-forward data available.</div>;

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Walk-Forward Validation</h1>
          <p style={s.subtitle}>
            {data.strategy ?? '—'} · {data.symbol ?? '—'} · {(data.folds ?? []).length} folds
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={() => navigate('/ai-strategy')}
            style={{
              padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
              background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.3)',
              color: '#a78bfa', fontSize: 12, fontWeight: 700, fontFamily: 'inherit',
            }}
          >
            🤖 Generate Strategy
          </button>
          <div style={s.searchRow}>
            <input
              style={s.searchInput}
              placeholder="Run ID…"
              value={inputId}
              onChange={(e) => setInputId(e.target.value)}
            />
            <button style={s.btn} onClick={() => load(inputId || undefined)}>Load</button>
          </div>
        </div>
      </div>

      {/* Summary metrics */}
      <div style={s.metricsRow}>
        <MetricCard label="Avg Sharpe"    value={(data.avg_sharpe   ?? 0).toFixed(2)}   color="#60a5fa" />
        <MetricCard label="Avg Accuracy"  value={`${(data.avg_accuracy ?? 0).toFixed(1)}%`} color="#4ade80" />
        <MetricCard label="Avg Drawdown"  value={`${(data.avg_drawdown ?? 0).toFixed(1)}%`} color="#f87171" />
        <div style={s.metricCard}>
          <div style={s.metricLabel}>Stability Score</div>
          <StabilityBadge score={data.stability_score} />
        </div>
      </div>

      {/* Equity chart */}
      <div style={s.card}>
        <div style={s.cardHeader}>
          <div style={s.cardTitle}>Fold Equity Curves</div>
          <div style={s.foldToggles}>
            {data.folds.map((f) => (
              <button
                key={f.fold}
                style={{
                  ...s.foldBtn,
                  background: visibleFolds.has(f.fold)
                    ? FOLD_COLORS[(f.fold - 1) % FOLD_COLORS.length]
                    : '#1e293b',
                  color: visibleFolds.has(f.fold) ? '#0f172a' : '#64748b',
                }}
                onClick={() => toggleFold(f.fold)}
              >
                Fold {f.fold}
              </button>
            ))}
          </div>
        </div>
        <EquityChart folds={data.folds} visibleFolds={visibleFolds} />
      </div>

      {/* Fold table */}
      <div style={s.card}>
        <div style={s.cardTitle}>Fold-by-Fold Performance</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={s.table}>
            <thead>
              <tr>
                {['Fold', 'Test Period', 'Accuracy', 'Sharpe', 'Max DD', 'Return', 'Trades', 'Win Rate'].map((h) => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.folds.map((f) => (
                <tr key={f.fold} style={s.tr}>
                  <td style={s.td}>
                    <span style={{
                      display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                      background: FOLD_COLORS[(f.fold - 1) % FOLD_COLORS.length],
                      marginRight: 6,
                    }} />
                    {f.fold}
                  </td>
                  <td style={s.td}>{f.test_start} → {f.test_end}</td>
                  <td style={{ ...s.td, color: f.accuracy >= 55 ? '#4ade80' : '#f87171' }}>
                    {f.accuracy.toFixed(1)}%
                  </td>
                  <td style={{ ...s.td, color: f.sharpe >= 1 ? '#4ade80' : '#facc15' }}>
                    {f.sharpe.toFixed(2)}
                  </td>
                  <td style={{ ...s.td, color: '#f87171' }}>{f.max_drawdown.toFixed(1)}%</td>
                  <td style={{ ...s.td, color: f.total_return >= 0 ? '#4ade80' : '#f87171' }}>
                    {f.total_return >= 0 ? '+' : ''}{f.total_return.toFixed(1)}%
                  </td>
                  <td style={s.td}>{f.total_trades}</td>
                  <td style={s.td}>{f.win_rate.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Monte Carlo */}
      {data.monte_carlo && (
        <div style={s.card}>
          <div style={s.cardTitle}>Monte Carlo Simulation ({data.monte_carlo.simulations.toLocaleString()} runs)</div>
          <div style={s.mcGrid}>
            <MCCard label="Median Equity"       value={`$${data.monte_carlo.median_equity.toLocaleString()}`} color="#60a5fa" />
            <MCCard label="5th Percentile (Worst)" value={`$${data.monte_carlo.p5_equity.toLocaleString()}`} color="#f87171" />
            <MCCard label="95th Percentile (Best)" value={`$${data.monte_carlo.p95_equity.toLocaleString()}`} color="#4ade80" />
            <MCCard label="Probability of Ruin" value={`${data.monte_carlo.probability_of_ruin.toFixed(1)}%`}
              color={data.monte_carlo.probability_of_ruin < 5 ? '#4ade80' : '#f87171'} />
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Small helpers ────────────────────────────────────────────────────────────

const MetricCard: React.FC<{ label: string; value: string; color: string }> = ({ label, value, color }) => (
  <div style={s.metricCard}>
    <div style={s.metricLabel}>{label}</div>
    <div style={{ ...s.metricValue, color }}>{value}</div>
  </div>
);

const MCCard: React.FC<{ label: string; value: string; color: string }> = ({ label, value, color }) => (
  <div style={s.mcCard}>
    <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
  </div>
);

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#f8fafc',
    fontFamily: "'Inter', system-ui, sans-serif",
    padding: '24px',
  },
  loading: { color: '#94a3b8', padding: 48, textAlign: 'center' },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: 24, flexWrap: 'wrap', gap: 16,
  },
  title:    { fontSize: 28, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 4 },
  searchRow: { display: 'flex', gap: 8 },
  searchInput: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
    color: '#f8fafc', padding: '8px 12px', fontSize: 14, outline: 'none',
  },
  btn: {
    background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '8px 16px', fontSize: 14, cursor: 'pointer',
  },
  metricsRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 16, marginBottom: 24,
  },
  metricCard: {
    background: '#1e293b', borderRadius: 12, padding: 20,
    border: '1px solid #334155',
  },
  metricLabel: { fontSize: 12, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' },
  metricValue: { fontSize: 28, fontWeight: 800 },
  card: {
    background: '#1e293b', borderRadius: 12, padding: 24,
    border: '1px solid #334155', marginBottom: 24,
  },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 },
  cardTitle: {
    fontSize: 14, fontWeight: 600, color: '#94a3b8',
    textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16,
  },
  foldToggles: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  foldBtn: {
    border: 'none', borderRadius: 6, padding: '4px 10px',
    fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
  },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: {
    textAlign: 'left', padding: '10px 12px',
    color: '#64748b', fontWeight: 600, borderBottom: '1px solid #334155',
    whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid #1e293b' },
  td: { padding: '10px 12px', color: '#cbd5e1', whiteSpace: 'nowrap' },
  mcGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
    gap: 16,
  },
  mcCard: {
    background: '#0f172a', borderRadius: 8, padding: 16,
    border: '1px solid #334155',
  },
};

export default WalkForward;
