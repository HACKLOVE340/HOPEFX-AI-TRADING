/**
 * components/panels/MicrostructurePanel.tsx
 * Microstructure panel: spread dynamics, OFI, Kyle's lambda, depth imbalance,
 * cumulative delta, buy/sell pressure bars, VWAP deviation.
 */

import React, { useEffect, useRef } from 'react';
import { createChart, AreaSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { fmtPrice, cn } from '../../lib/utils';

// ── Pressure gauge (SVG arc rings) ────────────────────────────────────────────

function PressureGauge({ buy, sell }: { buy: number; sell: number }) {
  const R = 28, CX = 40, CY = 40, SW = 7;
  const circ = 2 * Math.PI * R;
  // Each arc starts at 12-o'clock (offset = circ * 0.25) going clockwise.
  // Buy arc covers buy*circ; sell arc starts where buy arc ends.
  const buyLen  = circ * Math.min(Math.max(buy, 0), 1);
  const sellLen = circ * Math.min(Math.max(sell, 0), 1);
  const OFFSET  = circ * 0.25; // rotate start point to top

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="80" height="80" viewBox="0 0 80 80" style={{ overflow: 'visible' }}>
        {/* Background ring */}
        <circle cx={CX} cy={CY} r={R} fill="none" stroke="#1e2d3d" strokeWidth={SW} />
        {/* Sell arc (red) — drawn first so buy overlaps visually on top */}
        <circle
          cx={CX} cy={CY} r={R} fill="none"
          stroke="#ff1744" strokeWidth={SW}
          strokeDasharray={`${sellLen} ${circ}`}
          strokeDashoffset={OFFSET - buyLen}
          style={{ transform: 'rotate(-90deg)', transformOrigin: `${CX}px ${CY}px` }}
          strokeLinecap="round"
        />
        {/* Buy arc (green) */}
        <circle
          cx={CX} cy={CY} r={R} fill="none"
          stroke="#00e676" strokeWidth={SW}
          strokeDasharray={`${buyLen} ${circ}`}
          strokeDashoffset={OFFSET}
          style={{ transform: 'rotate(-90deg)', transformOrigin: `${CX}px ${CY}px` }}
          strokeLinecap="round"
        />
      </svg>
      <div className="flex items-center gap-3 text-[10px] font-mono">
        <span className="text-[#00e676]">B {(buy * 100).toFixed(0)}%</span>
        <span className="text-[#ff1744]">S {(sell * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

// ── Metric row ────────────────────────────────────────────────────────────────

function MicroRow({
  label,
  value,
  color,
  bar,
  barColor,
}: {
  label:     string;
  value:     string;
  color?:    string;
  bar?:      number;   // 0–1 for optional bar
  barColor?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#1e2d3d] last:border-0">
      <span className="text-[10px] text-slate-500 uppercase tracking-wider w-28 shrink-0">{label}</span>
      <div className="flex items-center gap-2 flex-1 justify-end">
        {bar != null && (
          <div className="w-16 h-1 bg-[#1e2d3d] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{ width: `${Math.min(Math.abs(bar) * 100, 100)}%`, backgroundColor: barColor ?? '#00d4ff' }}
            />
          </div>
        )}
        <span
          className="font-mono tabular-nums text-xs font-semibold w-20 text-right"
          style={color ? { color } : undefined}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

// ── Delta history mini-chart (LWC AreaSeries) ─────────────────────────────────

function DeltaChart({ history }: { history: number[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartApiRef  = useRef<IChartApi | null>(null);
  const seriesRef    = useRef<ISeriesApi<'Area'> | null>(null);
  const rafRef       = useRef<number>(0);

  const isPos = (history[history.length - 1] ?? 0) >= 0;
  const color  = isPos ? '#00e676' : '#ff1744';

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout:    { background: { color: 'transparent' }, textColor: '#64748b' },
      grid:      { vertLines: { color: 'transparent' }, horzLines: { color: 'transparent' } },
      rightPriceScale: { visible: false },
      leftPriceScale:  { visible: false },
      timeScale: { visible: false },
      crosshair: { vertLine: { visible: false }, horzLine: { visible: false } },
      handleScroll: false,
      handleScale:  false,
      height: 56,
      width:  containerRef.current.clientWidth || 200,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor:   color,
      topColor:    `${color}4d`,
      bottomColor: `${color}00`,
      lineWidth:   2,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chartApiRef.current = chart;
    seriesRef.current   = series;

    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartApiRef.current) {
          chartApiRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
    });
    ro.observe(containerRef.current);
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartApiRef.current = null;
      seriesRef.current   = null;
    };
  }, [color]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!seriesRef.current || history.length < 2) return;
    // Use synthetic timestamps (1-second increments from epoch) for indexed data.
    const base = 1_000_000_000 as UTCTimestamp;
    seriesRef.current.setData(
      history.map((v, i) => ({ time: (base + i) as UTCTimestamp, value: v })),
    );
    chartApiRef.current?.timeScale().fitContent();
  }, [history]);

  if (history.length < 2) return null;
  return <div ref={containerRef} style={{ width: '100%', height: 56 }} />;
}

// ── Main component ────────────────────────────────────────────────────────────

export function MicrostructurePanel() {
  const micro    = useStore((s) => s.microstructure);
  const history  = useStore((s) => s.priceHistory['XAU_USD'] ?? []);
  const deltaHist = history.slice(-40).map((t) => t.mid);

  if (!micro) {
    return (
      <Panel title="Microstructure">
        <div className="flex items-center justify-center h-full text-slate-600 text-xs">
          Awaiting microstructure data…
        </div>
      </Panel>
    );
  }

  const ofi      = micro.order_flow_imbalance;
  const ofiColor = ofi > 0.1 ? '#00e676' : ofi < -0.1 ? '#ff1744' : '#ffb800';
  const delta    = micro.volume_delta;
  const cumDelta = micro.cumulative_delta;
  const spread   = micro.spread;
  const spreadPct = micro.spread_pct;
  const vwap     = micro.vwap;
  const mid      = (micro.bid + micro.ask) / 2;
  const vwapDev  = vwap > 0 ? ((mid - vwap) / vwap) * 100 : 0;

  return (
    <Panel title="Microstructure" noPad bodyClass="p-0">
      <div className="flex flex-col h-full overflow-y-auto scrollbar-terminal">

        {/* Pressure gauges + spread */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e2d3d]">
          <PressureGauge buy={micro.buy_pressure} sell={micro.sell_pressure} />

          <div className="flex flex-col gap-2 flex-1 ml-4">
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Spread</span>
              <span className="font-mono tabular-nums text-xs text-[#ffb800]">
                {spread.toFixed(4)} ({(spreadPct * 100).toFixed(3)}%)
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">VWAP</span>
              <span className="font-mono tabular-nums text-xs text-slate-300">
                {fmtPrice(vwap)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">VWAP Dev</span>
              <span
                className="font-mono tabular-nums text-xs"
                style={{ color: vwapDev >= 0 ? '#00e676' : '#ff1744' }}
              >
                {vwapDev >= 0 ? '+' : ''}{vwapDev.toFixed(3)}%
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Ticks</span>
              <span className="font-mono tabular-nums text-xs text-slate-400">
                {micro.tick_count.toLocaleString()}
              </span>
            </div>
          </div>
        </div>

        {/* Cumulative delta chart */}
        <div className="px-4 pt-2 pb-1 border-b border-[#1e2d3d]">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">Cumulative Delta</span>
            <span
              className={cn(
                'font-mono tabular-nums text-xs font-semibold',
                cumDelta >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
              )}
            >
              {cumDelta >= 0 ? '+' : ''}{cumDelta.toFixed(0)}
            </span>
          </div>
          <DeltaChart history={deltaHist} />
        </div>

        {/* Metrics grid */}
        <div className="px-4 py-2">
          <MicroRow
            label="OFI"
            value={`${(ofi * 100).toFixed(2)}%`}
            color={ofiColor}
            bar={Math.abs(ofi)}
            barColor={ofiColor}
          />
          <MicroRow
            label="Vol Delta"
            value={`${delta >= 0 ? '+' : ''}${delta.toFixed(0)}`}
            color={delta >= 0 ? '#00e676' : '#ff1744'}
          />
          <MicroRow
            label="Trade Press"
            value={micro.trade_pressure.toFixed(4)}
            color={micro.trade_pressure >= 0 ? '#00e676' : '#ff1744'}
            bar={Math.min(Math.abs(micro.trade_pressure), 1)}
            barColor={micro.trade_pressure >= 0 ? '#00e676' : '#ff1744'}
          />
          <MicroRow
            label="Depth Imbal"
            value={micro.depth_imbalance != null ? `${(micro.depth_imbalance * 100).toFixed(1)}%` : '—'}
            color={(micro.depth_imbalance ?? 0) >= 0 ? '#00e676' : '#ff1744'}
            bar={micro.depth_imbalance != null ? Math.abs(micro.depth_imbalance) : undefined}
            barColor={(micro.depth_imbalance ?? 0) >= 0 ? '#00e676' : '#ff1744'}
          />
          <MicroRow
            label="Bid Depth"
            value={micro.bid_depth?.toFixed(0) ?? '—'}
            color="#00e676"
          />
          <MicroRow
            label="Ask Depth"
            value={micro.ask_depth?.toFixed(0) ?? '—'}
            color="#ff1744"
          />
        </div>
      </div>
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const MicrostructurePanelGuarded = withPanelGuard(MicrostructurePanel, 'Microstructure', 6);
