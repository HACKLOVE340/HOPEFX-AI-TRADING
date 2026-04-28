/**
 * Dashboard — real-time trading dashboard
 *
 * Data sources (in priority order):
 *   1. Live WebSocket feed → Zustand store
 *   2. REST API polling (30 s) for positions / signals / account (via AppShell useBootstrapData)
 *
 * Sections:
 *   - Live price ticker (5 symbols)
 *   - Account metrics bar
 *   - Equity curve (lightweight-charts)
 *   - Open positions table
 *   - Active signals panel
 *   - ML model accuracy card
 */

import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChart, AreaSeries, type IChartApi, type ISeriesApi, ColorType } from 'lightweight-charts';
import {
  useStore,
  selectAccount,
  selectPositions,
  selectSignals,
  selectWsStatus,
  selectEquityCurve,
  selectRiskSnapshot,
  selectMicrostructure,
  selectSentiment,
} from '../store';
import { mlApi, tradingApi } from '../hooks/useApi';
import type { EquityPoint } from '../types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtUSD = (n: number) =>
  (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

const fmtPct = (n: number) => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

// ─── Stat card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
  highlight?: boolean;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, sub, positive, highlight }) => (
  <div style={{ ...s.statCard, ...(highlight ? s.statCardHighlight : {}) }}>
    <div style={s.statLabel}>{label}</div>
    <div
      style={{
        ...s.statValue,
        color:
          positive === true  ? '#4ade80' :
          positive === false ? '#f87171' :
          '#f8fafc',
      }}
    >
      {value}
    </div>
    {sub && <div style={s.statSub}>{sub}</div>}
  </div>
);

// ─── Price ticker ─────────────────────────────────────────────────────────────
// Symbol keys must match the WebSocket price_tick format (slash separator).
const WATCHED_SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];

const PriceTicker: React.FC = () => {
  const prices = useStore((s) => s.prices);

  return (
    <div style={s.ticker}>
      {WATCHED_SYMBOLS.map((sym) => {
        const tick  = prices[sym];
        const up    = tick ? tick.change_pct >= 0 : null;
        const decimals =
          sym.includes('JPY') ? 3 :
          sym.includes('BTC') ? 0 :
          sym.includes('XAU') ? 2 : 5;
        return (
          <div key={sym} style={s.tickerItem}>
            <span style={s.tickerSymbol}>{sym}</span>
            <span style={s.tickerPrice}>
              {tick ? fmt(tick.mid, decimals) : '—'}
            </span>
            <span style={{ ...s.tickerChange, color: up === true ? '#4ade80' : up === false ? '#f87171' : '#64748b' }}>
              {tick ? fmtPct(tick.change_pct) : '—'}
            </span>
          </div>
        );
      })}
    </div>
  );
};

// ─── Equity chart (lightweight-charts) ───────────────────────────────────────

// lightweight-charts v5 requires { time: UTCTimestamp | string, value: number }
interface ChartPoint { time: string; value: number }

function toChartPoints(curve: EquityPoint[]): ChartPoint[] {
  return curve
    .filter((pt) => pt.timestamp && isFinite(pt.equity))
    .map((pt) => ({
      // lightweight-charts accepts ISO date strings (YYYY-MM-DD) or unix seconds
      time:  pt.timestamp.slice(0, 10),
      value: pt.equity,
    }))
    // Deduplicate by time key (keep last) — duplicate timestamps crash the chart
    .reduce<ChartPoint[]>((acc, pt) => {
      if (acc.length > 0 && acc[acc.length - 1]!.time === pt.time) {
        acc[acc.length - 1] = pt;
      } else {
        acc.push(pt);
      }
      return acc;
    }, []);
}

const EquityChart: React.FC<{ data: EquityPoint[] }> = ({ data }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const seriesRef    = useRef<ISeriesApi<'Area'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    chartRef.current = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#64748b',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true },
      width:  containerRef.current.clientWidth,
      height: 240,
    });

    seriesRef.current = chartRef.current.addSeries(AreaSeries, {
      lineColor:   '#3b82f6',
      topColor:    'rgba(59,130,246,0.25)',
      bottomColor: 'rgba(59,130,246,0.0)',
      lineWidth:   2,
    });

    const points = toChartPoints(data);
    if (points.length > 0) {
      seriesRef.current.setData(points);
      chartRef.current.timeScale().fitContent();
    }

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chartRef.current?.remove();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!seriesRef.current) return;
    const points = toChartPoints(data);
    if (points.length > 0) {
      seriesRef.current.setData(points);
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  return <div ref={containerRef} style={{ width: '100%', height: 240 }} />;
};

// ─── Positions table ──────────────────────────────────────────────────────────

const PositionsTable: React.FC = () => {
  const positions = useStore(selectPositions);

  if (positions.length === 0) {
    return <p style={s.empty}>No open positions.</p>;
  }

  return (
    <table style={s.table}>
      <thead>
        <tr>
          {['Symbol', 'Side', 'Size', 'Entry', 'Current', 'Unreal. P&L', 'Opened'].map((h) => (
            <th key={h} style={s.th}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.id} style={s.tr}>
            <td style={{ ...s.td, fontWeight: 600, color: '#e2e8f0' }}>{p.symbol}</td>
            <td style={{ ...s.td, color: p.side === 'long' ? '#4ade80' : '#f87171', fontWeight: 600, textTransform: 'uppercase' }}>
              {p.side}
            </td>
            <td style={s.td}>{fmt(p.size, 2)}</td>
            <td style={s.td}>{fmt(p.entry_price, 4)}</td>
            <td style={s.td}>{fmt(p.current_price, 4)}</td>
            <td style={{ ...s.td, color: p.unrealized_pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>
              {fmtUSD(p.unrealized_pnl)}
            </td>
            <td style={{ ...s.td, color: '#64748b', fontSize: 12 }}>
              {new Date(p.opened_at).toLocaleString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

// ─── Signals panel ────────────────────────────────────────────────────────────

const SignalsPanel: React.FC = () => {
  const signals = useStore(selectSignals);
  const active  = signals.filter((sig) => sig.status === 'active').slice(0, 6);

  if (active.length === 0) {
    return <p style={s.empty}>No active signals.</p>;
  }

  return (
    <div style={s.signalGrid}>
      {active.map((sig) => (
        <div key={sig.id} style={s.signalCard}>
          <div style={s.signalHeader}>
            <span style={s.signalSymbol}>{sig.symbol}</span>
            <span
              style={{
                ...s.signalBadge,
                background: sig.direction === 'long' ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
                color:      sig.direction === 'long' ? '#4ade80' : '#f87171',
              }}
            >
              {sig.direction.toUpperCase()}
            </span>
          </div>
          <div style={s.signalRow}>
            <span style={s.signalKey}>Confidence</span>
            <span style={{ ...s.signalVal, color: sig.confidence > 0.75 ? '#4ade80' : sig.confidence > 0.55 ? '#fbbf24' : '#f87171' }}>
              {(sig.confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div style={s.signalRow}>
            <span style={s.signalKey}>Entry</span>
            <span style={s.signalVal}>{fmt(sig.entry_price, 4)}</span>
          </div>
          <div style={s.signalRow}>
            <span style={s.signalKey}>SL / TP</span>
            <span style={{ ...s.signalVal, color: '#f87171' }}>{fmt(sig.stop_loss, 4)}</span>
            <span style={{ color: '#64748b', margin: '0 4px' }}>/</span>
            <span style={{ ...s.signalVal, color: '#4ade80' }}>{fmt(sig.take_profit, 4)}</span>
          </div>
          <div style={s.signalRow}>
            <span style={s.signalKey}>Model</span>
            <span style={{ ...s.signalVal, color: '#94a3b8' }}>{sig.model}</span>
          </div>
          <div style={{ background: '#1e293b', borderRadius: 4, height: 4, marginTop: 8 }}>
            <div style={{ width: `${sig.confidence * 100}%`, height: 4, borderRadius: 4, background: sig.confidence > 0.75 ? '#4ade80' : sig.confidence > 0.55 ? '#fbbf24' : '#f87171', transition: 'width 0.4s ease' }} />
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── ML accuracy card ─────────────────────────────────────────────────────────

interface AccuracyResponse {
  model_id:      string;
  accuracy:      number;
  precision:     number;
  recall:        number;
  f1:            number;
  sharpe:        number;
  win_rate:      number;
  total_signals: number;
  evaluated_at:  string;
  note?:         string;
  thresholds?:   Record<string, number>;
}

const MlAccuracyCard: React.FC = () => {
  const [data, setData]   = useState<AccuracyResponse | null>(null);
  const [mlErr, setMlErr] = useState<string | null>(null);

  useEffect(() => {
    mlApi.accuracy()
      .then((r) => {
        const raw = r.data as AccuracyResponse;
        setData(raw);
      })
      .catch((err: unknown) => {
        setData(null);
        setMlErr(err instanceof Error ? err.message : 'Failed to load model metrics.');
      });
  }, []);

  if (mlErr) {
    return <p style={{ color: '#f87171', fontSize: 13, padding: '16px 0' }}>{mlErr}</p>;
  }
  if (!data) {
    return <p style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>Loading model metrics…</p>;
  }
  if (data.accuracy === 0 && data.total_signals === 0) {
    return (
      <p style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>
        {data.note || 'No model metrics available yet.'}
      </p>
    );
  }

  const metrics = [
    { key: 'Accuracy',  val: (data.accuracy  * 100).toFixed(1) + '%', good: data.accuracy  >= 0.60 },
    { key: 'Win Rate',  val: (data.win_rate   * 100).toFixed(1) + '%', good: data.win_rate  >= 0.55 },
    { key: 'F1',        val: data.f1.toFixed(3),                        good: data.f1        >= 0.60 },
    { key: 'Sharpe',    val: data.sharpe.toFixed(2),                    good: data.sharpe    >= 1.5  },
    { key: 'Precision', val: (data.precision  * 100).toFixed(1) + '%', good: data.precision >= 0.60 },
    { key: 'Recall',    val: (data.recall     * 100).toFixed(1) + '%', good: data.recall    >= 0.55 },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{data.model_id}</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
            {data.total_signals.toLocaleString()} signals · evaluated {new Date(data.evaluated_at).toLocaleDateString()}
          </div>
        </div>
        <div style={{
          fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 6,
          background: data.accuracy >= 0.60 ? 'rgba(74,222,128,0.12)' : 'rgba(251,191,36,0.12)',
          color: data.accuracy >= 0.60 ? '#4ade80' : '#fbbf24',
          border: `1px solid ${data.accuracy >= 0.60 ? '#4ade8044' : '#fbbf2444'}`,
        }}>
          {data.accuracy >= 0.60 ? '✅ GATE PASSED' : '⚠️ BELOW THRESHOLD'}
        </div>
      </div>
      <div style={s.mlGrid}>
        {metrics.map((m) => (
          <div key={m.key} style={s.mlCard}>
            <div style={s.mlMetric}>
              <span style={s.mlKey}>{m.key}</span>
              <span style={{ ...s.mlVal, color: m.good ? '#4ade80' : '#fbbf24' }}>{m.val}</span>
            </div>
          </div>
        ))}
      </div>
      {data.note && (
        <div style={{ fontSize: 11, color: '#475569', marginTop: 10, fontStyle: 'italic' }}>{data.note}</div>
      )}
      <div style={{ background: '#0f172a', borderRadius: 4, height: 6, marginTop: 12 }}>
        <div style={{
          width: `${Math.min(data.accuracy * 100, 100)}%`, height: 6, borderRadius: 4,
          background: data.accuracy >= 0.60 ? '#4ade80' : '#fbbf24',
          transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  );
};

// ─── Market Regime panel ──────────────────────────────────────────────────────

interface MarketRegime {
  regime: string;
  confidence: number;
  volatility: string;
  trend: string;
  description?: string;
}

const MarketRegimePanel: React.FC = () => {
  const [regime, setRegime] = useState<MarketRegime | null>(null);
  const [err, setErr]       = useState(false);

  useEffect(() => {
    tradingApi.regime('XAU/USD')
      .then((r) => setRegime(r.data as MarketRegime))
      .catch(() => setErr(true));
  }, []);

  if (err || !regime) {
    return (
      <div style={{ color: '#475569', fontSize: 13 }}>
        {err ? 'Regime data unavailable.' : 'Loading…'}
      </div>
    );
  }

  const regimeColor =
    regime.regime === 'trending_up'   ? '#4ade80' :
    regime.regime === 'trending_down' ? '#f87171' :
    regime.regime === 'ranging'       ? '#fbbf24' : '#94a3b8';

  return (
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Regime</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: regimeColor }}>
          {regime.regime.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
        </div>
        {regime.description && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{regime.description}</div>}
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Confidence</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc' }}>{(regime.confidence * 100).toFixed(1)}%</div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Volatility</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: regime.volatility === 'high' ? '#f87171' : regime.volatility === 'medium' ? '#fbbf24' : '#4ade80' }}>
          {regime.volatility.charAt(0).toUpperCase() + regime.volatility.slice(1)}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Trend</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: regime.trend === 'up' ? '#4ade80' : regime.trend === 'down' ? '#f87171' : '#94a3b8' }}>
          {regime.trend === 'up' ? '↑ Bullish' : regime.trend === 'down' ? '↓ Bearish' : '→ Neutral'}
        </div>
      </div>
    </div>
  );
};

// ─── Risk snapshot panel ──────────────────────────────────────────────────────

const RiskSnapshotPanel: React.FC = () => {
  const risk = useStore(selectRiskSnapshot);
  const micro = useStore(selectMicrostructure);
  const sentiment = useStore(selectSentiment);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
      {[
        {
          label: 'Daily Loss',
          value: risk?.daily_loss_pct != null ? `${risk.daily_loss_pct.toFixed(2)}%` : '—',
          warn: risk?.daily_loss_pct != null && risk.daily_loss_pct > 3,
        },
        {
          label: 'Max Drawdown',
          value: risk?.max_drawdown_pct != null ? `${risk.max_drawdown_pct.toFixed(2)}%` : '—',
          warn: risk?.max_drawdown_pct != null && risk.max_drawdown_pct > 8,
        },
        {
          label: 'Open Risk',
          value: risk?.open_risk_pct != null ? `${risk.open_risk_pct.toFixed(2)}%` : '—',
          warn: risk?.open_risk_pct != null && risk.open_risk_pct > 5,
        },
        {
          label: 'Kill Switch',
          value: risk?.kill_switch_active ? '🔴 ACTIVE' : '🟢 Off',
          warn: !!risk?.kill_switch_active,
        },
        {
          label: 'Spread (XAU)',
          value: micro?.spread != null ? `$${micro.spread.toFixed(2)}` : '—',
          warn: micro?.spread != null && micro.spread > 0.5,
        },
        {
          label: 'Sentiment',
          value: sentiment?.signal?.news_sentiment_score != null
            ? `${(sentiment.signal.news_sentiment_score * 100).toFixed(0)}%`
            : '—',
          warn: false,
        },
      ].map(({ label, value, warn }) => (
        <div key={label} style={{
          background: warn ? 'rgba(248,113,113,0.08)' : '#0f172a',
          border: `1px solid ${warn ? '#f87171' : '#1e293b'}`,
          borderRadius: 8, padding: '10px 14px',
        }}>
          <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>{label}</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: warn ? '#f87171' : '#f8fafc' }}>{value}</div>
        </div>
      ))}
    </div>
  );
};

// ─── Quick-nav shortcuts ──────────────────────────────────────────────────────

const QUICK_LINKS = [
  { icon: '⚡', label: 'Trade',        path: '/trade'       },
  { icon: '🧠', label: 'AI Chart Bot', path: '/ai-charts'   },
  { icon: '☢️', label: 'Nuclear AI',   path: '/nuclear'     },
  { icon: '📓', label: 'Journal',      path: '/journal'     },
  { icon: '🏆', label: 'Performance',  path: '/performance' },
  { icon: '💹', label: 'P&L',          path: '/pnl'         },
  { icon: '🌍', label: 'Geopolitical', path: '/geopolitical'},
  { icon: '📡', label: 'Signal Feed',  path: '/feed'        },
];

const QuickNav: React.FC = () => {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {QUICK_LINKS.map(({ icon, label, path }) => (
        <button
          key={path}
          onClick={() => navigate(path)}
          style={{
            background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
            padding: '8px 14px', cursor: 'pointer', color: '#94a3b8',
            fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
            transition: 'border-color 0.15s, color 0.15s',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#3b82f6';
            (e.currentTarget as HTMLButtonElement).style.color = '#60a5fa';
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = '#334155';
            (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8';
          }}
        >
          <span>{icon}</span> {label}
        </button>
      ))}
    </div>
  );
};

// ─── WS status badge ──────────────────────────────────────────────────────────

const WsBadge: React.FC = () => {
  const status = useStore(selectWsStatus);
  const colors: Record<string, string> = {
    connected:    '#22c55e',
    connecting:   '#fbbf24',
    disconnected: '#64748b',
    error:        '#f87171',
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8' }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: colors[status] ?? '#64748b',
        display: 'inline-block',
        boxShadow: status === 'connected' ? `0 0 6px ${colors.connected}` : 'none',
      }} />
      {status === 'connected' ? 'Live' : status.charAt(0).toUpperCase() + status.slice(1)}
    </div>
  );
};



// ─── Main ─────────────────────────────────────────────────────────────────────

const Dashboard: React.FC = () => {
  // All data is populated by AppShell's useBootstrapData (TanStack Query + WebSocket).
  // Reading directly from the store avoids duplicate polling loops.
  const account      = useStore(selectAccount);
  // Equity curve is fetched by useEquityCurve() inside useBootstrapData — read from store.
  const equityHistory = useStore(selectEquityCurve);

  const acc = account;

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.heading}>Dashboard</h1>
          <p style={s.subheading}>Real-time trading overview</p>
        </div>
        <WsBadge />
      </div>

      <PriceTicker />

      <div style={s.statsGrid}>
        <StatCard label="Balance"      value={acc ? '$' + fmt(acc.balance)                    : '—'} />
        <StatCard label="Equity"       value={acc ? '$' + fmt(acc.equity)                     : '—'} highlight />
        <StatCard label="Daily P&L"    value={acc ? fmtUSD(acc.daily_pnl)                     : '—'} positive={acc ? acc.daily_pnl >= 0 : null} sub={acc ? fmtPct(acc.daily_pnl_pct) : undefined} />
        <StatCard label="Total P&L"    value={acc ? fmtUSD(acc.total_pnl)                     : '—'} positive={acc ? acc.total_pnl >= 0 : null} />
        <StatCard label="Win Rate"     value={acc ? (acc.win_rate * 100).toFixed(1) + '%'     : '—'} positive={acc ? acc.win_rate >= 0.55 : null} />
        <StatCard label="Sharpe"       value={acc ? acc.sharpe_ratio.toFixed(2)               : '—'} positive={acc ? acc.sharpe_ratio >= 1.5 : null} />
        <StatCard label="Max Drawdown" value={acc ? (acc.max_drawdown * 100).toFixed(2) + '%' : '—'} positive={acc ? acc.max_drawdown < 0.1 : null} />
        <StatCard label="Open Trades"  value={acc ? String(acc.open_trades)                   : '—'} />
      </div>

      <div style={s.card}>
        <div style={s.cardHeader}>
          <span style={s.cardTitle}>Equity Curve</span>
          {acc && (
            <span style={{ fontSize: 13, color: acc.total_pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>
              {fmtUSD(acc.total_pnl)}
            </span>
          )}
        </div>
        {equityHistory.length === 0 ? (
          <p style={{ color: '#475569', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
            No equity history yet. Start trading to see your curve.
          </p>
        ) : (
          <EquityChart data={equityHistory} />
        )}
      </div>

      <div style={s.twoCol}>
        <div style={s.card}>
          <div style={s.cardTitle}>Open Positions</div>
          <PositionsTable />
        </div>
        <div style={s.card}>
          <div style={s.cardTitle}>Active Signals</div>
          <SignalsPanel />
        </div>
      </div>

      <div style={s.twoCol}>
        <div style={s.card}>
          <div style={{ ...s.cardTitle, marginBottom: 12 }}>Market Regime — XAU/USD</div>
          <MarketRegimePanel />
        </div>
        <div style={s.card}>
          <div style={{ ...s.cardTitle, marginBottom: 12 }}>Risk Snapshot</div>
          <RiskSnapshotPanel />
        </div>
      </div>

      <div style={s.card}>
        <div style={s.cardTitle}>ML Model Accuracy</div>
        <MlAccuracyCard />
      </div>

      <div style={s.card}>
        <div style={{ ...s.cardTitle, marginBottom: 12 }}>Quick Navigation</div>
        <QuickNav />
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:       { padding: '24px 20px', maxWidth: 1280, margin: '0 auto' },
  header:     { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  heading:    { fontSize: 22, fontWeight: 700, color: '#f8fafc', margin: 0 },
  subheading: { fontSize: 13, color: '#64748b', margin: '2px 0 0' },

  ticker:       { display: 'flex', gap: 0, overflowX: 'auto', marginBottom: 16, background: '#0f172a', borderRadius: 10, border: '1px solid #1e293b' },
  tickerItem:   { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 120, padding: '10px 16px', borderRight: '1px solid #1e293b' },
  tickerSymbol: { fontSize: 10, color: '#64748b', fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase' },
  tickerPrice:  { fontSize: 17, fontWeight: 700, color: '#f8fafc', margin: '3px 0' },
  tickerChange: { fontSize: 12, fontWeight: 600 },

  statsGrid:         { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10, marginBottom: 14 },
  statCard:          { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 14px' },
  statCardHighlight: { border: '1px solid #3b82f6', boxShadow: '0 0 12px rgba(59,130,246,0.15)' },
  statLabel:         { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 },
  statValue:         { fontSize: 20, fontWeight: 700, color: '#f8fafc' },
  statSub:           { fontSize: 11, color: '#94a3b8', marginTop: 2 },

  card:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '16px 18px', marginBottom: 14 },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  cardTitle:  { fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 },

  twoCol: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 },

  table: { width: '100%', borderCollapse: 'collapse' },
  th:    { textAlign: 'left', fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, padding: '6px 8px', borderBottom: '1px solid #334155' },
  tr:    { borderBottom: '1px solid #0f172a' },
  td:    { padding: '9px 8px', fontSize: 13, color: '#cbd5e1' },
  empty: { color: '#64748b', fontSize: 13, margin: '8px 0' },

  signalGrid:   { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 },
  signalCard:   { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px' },
  signalHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  signalSymbol: { fontSize: 14, fontWeight: 700, color: '#e2e8f0' },
  signalBadge:  { fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, letterSpacing: 0.5 },
  signalRow:    { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 },
  signalKey:    { fontSize: 11, color: '#64748b', minWidth: 72 },
  signalVal:    { fontSize: 12, fontWeight: 600, color: '#e2e8f0' },

  mlGrid:    { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 },
  mlCard:    { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '14px 16px' },
  mlName:    { fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 10 },
  mlMetrics: { display: 'flex', gap: 16 },
  mlMetric:  { display: 'flex', flexDirection: 'column', gap: 2 },
  mlKey:     { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 },
  mlVal:     { fontSize: 16, fontWeight: 700, color: '#f8fafc' },
};

export default Dashboard;
