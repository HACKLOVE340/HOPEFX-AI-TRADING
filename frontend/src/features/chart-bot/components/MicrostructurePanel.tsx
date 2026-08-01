/**
 * MicrostructurePanel.tsx
 * Live microstructure panel: spread dynamics, order flow heatmap,
 * trade pressure gauge, VWAP/TWAP, and market impact display.
 */

import React, { useMemo, memo, useEffect, useRef } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import { useMicrostructure } from '../hooks/useChartData';
import { COLORS } from '../utils/design-tokens';
import { formatPrice, formatSpread, clamp, normalise } from '../utils/formatters';
import type { VolumeDeltaBar } from '../types';

// ─── Spread Gauge ─────────────────────────────────────────────────────────────

const SpreadGauge = memo(({ spread, spreadPct, history }: { spread: number; spreadPct: number; history: number[] }) => {
  const max = Math.max(...history, spread, 0.01);
  const pct = clamp(spread / max, 0, 1);
  const color = pct < 0.33 ? COLORS.profit.base : pct < 0.66 ? COLORS.neon.gold : COLORS.loss.base;

  return (
    <div style={s.gaugeCard}>
      <div style={s.gaugeTitle}>SPREAD</div>
      <div style={{ ...s.gaugeValue, color }}>{formatSpread(spread)}</div>
      <div style={s.gaugePct}>{(spreadPct * 100).toFixed(3)}%</div>
      {/* Mini sparkline */}
      <svg width="100%" height={28} style={{ marginTop: 4 }}>
        {history.slice(-30).map((v, i, arr) => {
          const x = (i / (arr.length - 1)) * 100;
          const y = 28 - clamp(v / max, 0, 1) * 24;
          return i === 0 ? null : (
            <line
              key={i}
              x1={`${((i - 1) / (arr.length - 1)) * 100}%`}
              y1={28 - clamp((arr[i - 1] ?? v) / max, 0, 1) * 24}
              x2={`${x}%`}
              y2={y}
              stroke={color}
              strokeWidth={1.5}
              opacity={0.7}
            />
          );
        })}
      </svg>
    </div>
  );
});
SpreadGauge.displayName = 'SpreadGauge';

// ─── Order Flow Imbalance Bar ─────────────────────────────────────────────────

const OFIBar = memo(({ imbalance }: { imbalance: number }) => {
  // imbalance: -1 (full sell) to +1 (full buy)
  const buyPct  = clamp((imbalance + 1) / 2, 0, 1) * 100;
  const sellPct = 100 - buyPct;
  const label   = imbalance > 0.2 ? 'BUY PRESSURE' : imbalance < -0.2 ? 'SELL PRESSURE' : 'BALANCED';
  const labelColor = imbalance > 0.2 ? COLORS.profit.base : imbalance < -0.2 ? COLORS.loss.base : COLORS.text.muted;

  return (
    <div style={s.ofiCard}>
      <div style={s.gaugeTitle}>ORDER FLOW IMBALANCE</div>
      <div style={{ ...s.ofiLabel, color: labelColor }}>{label}</div>
      <div style={s.ofiBar}>
        <div style={{ ...s.ofiBuy,  width: `${buyPct}%`  }} />
        <div style={{ ...s.ofiSell, width: `${sellPct}%` }} />
      </div>
      <div style={s.ofiLegend}>
        <span style={{ color: COLORS.profit.base, fontFamily: '"JetBrains Mono", monospace', fontSize: 10 }}>
          BUY {buyPct.toFixed(1)}%
        </span>
        <span style={{ color: COLORS.loss.base, fontFamily: '"JetBrains Mono", monospace', fontSize: 10 }}>
          SELL {sellPct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
});
OFIBar.displayName = 'OFIBar';

// ─── Trade Pressure Gauge (arc) ───────────────────────────────────────────────

const TradePressureGauge = memo(({ pressure }: { pressure: number }) => {
  // pressure: 0–100
  const angle = (pressure / 100) * 180 - 90; // -90 to +90 degrees
  const color = pressure > 70 ? COLORS.profit.base
              : pressure < 30 ? COLORS.loss.base
              : COLORS.neon.gold;

  // Arc path
  const r = 44;
  const cx = 60, cy = 60;
  const startAngle = -180;
  const endAngle   = 0;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const arcPath = (start: number, end: number, radius: number) => {
    const s = { x: cx + radius * Math.cos(toRad(start)), y: cy + radius * Math.sin(toRad(start)) };
    const e = { x: cx + radius * Math.cos(toRad(end)),   y: cy + radius * Math.sin(toRad(end))   };
    const large = end - start > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
  };

  const needleAngle = startAngle + (pressure / 100) * 180;
  const nx = cx + (r - 8) * Math.cos(toRad(needleAngle));
  const ny = cy + (r - 8) * Math.sin(toRad(needleAngle));

  return (
    <div style={s.gaugeCard}>
      <div style={s.gaugeTitle}>TRADE PRESSURE</div>
      <svg width={120} height={70} style={{ display: 'block', margin: '0 auto' }}>
        {/* Background arc */}
        <path d={arcPath(startAngle, endAngle, r)} fill="none" stroke={COLORS.bg.elevated} strokeWidth={8} strokeLinecap="round" />
        {/* Colored arc */}
        <path d={arcPath(startAngle, needleAngle, r)} fill="none" stroke={color} strokeWidth={8} strokeLinecap="round" opacity={0.9} />
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={2} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={4} fill={color} />
        {/* Value */}
        <text x={cx} y={cy + 16} textAnchor="middle" fill={color} fontSize={14} fontFamily='"JetBrains Mono", monospace' fontWeight={700}>
          {pressure.toFixed(0)}
        </text>
      </svg>
      <div style={{ textAlign: 'center', fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, letterSpacing: '0.08em' }}>
        {pressure > 70 ? 'BULLISH' : pressure < 30 ? 'BEARISH' : 'NEUTRAL'}
      </div>
    </div>
  );
});
TradePressureGauge.displayName = 'TradePressureGauge';

// ─── Volume Delta Heatmap ─────────────────────────────────────────────────────

const VolumeDeltaHeatmap = memo(({ bars }: { bars: VolumeDeltaBar[] }) => {
  const recent = bars.slice(-40);
  // Bind once: `recent.length > 0` does not narrow recent[n] (audit #38), and
  // this was indexed three times in the same JSX expression.
  const latestCumDelta = recent[recent.length - 1]?.cumDelta;
  if (!recent.length) return (
    <div style={s.heatmapCard}>
      <div style={s.gaugeTitle}>VOLUME DELTA</div>
      <div style={s.noData}>Awaiting data…</div>
    </div>
  );

  const maxDelta = Math.max(...recent.map((b) => Math.abs(b.delta)), 1);

  return (
    <div style={s.heatmapCard}>
      <div style={s.gaugeTitle}>VOLUME DELTA</div>
      <div style={s.heatmapGrid}>
        {recent.map((bar, i) => {
          const intensity = clamp(Math.abs(bar.delta) / maxDelta, 0, 1);
          const isBuy = bar.delta >= 0;
          const bg = isBuy
            ? `rgba(0,255,136,${0.08 + intensity * 0.5})`
            : `rgba(255,51,102,${0.08 + intensity * 0.5})`;
          return (
            <div
              key={i}
              title={`Δ${bar.delta > 0 ? '+' : ''}${bar.delta.toFixed(0)}`}
              style={{
                ...s.heatCell,
                background: bg,
                height: `${8 + intensity * 24}px`,
                alignSelf: 'flex-end',
              }}
            />
          );
        })}
      </div>
      {/* Cumulative delta */}
      {latestCumDelta !== undefined && (
        <div style={s.cumDelta}>
          <span style={s.gaugeTitle}>CUM Δ</span>
          <span style={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 12,
            fontWeight: 700,
            color: latestCumDelta >= 0 ? COLORS.profit.base : COLORS.loss.base,
          }}>
            {latestCumDelta >= 0 ? '+' : ''}{latestCumDelta.toFixed(0)}
          </span>
        </div>
      )}
    </div>
  );
});
VolumeDeltaHeatmap.displayName = 'VolumeDeltaHeatmap';

// ─── VWAP / TWAP Row ──────────────────────────────────────────────────────────

const VWAPRow = memo(({ vwap, twap, mid }: { vwap: number; twap: number; mid: number }) => {
  const vwapDiff = mid - vwap;
  const twapDiff = mid - twap;
  return (
    <div style={s.vwapCard}>
      <div style={s.vwapRow}>
        <span style={s.gaugeTitle}>VWAP</span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 12, fontWeight: 700, color: COLORS.neon.cyan }}>
          {formatPrice(vwap)}
        </span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: vwapDiff >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
          {vwapDiff >= 0 ? '+' : ''}{formatPrice(vwapDiff)}
        </span>
      </div>
      <div style={s.vwapRow}>
        <span style={s.gaugeTitle}>TWAP</span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 12, fontWeight: 700, color: COLORS.neon.purple }}>
          {formatPrice(twap)}
        </span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: twapDiff >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
          {twapDiff >= 0 ? '+' : ''}{formatPrice(twapDiff)}
        </span>
      </div>
    </div>
  );
});
VWAPRow.displayName = 'VWAPRow';

// ─── Main Component ───────────────────────────────────────────────────────────

const MicrostructurePanel: React.FC = () => {
  const symbol      = useChartBotStore((s) => s.symbol);
  const liveTick    = useChartBotStore((s) => s.liveTick);
  const microStore  = useChartBotStore((s) => s.microstructure);
  const volumeDelta = useChartBotStore((s) => s.volumeDelta);

  const { data: microFetched } = useMicrostructure(symbol);
  const micro = microStore ?? microFetched;

  // Spread history for sparkline
  const spreadHistory = useRef<number[]>([]);
  useEffect(() => {
    if (micro?.spread) {
      spreadHistory.current = [...spreadHistory.current, micro.spread].slice(-60);
    }
  }, [micro?.spread]);

  const mid = liveTick?.mid ?? micro?.vwap ?? 0;

  return (
    <div style={s.wrapper}>
      <div style={s.header}>
        <span style={s.title}>MICROSTRUCTURE</span>
        <div style={s.tickDir}>
          {micro?.tickDirection === 'up'   && <span style={{ color: COLORS.profit.base, fontSize: 14 }}>▲</span>}
          {micro?.tickDirection === 'down' && <span style={{ color: COLORS.loss.base,   fontSize: 14 }}>▼</span>}
          {micro?.tickDirection === 'flat' && <span style={{ color: COLORS.text.muted,  fontSize: 14 }}>—</span>}
          <span style={s.tickLabel}>{micro?.tickDirection?.toUpperCase() ?? '—'}</span>
        </div>
      </div>

      <div style={s.grid}>
        {/* Spread */}
        <SpreadGauge
          spread={micro?.spread ?? 0}
          spreadPct={micro?.spreadPct ?? 0}
          history={spreadHistory.current}
        />

        {/* Trade pressure */}
        <TradePressureGauge pressure={micro?.tradePressure ?? 50} />

        {/* OFI */}
        <div style={{ gridColumn: '1 / -1' }}>
          <OFIBar imbalance={micro?.orderFlowImbalance ?? 0} />
        </div>

        {/* Volume delta heatmap */}
        <div style={{ gridColumn: '1 / -1' }}>
          <VolumeDeltaHeatmap bars={volumeDelta} />
        </div>

        {/* VWAP / TWAP */}
        {micro && (
          <div style={{ gridColumn: '1 / -1' }}>
            <VWAPRow vwap={micro.vwap} twap={micro.twap} mid={mid} />
          </div>
        )}

        {/* Market impact */}
        {micro && (
          <div style={{ gridColumn: '1 / -1', ...s.impactRow }}>
            <span style={s.gaugeTitle}>MARKET IMPACT</span>
            <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 11, color: COLORS.neon.amber }}>
              {(micro.marketImpact * 100).toFixed(3)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
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
  },
  title: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 700,
    color: COLORS.text.muted,
    letterSpacing: '0.12em',
  },
  tickDir: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  tickLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
    letterSpacing: '0.08em',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 1,
    background: COLORS.bg.border,
  },
  gaugeCard: {
    background: COLORS.bg.surface,
    padding: '10px 12px',
  },
  gaugeTitle: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    color: COLORS.text.muted,
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    marginBottom: 4,
    display: 'block',
  },
  gaugeValue: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 16,
    fontWeight: 700,
    letterSpacing: '-0.01em',
  },
  gaugePct: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
    marginTop: 2,
  },
  ofiCard: {
    background: COLORS.bg.surface,
    padding: '10px 12px',
  },
  ofiLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.08em',
    marginBottom: 6,
  },
  ofiBar: {
    display: 'flex',
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    background: COLORS.bg.elevated,
  },
  ofiBuy: {
    background: COLORS.profit.base,
    transition: 'width 300ms ease',
  },
  ofiSell: {
    background: COLORS.loss.base,
    transition: 'width 300ms ease',
  },
  ofiLegend: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: 4,
  },
  heatmapCard: {
    background: COLORS.bg.surface,
    padding: '10px 12px',
  },
  heatmapGrid: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: 2,
    height: 40,
    marginTop: 6,
  },
  heatCell: {
    flex: 1,
    borderRadius: 2,
    minWidth: 4,
    transition: 'height 200ms ease, background 200ms ease',
  },
  cumDelta: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 6,
  },
  vwapCard: {
    background: COLORS.bg.surface,
    padding: '8px 12px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
  },
  vwapRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  impactRow: {
    background: COLORS.bg.surface,
    padding: '8px 12px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  noData: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
    padding: '12px 0',
    textAlign: 'center' as const,
  },
};

export default memo(MicrostructurePanel);
