/**
 * components/panels/MicrostructurePanel.tsx
 * Microstructure panel: spread dynamics, OFI, Kyle's lambda, depth imbalance,
 * cumulative delta, buy/sell pressure bars, VWAP deviation.
 */

import React from 'react';
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { fmtPrice, cn } from '../../lib/utils';

// ── Pressure gauge (radial) ───────────────────────────────────────────────────

function PressureGauge({ buy, sell }: { buy: number; sell: number }) {
  const data = [
    { name: 'Buy',  value: buy  * 100, fill: '#00e676' },
    { name: 'Sell', value: sell * 100, fill: '#ff1744' },
  ];

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="w-20 h-20">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            cx="50%" cy="50%"
            innerRadius="55%" outerRadius="90%"
            startAngle={90} endAngle={-270}
            data={data}
            barSize={6}
          >
            <RadialBar dataKey="value" cornerRadius={3} background={{ fill: '#1e2d3d' }} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
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

// ── Delta history mini-chart ──────────────────────────────────────────────────

function DeltaChart({ history }: { history: number[] }) {
  if (history.length < 2) return null;
  const data = history.map((v, i) => ({ i, v }));
  const isPos = (history[history.length - 1] ?? 0) >= 0;

  return (
    <div className="h-14">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="deltaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={isPos ? '#00e676' : '#ff1744'} stopOpacity={0.3} />
              <stop offset="95%" stopColor={isPos ? '#00e676' : '#ff1744'} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <YAxis hide />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="bg-[#111827] border border-[#1e2d3d] rounded px-2 py-1 text-[10px] font-mono">
                  <span style={{ color: isPos ? '#00e676' : '#ff1744' }}>
                    Δ {(payload[0].value as number).toFixed(0)}
                  </span>
                </div>
              ) : null
            }
          />
          <Area
            type="monotone"
            dataKey="v"
            stroke={isPos ? '#00e676' : '#ff1744'}
            strokeWidth={1.5}
            fill="url(#deltaGrad)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
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
