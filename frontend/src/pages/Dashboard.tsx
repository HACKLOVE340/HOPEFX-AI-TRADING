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
import { Link } from 'react-router-dom';
import { createChart, AreaSeries, type IChartApi, type ISeriesApi, ColorType } from 'lightweight-charts';
import { PageHeader, EmptyState, CrossLinkBar, Spinner } from '../components';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { DataAge } from '../components/ui/DataAge';
import { useFlashHighlight, useFlashMap } from '../hooks/useFlashHighlight';
import {
  useStore,
  selectAccount,
  selectPositions,
  selectSignals,
  selectWsStatus,
  selectFeedLive,
  selectEquityCurve,
  selectRiskSnapshot,
  selectMicrostructure,
  selectSentiment,
} from '../store';
import { mlApi, tradingApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import type { EquityPoint } from '../types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtUSD = (n: number) =>
  (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

const fmtPct = (n: number) => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

/**
 * Statistical account fields are absent on a new account and before the first
 * evaluation cycle (audit #37/#39). On a trading dashboard "no data yet" and
 * "exactly zero" are very different claims, so render an em-dash rather than a
 * confident 0.00 the user could mistake for a measured result.
 *
 * `??` would be wrong here for the same reason: a fabricated zero Sharpe reads
 * as a real, terrible Sharpe.
 */
const has = (n: number | undefined): n is number => typeof n === 'number' && Number.isFinite(n);
const orDash = (n: number | undefined, render: (v: number) => string) => (has(n) ? render(n) : '—');

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
const WATCHED_SYMBOLS = ['XAU/USD', 'XAG/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];

const TickerItem: React.FC<{ sym: string }> = ({ sym }) => {
  const tick = useStore((st) => st.prices[sym]);
  const flash = useFlashHighlight(tick?.mid);
  const up    = tick ? tick.change_pct >= 0 : null;
  const decimals =
    sym.includes('JPY') ? 3 :
    sym.includes('BTC') ? 0 :
    sym.includes('XAU') ? 2 :
    sym.includes('XAG') ? 3 : 5;

  return (
    <Link
      to={`/ai-chart`}
      state={{ symbol: sym }}
      style={{
        ...s.tickerItem,
        background: flash,
        transition: 'background 0.4s ease',
        textDecoration: 'none',
      }}
    >
      <span style={s.tickerSymbol}>{sym}</span>
      <span style={s.tickerPrice}>
        {tick ? fmt(tick.mid, decimals) : '—'}
      </span>
      <span style={{ ...s.tickerChange, color: up === true ? '#4ade80' : up === false ? '#f87171' : '#64748b' }}>
        {tick ? fmtPct(tick.change_pct) : '—'}
      </span>
      {tick && (
        <span style={{ fontSize: 10, color: '#475569', marginTop: 1 }}>
          {fmt(tick.bid, decimals)} / {fmt(tick.ask, decimals)}
        </span>
      )}
    </Link>
  );
};

const PriceTicker: React.FC = () => (
  /* Outer div allows horizontal scroll on mobile without affecting the page */
  <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch', marginBottom: 12 }}>
    <div style={{ ...s.ticker, minWidth: 'max-content' }}>
      {WATCHED_SYMBOLS.map((sym) => <TickerItem key={sym} sym={sym} />)}
    </div>
  </div>
);

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
      const prev = acc[acc.length - 1];
      if (prev && prev.time === pt.time) {
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
  const rafRef       = useRef<number>(0);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
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

    const series = chart.addSeries(AreaSeries, {
      lineColor:   '#3b82f6',
      topColor:    'rgba(59,130,246,0.25)',
      bottomColor: 'rgba(59,130,246,0.0)',
      lineWidth:   2,
    });

    chartRef.current  = chart;
    seriesRef.current = series;

    const points = toChartPoints(data);
    if (points.length > 0) {
      series.setData(points);
      chart.timeScale().fitContent();
      chart.timeScale().scrollToRealTime();
    }

    // rAF-throttled ResizeObserver prevents layout thrashing
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      seriesRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!seriesRef.current) return;
    const points = toChartPoints(data);
    if (points.length > 0) {
      seriesRef.current.setData(points);
      chartRef.current?.timeScale().fitContent();
      chartRef.current?.timeScale().scrollToRealTime();
    }
  }, [data]);

  return <div ref={containerRef} style={{ width: '100%', height: 240 }} />;
};

// ─── Positions table with real-time P&L flash highlights ─────────────────────

const PositionsTable: React.FC = () => {
  const positions = useStore(selectPositions);
  const flashColors = useFlashMap(
    positions.map((p) => ({ id: p.id, value: p.unrealized_pnl })),
  );

  if (positions.length === 0) {
    return <EmptyState compact icon="📭" title="No open positions" description="Your live positions will appear here once you place a trade." links={[{ label: 'Trade Now', href: '/trade', icon: '⚡' }]} />;
  }

  return (
    <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      <table style={{ ...s.table, minWidth: 560 }}>
        <thead>
          <tr>
            {['Symbol', 'Side', 'Size', 'Entry', 'Current', 'Unreal. P&L', 'Opened'].map((h) => (
              <th key={h} style={s.th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr
              key={p.id}
              style={{
                ...s.tr,
                background: flashColors[p.id] ?? 'transparent',
                transition: 'background 0.4s ease',
              }}
            >
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
    </div>
  );
};

// ─── Signals panel ────────────────────────────────────────────────────────────

const SignalsPanel: React.FC = () => {
  const signals = useStore(selectSignals);
  const active  = signals.filter((sig) => sig.status === 'active').slice(0, 6);

  if (active.length === 0) {
    return <EmptyState compact icon="📡" title="No active signals" description="AI-generated trading signals will appear here in real-time." links={[{ label: 'Signals Feed', href: '/signals', icon: '📡' }]} />;
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
  // Nullable: the server sends null when the evaluation measured no win rate,
  // rather than substituting accuracy for it. Rendering that as 0.0% would be
  // its own lie, so the card below shows "—".
  win_rate:      number | null;
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
        setMlErr(extractApiError(err, 'Failed to load model metrics.'));
      });
  }, []);

  if (mlErr) {
    return <p style={{ color: '#f87171', fontSize: 13, padding: '16px 0' }}>{mlErr}</p>;
  }
  if (!data) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#475569', fontSize: 13, padding: '16px 0' }}>
        <Spinner size="sm" /> Loading model metrics…
      </div>
    );
  }
  // Guard against partial API responses — all numeric fields may be absent
  // on first evaluation or when the model has not yet accumulated enough signals.
  const safeAccuracy    = data.accuracy      ?? 0;
  const safeWinRate     = data.win_rate      ?? 0;
  const safeF1          = data.f1            ?? 0;
  const safeSharpe      = data.sharpe        ?? 0;
  const safePrecision   = data.precision     ?? 0;
  const safeRecall      = data.recall        ?? 0;
  const safeTotalSigs   = data.total_signals ?? 0;

  if (safeAccuracy === 0 && safeTotalSigs === 0) {
    return (
      <p style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>
        {data.note || 'No model metrics available yet.'}
      </p>
    );
  }

  const metrics = [
    { key: 'Accuracy',  val: (safeAccuracy  * 100).toFixed(1) + '%', good: safeAccuracy  >= 0.60 },
    { key: 'Win Rate',  val: data.win_rate == null ? '—' : (safeWinRate * 100).toFixed(1) + '%',
      good: data.win_rate == null ? undefined : safeWinRate >= 0.55 },
    { key: 'F1',        val: safeF1.toFixed(3),                       good: safeF1        >= 0.60 },
    { key: 'Sharpe',    val: safeSharpe.toFixed(2),                   good: safeSharpe    >= 1.5  },
    { key: 'Precision', val: (safePrecision * 100).toFixed(1) + '%',  good: safePrecision >= 0.60 },
    { key: 'Recall',    val: (safeRecall    * 100).toFixed(1) + '%',  good: safeRecall    >= 0.55 },
  ];

  const evaluatedLabel = data.evaluated_at
    ? new Date(data.evaluated_at).toLocaleDateString()
    : '—';

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{data.model_id ?? 'Model'}</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
            {safeTotalSigs.toLocaleString()} signals · evaluated {evaluatedLabel}
          </div>
        </div>
        <div style={{
          fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 6,
          background: safeAccuracy >= 0.60 ? 'rgba(74,222,128,0.12)' : 'rgba(251,191,36,0.12)',
          color: safeAccuracy >= 0.60 ? '#4ade80' : '#fbbf24',
          border: `1px solid ${safeAccuracy >= 0.60 ? '#4ade8044' : '#fbbf2444'}`,
        }}>
          {safeAccuracy >= 0.60 ? '✅ GATE PASSED' : '⚠️ BELOW THRESHOLD'}
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
          width: `${Math.min(safeAccuracy * 100, 100)}%`, height: 6, borderRadius: 4,
          background: safeAccuracy >= 0.60 ? '#4ade80' : '#fbbf24',
          transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  );
};

// ─── Market Regime panel ──────────────────────────────────────────────────────

interface MarketRegime {
  // Nullable in practice, not by design: `/trading/regime` returns a partial
  // object before the classifier has enough bars, and typing these as required
  // is what let the crash through tsc (F1-03).
  regime: string | null;
  confidence: number | null;
  volatility: string | null;
  trend: string | null;
  description?: string;
}

const MarketRegimePanel: React.FC = () => {
  const [regime, setRegime] = useState<MarketRegime | null>(null);
  const [err, setErr]       = useState(false);
  // Whether the request has come back at all. Without it, a response that
  // arrived but named no regime is indistinguishable from one still in flight,
  // and the panel spins forever instead of admitting it has nothing.
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    tradingApi.regime('XAU/USD')
      .then((r) => { setRegime(r.data as MarketRegime); setLoaded(true); })
      .catch(() => { setErr(true); setLoaded(true); });
  }, []);

  // `!regime` only catches null. An object without a `regime` field passed the
  // guard and then threw on `.replace` of undefined, taking the whole Dashboard
  // route down rather than this panel — the F1-03 class, and the reason the
  // Dashboard row of the F1 matrix could not be scored at all. Treat a payload
  // that does not name a regime as no regime data.
  if (err || !regime?.regime) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#475569', fontSize: 13 }}>
        {err || loaded ? 'Regime data unavailable.' : <><Spinner size="sm" /> Loading…</>}
      </div>
    );
  }

  const regimeColor =
    regime.regime === 'trending_up'   ? '#4ade80' :
    regime.regime === 'trending_down' ? '#f87171' :
    regime.regime === 'ranging'       ? '#fbbf24' : '#94a3b8';

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 16 }}>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Regime</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: regimeColor }}>
          {regime.regime.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
        </div>
        {regime.description && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{regime.description}</div>}
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Confidence</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc' }}>{regime.confidence != null ? `${(regime.confidence * 100).toFixed(1)}%` : '—'}</div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Volatility</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: regime.volatility === 'high' ? '#f87171' : regime.volatility === 'medium' ? '#fbbf24' : '#4ade80' }}>
          {regime.volatility ? regime.volatility.charAt(0).toUpperCase() + regime.volatility.slice(1) : '—'}
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
  { icon: '⚡', label: 'Trade',        path: '/trade'        },
  { icon: '🧠', label: 'AI Chart Bot', path: '/ai-chart'     },
  { icon: '☢️', label: 'Nuclear AI',   path: '/nuclear'      },
  { icon: '📓', label: 'Journal',      path: '/journal'      },
  { icon: '🏆', label: 'Performance',  path: '/performance'  },
  { icon: '💹', label: 'P&L',          path: '/pnl'          },
  { icon: '🌍', label: 'Geopolitical', path: '/geopolitical' },
  { icon: '📡', label: 'Signal Feed',  path: '/signals'      },
  { icon: '👁', label: 'Watchlist',    path: '/watchlist'    },
  { icon: '🔗', label: 'Correlation',  path: '/correlation'  },
  { icon: '🔁', label: 'Copy Trading', path: '/copy-trading' },
  { icon: '▶️', label: 'Replay',       path: '/replay'       },
];

const QuickNav: React.FC = () => (
  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
    {QUICK_LINKS.map(({ icon, label, path }) => (
      <Link
        key={path}
        to={path}
        style={{
          background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
          padding: '8px 14px', color: '#94a3b8',
          fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
          textDecoration: 'none', transition: 'border-color 0.15s, color 0.15s',
        }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLAnchorElement).style.borderColor = '#3b82f6';
          (e.currentTarget as HTMLAnchorElement).style.color = '#60a5fa';
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155';
          (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8';
        }}
      >
        <span>{icon}</span> {label}
      </Link>
    ))}
  </div>
);

// ─── WS status badge ──────────────────────────────────────────────────────────

const WsBadge: React.FC = () => {
  const status = useStore(selectWsStatus);
  // F1-02 / S9-01: this badge said "Live", in glowing green, for as long as the
  // socket was open — including while the server's broadcast loop was stalled
  // and nothing had arrived for minutes. It is the one cue a trader glances at
  // to decide whether the prices beside it can be trusted, so it must describe
  // the *feed*, not the connection.
  const feedLive   = useStore(selectFeedLive);
  const lastDataAt = useStore((st) => st.lastDataAt);
  const stalled    = status === 'connected' && !feedLive;

  const colors: Record<string, string> = {
    connected:    '#22c55e',
    connecting:   '#fbbf24',
    disconnected: '#64748b',
    error:        '#f87171',
  };
  const dot = stalled ? '#ffb800' : (colors[status] ?? '#64748b');

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8' }}>
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: dot,
        display: 'inline-block',
        boxShadow: feedLive ? `0 0 6px ${colors.connected}` : 'none',
      }} />
      {stalled
        ? 'Stalled'
        : status === 'connected' ? 'Live' : status.charAt(0).toUpperCase() + status.slice(1)}
      {stalled && <DataAge at={lastDataAt} />}
    </div>
  );
};



// ─── Main ─────────────────────────────────────────────────────────────────────

const Dashboard: React.FC = () => {
  const account       = useStore(selectAccount);
  const equityHistory = useStore(selectEquityCurve);
  const acc = account;

  return (
    <div className="page-content fade-in">
      <PageHeader
        title="Dashboard"
        subtitle="Real-time trading overview"
        icon="📊"
        breadcrumbs={[{ label: "Dashboard" }]}
        badge={<WsBadge />}
        actions={
          <Link
            to="/trade"
            style={{
              background: '#1d4ed8', border: '1px solid #3b82f6', borderRadius: 8,
              color: '#fff', fontSize: 13, fontWeight: 700, padding: '8px 18px',
              textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            ⚡ New Trade
          </Link>
        }
      />

      <PriceTicker />

      {!acc ? (
        <PanelSkeleton rows={3} />
      ) : (
        <div style={s.statsGrid}>
          <StatCard label="Balance"     value={orDash(acc.balance, v => '$' + fmt(v))} />
          <StatCard label="Equity"      value={orDash(acc.equity, v => '$' + fmt(v))} highlight />
          <StatCard label="Daily P&L"   value={orDash(acc.daily_pnl, fmtUSD)}
            positive={has(acc.daily_pnl) ? acc.daily_pnl >= 0 : undefined}
            sub={orDash(acc.daily_pnl_pct, fmtPct)} />
          <StatCard label="Total P&L"   value={orDash(acc.total_pnl, fmtUSD)}
            positive={has(acc.total_pnl) ? acc.total_pnl >= 0 : undefined} />
          <StatCard label="Win Rate"    value={orDash(acc.win_rate, v => (v * 100).toFixed(1) + '%')}
            positive={has(acc.win_rate) ? acc.win_rate >= 0.55 : undefined} />
          <StatCard label="Sharpe"      value={orDash(acc.sharpe_ratio, v => v.toFixed(2))}
            positive={has(acc.sharpe_ratio) ? acc.sharpe_ratio >= 1.5 : undefined} />
          <StatCard label="Account DD"  value={orDash(acc.max_drawdown, v => (v * 100).toFixed(2) + '%')}
            positive={has(acc.max_drawdown) ? acc.max_drawdown < 0.1 : undefined} />
          <StatCard label="Open Trades" value={orDash(acc.open_trades, String)} />
        </div>
      )}

      <div style={s.card}>
        <div style={s.cardHeader}>
          <span style={s.cardTitle}>Live Equity Curve</span>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            {has(acc?.total_pnl) && (
              <span style={{ fontSize: 13, color: acc.total_pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                {fmtUSD(acc.total_pnl)}
              </span>
            )}
            <Link to="/performance" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>
              Full report →
            </Link>
          </div>
        </div>
        {equityHistory.length === 0 ? (
          <EmptyState
            icon="📈"
            title="No equity history yet"
            description="Start trading to see your equity curve grow here."
            links={[{ label: '⚡ Start Trading', href: '/trade' }]}
            compact
          />
        ) : (
          <EquityChart data={equityHistory} />
        )}
      </div>

      <div style={s.twoCol}>
        <div style={s.card}>
          <div style={{ ...s.cardHeader, marginBottom: 10 }}>
            <span style={s.cardTitle}>Open Positions</span>
            <Link to="/portfolio" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>View all →</Link>
          </div>
          <PositionsTable />
        </div>
        <div style={s.card}>
          <div style={{ ...s.cardHeader, marginBottom: 10 }}>
            <span style={s.cardTitle}>Active Signals</span>
            <Link to="/ai-strategy" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>Strategy gen →</Link>
          </div>
          <SignalsPanel />
        </div>
      </div>

      <div style={s.twoCol}>
        <div style={s.card}>
          <div style={{ ...s.cardHeader, marginBottom: 12 }}>
            <span style={s.cardTitle}>Market Regime — XAU/USD</span>
            <Link to="/ai-chart" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>AI Chart →</Link>
          </div>
          <MarketRegimePanel />
        </div>
        <div style={s.card}>
          <div style={{ ...s.cardHeader, marginBottom: 12 }}>
            <span style={s.cardTitle}>Risk Snapshot</span>
            <Link to="/risk-calculator" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>Calculator →</Link>
          </div>
          <RiskSnapshotPanel />
        </div>
      </div>

      <div style={s.card}>
        <div style={{ ...s.cardHeader, marginBottom: 12 }}>
          <span style={s.cardTitle}>ML Model Accuracy</span>
          <Link to="/performance" style={{ fontSize: 12, color: '#3b82f6', textDecoration: 'none' }}>Performance →</Link>
        </div>
        <MlAccuracyCard />
      </div>

      <div style={s.card}>
        <div style={{ ...s.cardTitle, marginBottom: 12 }}>Quick Navigation</div>
        <QuickNav />
      </div>

      <CrossLinkBar title="Explore" links={[
        { label: 'Trade',           href: '/trade',            icon: '⚡', color: '#3b82f6' },
        { label: 'Portfolio',       href: '/portfolio',        icon: '💼', color: '#4ade80' },
        { label: 'AI Charts',       href: '/ai-chart',         icon: '📈', color: '#06b6d4' },
        { label: 'Signals',         href: '/signals',          icon: '📡', color: '#a78bfa' },
        { label: 'Risk Calculator', href: '/risk-calculator',  icon: '🧮', color: '#f59e0b' },
        { label: 'Economic Calendar',href: '/calendar',        icon: '📅', color: '#f97316' },
        { label: 'Leaderboard',     href: '/leaderboard',      icon: '🏆', color: '#fbbf24' },
        { label: 'Performance',     href: '/performance',      icon: '📊', color: '#22c55e' },
      ]} />
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  // Responsive page padding — overridden by media queries via className below
  page:       { padding: '12px', maxWidth: 1280, margin: '0 auto', width: '100%' },
  header:     { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  heading:    { fontSize: 22, fontWeight: 700, color: '#f8fafc', margin: 0 },
  subheading: { fontSize: 13, color: '#64748b', margin: '2px 0 0' },

  // Ticker: no overflow here — wrapper div handles scroll
  ticker:       { display: 'flex', gap: 0, background: '#0f172a', borderRadius: 10, border: '1px solid #1e293b' },
  tickerItem:   { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 110, padding: '10px 14px', borderRight: '1px solid #1e293b' },
  tickerSymbol: { fontSize: 10, color: '#64748b', fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase' },
  tickerPrice:  { fontSize: 16, fontWeight: 700, color: '#f8fafc', margin: '3px 0' },
  tickerChange: { fontSize: 12, fontWeight: 600 },

  // Stats grid: auto-fill so it collapses to 2 cols on mobile naturally
  statsGrid:         { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, marginBottom: 12 },
  statCard:          { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '10px 12px' },
  statCardHighlight: { border: '1px solid #3b82f6', boxShadow: '0 0 12px rgba(59,130,246,0.15)' },
  statLabel:         { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 },
  statValue:         { fontSize: 18, fontWeight: 700, color: '#f8fafc' },
  statSub:           { fontSize: 11, color: '#94a3b8', marginTop: 2 },

  card:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 14px', marginBottom: 12 },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  cardTitle:  { fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 },

  // twoCol: single column on mobile, 2 cols on sm+ — achieved via className
  twoCol: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 340px), 1fr))', gap: 12, marginBottom: 12 },

  table: { width: '100%', borderCollapse: 'collapse' },
  th:    { textAlign: 'left', fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, padding: '6px 8px', borderBottom: '1px solid #334155', whiteSpace: 'nowrap' },
  tr:    { borderBottom: '1px solid #0f172a' },
  td:    { padding: '9px 8px', fontSize: 13, color: '#cbd5e1', whiteSpace: 'nowrap' },
  empty: { color: '#64748b', fontSize: 13, margin: '8px 0' },

  // signalGrid: single col on mobile, 2 cols on sm+
  signalGrid:   { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 260px), 1fr))', gap: 10 },
  signalCard:   { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px' },
  signalHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  signalSymbol: { fontSize: 14, fontWeight: 700, color: '#e2e8f0' },
  signalBadge:  { fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, letterSpacing: 0.5 },
  signalRow:    { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 },
  signalKey:    { fontSize: 11, color: '#64748b', minWidth: 72 },
  signalVal:    { fontSize: 12, fontWeight: 600, color: '#e2e8f0' },

  mlGrid:    { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(160px, 100%), 1fr))', gap: 10 },
  mlCard:    { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px' },
  mlName:    { fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 10 },
  mlMetrics: { display: 'flex', gap: 16 },
  mlMetric:  { display: 'flex', flexDirection: 'column', gap: 2 },
  mlKey:     { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 },
  mlVal:     { fontSize: 16, fontWeight: 700, color: '#f8fafc' },
};

export default Dashboard;
