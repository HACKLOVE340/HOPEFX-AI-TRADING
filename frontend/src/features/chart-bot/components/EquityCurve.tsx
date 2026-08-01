/**
 * EquityCurve.tsx
 * Advanced equity curve with dynamic drawdown shading, Sharpe/Sortino
 * overlays, zoom/pan, and intelligent annotations.
 * Built on lightweight-charts v5 — imperative DOM API, no recharts.
 */

import React, { useState, useMemo, memo, useCallback, useEffect, useRef } from 'react';
import {
  createChart, createSeriesMarkers, AreaSeries, LineSeries, HistogramSeries,
} from 'lightweight-charts';
import type { IChartApi, ISeriesApi, UTCTimestamp, SeriesMarker } from 'lightweight-charts';
import { useEquityCurve } from '../hooks/useChartData';
import { useChartBotStore } from '../store/chart-bot-store';
import { COLORS, CHART_DIMS } from '../utils/design-tokens';
import { formatPnl, formatPct, formatDateTime } from '../utils/formatters';
import { fmtRatio } from '../../../lib/utils';
import type { EquityPoint } from '../types';

// ─── Period selector ──────────────────────────────────────────────────────────

const PERIODS = [
  { label: '1W',  days: 7   },
  { label: '1M',  days: 30  },
  { label: '3M',  days: 90  },
  { label: '6M',  days: 180 },
  { label: '1Y',  days: 365 },
  { label: 'ALL', days: 0   },
];

// ─── Stats Bar ────────────────────────────────────────────────────────────────

interface Stats {
  totalReturn: number;
  totalReturnPct: number;
  maxDrawdown: number;
  avgSharpe: number | null;
  avgSortino: number | null;
  winDays: number;
  lossDays: number;
  currentEquity: number;
  peakEquity: number;
}

const StatPill = memo(({ label, value, color }: { label: string; value: string; color: string }) => (
  <div style={styles.statPill}>
    <span style={styles.statLabel}>{label}</span>
    <span style={{ ...styles.statValue, color }}>{value}</span>
  </div>
));
StatPill.displayName = 'StatPill';

const StatsBar = memo(({ stats }: { stats: Stats }) => (
  <div style={styles.statsBar}>
    <StatPill label="Total Return" value={formatPnl(stats.totalReturn)} color={stats.totalReturn >= 0 ? COLORS.profit.base : COLORS.loss.base} />
    <StatPill label="Return %" value={formatPct(stats.totalReturnPct)} color={stats.totalReturnPct >= 0 ? COLORS.profit.base : COLORS.loss.base} />
    <StatPill label="Max DD" value={formatPct(stats.maxDrawdown)} color={COLORS.loss.base} />
    <StatPill label="Sharpe" value={fmtRatio(stats.avgSharpe)} color={(stats.avgSharpe ?? 0) >= 1 ? COLORS.profit.base : COLORS.neon.gold} />
    <StatPill label="Sortino" value={fmtRatio(stats.avgSortino)} color={(stats.avgSortino ?? 0) >= 1.5 ? COLORS.profit.base : COLORS.neon.gold} />
    <StatPill label="Win Days" value={`${stats.winDays}`} color={COLORS.profit.base} />
    <StatPill label="Loss Days" value={`${stats.lossDays}`} color={COLORS.loss.base} />
  </div>
));
StatsBar.displayName = 'StatsBar';

// ─── Legend ───────────────────────────────────────────────────────────────────

const LegendItem = memo(({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) => (
  <div style={styles.legendItem}>
    <div style={{ ...styles.legendLine, background: dashed ? 'transparent' : color, borderTop: dashed ? `1px dashed ${color}` : 'none', width: 20 }} />
    <span style={{ ...styles.legendLabel, color: COLORS.text.muted }}>{label}</span>
  </div>
));
LegendItem.displayName = 'LegendItem';

// ─── Main Component ───────────────────────────────────────────────────────────

const EquityCurve: React.FC = () => {
  const [period, setPeriod] = useState(90);
  const { data: rawPoints, isLoading } = useEquityCurve(period || 365);
  const livePoints = useChartBotStore((s) => s.equityCurve);

  // Chart refs
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef   = useRef<HTMLDivElement>(null);
  const mainChartRef     = useRef<IChartApi | null>(null);
  const ddChartRef       = useRef<IChartApi | null>(null);
  const equitySerRef     = useRef<ISeriesApi<'Area'> | null>(null);
  const sharpeSerRef     = useRef<ISeriesApi<'Line'> | null>(null);
  const sortinoSerRef    = useRef<ISeriesApi<'Line'> | null>(null);
  const ddSerRef         = useRef<ISeriesApi<'Histogram'> | null>(null);
  const rafRef           = useRef<number>(0);

  // Merge fetched + live streaming points
  const points: EquityPoint[] = useMemo(() => {
    const base = rawPoints ?? [];
    if (!livePoints.length) return base;
    const lastFetched = base[base.length - 1]?.time ?? 0;
    const newLive = livePoints.filter((p) => p.time > lastFetched);
    return [...base, ...newLive];
  }, [rawPoints, livePoints]);

  // Compute stats
  const stats = useMemo<Stats>(() => {
    if (!points.length) return {
      totalReturn: 0, totalReturnPct: 0, maxDrawdown: 0,
      avgSharpe: null, avgSortino: null, winDays: 0, lossDays: 0,
      currentEquity: 0, peakEquity: 0,
    };
    // `points.length` being non-zero does not narrow points[n] (audit #38).
    const first = points[0]?.equity ?? 0;
    const last  = points[points.length - 1]?.equity ?? first;
    const peak  = Math.max(...points.map((p) => p.equity));
    const maxDD = Math.min(...points.map((p) => p.drawdown));
    // Average only over points that actually carry a finite ratio. A fresh
    // account has no closed trades, so the backend cannot compute Sharpe or
    // Sortino and omits them — and `undefined + 0` is NaN, which poisons the
    // whole reduce and renders literally as "NaN" in the stats bar.
    const finiteAvg = (pick: (p: EquityPoint) => number | null | undefined): number | null => {
      const vals = points.map(pick).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
      return vals.length ? vals.reduce((a, v) => a + v, 0) / vals.length : null;
    };
    const avgSharpe  = finiteAvg((p) => p.sharpe);
    const avgSortino = finiteAvg((p) => p.sortino);
    const winDays  = points.filter((p, i) => i > 0 && p.equity > (points[i - 1]?.equity ?? p.equity)).length;
    const lossDays = points.filter((p, i) => i > 0 && p.equity < (points[i - 1]?.equity ?? p.equity)).length;
    return {
      totalReturn:    last - first,
      // first === 0 would give Infinity/NaN — a zero starting equity has no
      // meaningful percentage return.
      totalReturnPct: first !== 0 ? ((last - first) / first) * 100 : 0,
      maxDrawdown:    maxDD,
      avgSharpe, avgSortino, winDays, lossDays,
      currentEquity: last, peakEquity: peak,
    };
  }, [points]);

  // ── Main chart init ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mainContainerRef.current) return;
    const chart = createChart(mainContainerRef.current, {
      layout:    { background: { color: 'transparent' }, textColor: COLORS.text.muted },
      grid:      { vertLines: { color: COLORS.bg.surface }, horzLines: { color: COLORS.bg.surface } },
      rightPriceScale: { borderColor: COLORS.bg.border },
      leftPriceScale:  { borderColor: COLORS.bg.border, visible: true, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: COLORS.bg.border, timeVisible: true, secondsVisible: false },
      height: CHART_DIMS.equityCurveHeight,
      width:  mainContainerRef.current.clientWidth,
    });

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor:   COLORS.neon.cyan,
      topColor:    `${COLORS.neon.cyan}40`,
      bottomColor: `${COLORS.neon.cyan}03`,
      lineWidth:   2,
      priceScaleId: 'right',
      lastValueVisible: true,
      priceLineVisible: false,
    });
    const sharpeSeries = chart.addSeries(LineSeries, {
      color:    COLORS.neon.gold,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceScaleId: 'left',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    const sortinoSeries = chart.addSeries(LineSeries, {
      color:    COLORS.neon.purple,
      lineWidth: 1,
      lineStyle: 3, // dotted
      priceScaleId: 'left',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    // Zero and Sharpe=1 reference lines
    sharpeSeries.createPriceLine({ price: 0, color: COLORS.bg.divider,   lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });
    sharpeSeries.createPriceLine({ price: 1, color: `${COLORS.neon.gold}66`, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SR=1' });

    mainChartRef.current    = chart;
    equitySerRef.current    = equitySeries;
    sharpeSerRef.current    = sharpeSeries;
    sortinoSerRef.current   = sortinoSeries;

    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (mainContainerRef.current && mainChartRef.current) {
          mainChartRef.current.applyOptions({ width: mainContainerRef.current.clientWidth });
        }
      });
    });
    ro.observe(mainContainerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      mainChartRef.current  = null;
      equitySerRef.current  = null;
      sharpeSerRef.current  = null;
      sortinoSerRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Drawdown sub-chart init ────────────────────────────────────────────────
  useEffect(() => {
    if (!ddContainerRef.current) return;
    const chart = createChart(ddContainerRef.current, {
      layout:    { background: { color: 'transparent' }, textColor: COLORS.text.muted },
      grid:      { vertLines: { color: COLORS.bg.surface }, horzLines: { color: COLORS.bg.surface } },
      rightPriceScale: { borderColor: COLORS.bg.border },
      timeScale: { borderColor: COLORS.bg.border, visible: false },
      height: 60,
      width:  ddContainerRef.current.clientWidth,
    });
    const ddSeries = chart.addSeries(HistogramSeries, {
      color:    `${COLORS.loss.base}80`,
      priceScaleId: 'right',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    ddChartRef.current = chart;
    ddSerRef.current   = ddSeries;

    const ro = new ResizeObserver(() => {
      if (ddContainerRef.current && ddChartRef.current) {
        ddChartRef.current.applyOptions({ width: ddContainerRef.current.clientWidth });
      }
    });
    ro.observe(ddContainerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      ddChartRef.current = null;
      ddSerRef.current   = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Data update ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!equitySerRef.current || !sharpeSerRef.current || !sortinoSerRef.current || !ddSerRef.current) return;
    if (!points.length) return;

    // Deduplicate by time
    const seen = new Set<number>();
    const sorted: EquityPoint[] = [...points]
      .sort((a, b) => a.time - b.time)
      .filter((p) => { if (seen.has(p.time)) return false; seen.add(p.time); return true; });

    equitySerRef.current.setData(
      sorted.map(p => ({ time: p.time as UTCTimestamp, value: p.equity })),
    );
    sharpeSerRef.current.setData(
      sorted.map(p => ({ time: p.time as UTCTimestamp, value: p.sharpe })),
    );
    sortinoSerRef.current.setData(
      sorted.map(p => ({ time: p.time as UTCTimestamp, value: p.sortino })),
    );
    ddSerRef.current.setData(
      sorted.map(p => ({
        time:  p.time as UTCTimestamp,
        value: p.drawdown,
        color: p.drawdown < -5 ? `${COLORS.loss.base}cc` : `${COLORS.loss.base}66`,
      })),
    );

    // Annotation markers on equity series
    const markers: SeriesMarker<UTCTimestamp>[] = sorted
      .filter(p => p.annotation)
      .map(p => ({
        time:     p.time as UTCTimestamp,
        position: 'aboveBar' as const,
        color:    COLORS.neon.amber,
        shape:    'circle' as const,
        text:     p.annotation!.slice(0, 24),
      }));
    createSeriesMarkers(equitySerRef.current, markers);

    mainChartRef.current?.timeScale().fitContent();
    ddChartRef.current?.timeScale().fitContent();
  }, [points]);

  const handlePeriod = useCallback((days: number) => setPeriod(days), []);

  if (isLoading && !points.length) {
    return (
      <div style={styles.wrapper}>
        <div style={styles.loading}>Loading equity curve…</div>
      </div>
    );
  }

  return (
    <div style={styles.wrapper}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.title}>EQUITY CURVE</span>
          <span style={{ ...styles.equityVal, color: stats.totalReturn >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
            {formatPnl(stats.currentEquity)}
          </span>
        </div>
        <div style={styles.periodRow}>
          {PERIODS.map((p) => (
            <button
              key={p.label}
              onClick={() => handlePeriod(p.days)}
              style={{ ...styles.periodBtn, ...(period === p.days ? styles.periodBtnActive : {}) }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Main equity chart */}
      <div style={{ padding: '0 4px' }}>
        <div ref={mainContainerRef} style={{ width: '100%', height: CHART_DIMS.equityCurveHeight }} />
      </div>

      {/* Drawdown sub-chart */}
      <div style={{ padding: '0 4px', marginTop: 2 }}>
        <div style={styles.ddLabel}>DRAWDOWN</div>
        <div ref={ddContainerRef} style={{ width: '100%', height: 60 }} />
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        <LegendItem color={COLORS.neon.cyan}   label="Equity" />
        <LegendItem color={COLORS.neon.gold}   label="Sharpe" dashed />
        <LegendItem color={COLORS.neon.purple} label="Sortino" dashed />
        <LegendItem color={COLORS.loss.base}   label="Drawdown" />
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    background: COLORS.bg.surface,
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 8,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px 8px',
    borderBottom: `1px solid ${COLORS.bg.border}`,
    flexWrap: 'wrap',
    gap: 8,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  title: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 700,
    color: COLORS.text.muted,
    letterSpacing: '0.12em',
  },
  equityVal: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: '-0.02em',
  },
  periodRow: {
    display: 'flex',
    gap: 3,
  },
  periodBtn: {
    background: 'transparent',
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 4,
    color: COLORS.text.muted,
    cursor: 'pointer',
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 600,
    padding: '3px 7px',
    letterSpacing: '0.06em',
  },
  periodBtnActive: {
    background: COLORS.bg.elevated,
    borderColor: COLORS.neon.cyan,
    color: COLORS.neon.cyan,
  },
  statsBar: {
    display: 'flex',
    gap: 0,
    borderBottom: `1px solid ${COLORS.bg.border}`,
    overflowX: 'auto',
  },
  statPill: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '6px 12px',
    borderRight: `1px solid ${COLORS.bg.border}`,
    minWidth: 72,
    flexShrink: 0,
  },
  statLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    color: COLORS.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginBottom: 2,
  },
  statValue: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '-0.01em',
  },
  ddLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    color: COLORS.loss.base,
    letterSpacing: '0.1em',
    padding: '4px 8px 0',
    opacity: 0.7,
  },
  legend: {
    display: 'flex',
    gap: 16,
    padding: '6px 14px 8px',
    borderTop: `1px solid ${COLORS.bg.border}`,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  legendLine: {
    height: 2,
  },
  legendLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.06em',
  },
  tooltip: {
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.divider}`,
    borderRadius: 6,
    padding: '8px 12px',
    minWidth: 160,
  },
  ttDate: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
    marginBottom: 6,
    letterSpacing: '0.04em',
  },
  ttRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: 16,
    marginBottom: 3,
  },
  ttLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
  },
  ttVal: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 700,
  },
  ttAnnotation: {
    fontFamily: '"Inter", sans-serif',
    fontSize: 10,
    color: COLORS.neon.amber,
    marginTop: 6,
    borderTop: `1px solid ${COLORS.bg.border}`,
    paddingTop: 4,
  },
  loading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 12,
    color: COLORS.text.muted,
    letterSpacing: '0.08em',
  },
};

export default memo(EquityCurve);
