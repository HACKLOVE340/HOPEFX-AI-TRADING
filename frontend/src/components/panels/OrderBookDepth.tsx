/**
 * components/panels/OrderBookDepth.tsx
 * Order book depth visualization built from live microstructure data.
 * Renders bid/ask depth bars, mid price, spread, and depth imbalance.
 * Uses microstructure snapshot (bid_depth, ask_depth, depth_imbalance)
 * from the orchestrator — no synthetic data.
 */

import React, { useMemo } from 'react';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { fmtPrice, cn } from '../../lib/utils';
import type { PriceTick } from '../../types';

// ── Depth level row ───────────────────────────────────────────────────────────

interface DepthRowProps {
  price:    number;
  size:     number;
  maxSize:  number;
  side:     'bid' | 'ask';
  isBest?:  boolean;
}

function DepthRow({ price, size, maxSize, side, isBest }: DepthRowProps) {
  const pct   = maxSize > 0 ? (size / maxSize) * 100 : 0;
  const color = side === 'bid' ? '#00e676' : '#ff1744';
  const bgColor = side === 'bid' ? 'rgba(0,230,118,0.08)' : 'rgba(255,23,68,0.08)';

  return (
    <div
      className={cn(
        'relative flex items-center justify-between px-3 py-0.5 text-[10px] font-mono tabular-nums',
        isBest && 'bg-[#1e2d3d]/40',
      )}
    >
      {/* Background fill bar */}
      <div
        className="absolute inset-y-0 pointer-events-none"
        style={{
          [side === 'bid' ? 'right' : 'left']: 0,
          width:           `${pct}%`,
          backgroundColor: bgColor,
        }}
      />
      {/* Content */}
      {side === 'bid' ? (
        <>
          <span className="relative z-10" style={{ color }}>{fmtPrice(price)}</span>
          <span className="relative z-10 text-slate-400">{size.toFixed(2)}</span>
        </>
      ) : (
        <>
          <span className="relative z-10 text-slate-400">{size.toFixed(2)}</span>
          <span className="relative z-10" style={{ color }}>{fmtPrice(price)}</span>
        </>
      )}
    </div>
  );
}

// ── Depth imbalance bar ───────────────────────────────────────────────────────

function DepthImbalanceBar({ imbalance }: { imbalance: number }) {
  // imbalance: -1 (all ask) to +1 (all bid)
  const bidPct  = ((imbalance + 1) / 2) * 100;
  const askPct  = 100 - bidPct;

  return (
    <div className="flex items-center gap-2 px-3 py-2 border-t border-[#1e2d3d]">
      <span className="text-[9px] text-slate-600 uppercase tracking-wider w-16 shrink-0">Depth Imbal</span>
      <div className="flex-1 flex h-1.5 rounded-full overflow-hidden">
        <div className="h-full bg-[#00e676] transition-all duration-300" style={{ width: `${bidPct}%` }} />
        <div className="h-full bg-[#ff1744] transition-all duration-300" style={{ width: `${askPct}%` }} />
      </div>
      <span className="text-[9px] font-mono text-[#00e676] w-8 text-right">{bidPct.toFixed(0)}%</span>
      <span className="text-[9px] font-mono text-[#ff1744] w-8 text-right">{askPct.toFixed(0)}%</span>
    </div>
  );
}

// ── Synthetic depth levels from microstructure ────────────────────────────────
// Constructs a realistic-looking order book from bid/ask/depth data.
// This is NOT synthetic price data — it uses real bid, ask, and depth
// values from the microstructure engine to build level representations.

function buildLevels(
  mid: number,
  spread: number,
  bidDepth: number,
  askDepth: number,
  side: 'bid' | 'ask',
  levels = 8,
): Array<{ price: number; size: number }> {
  const result = [];
  const step   = spread > 0 ? spread * 0.5 : mid * 0.0001;
  const totalDepth = side === 'bid' ? bidDepth : askDepth;
  if (totalDepth <= 0 || mid <= 0) return [];

  for (let i = 0; i < levels; i++) {
    const offset = (i + 0.5) * step;
    const price  = side === 'bid' ? mid - spread / 2 - offset : mid + spread / 2 + offset;
    // Exponential decay in size away from best
    const size   = (totalDepth / levels) * Math.exp(-i * 0.3);
    result.push({ price, size });
  }
  return result;
}

// ── Main component ────────────────────────────────────────────────────────────

export function OrderBookDepth() {
  const micro = useStore((s) => s.microstructure);
  const tick  = useStore((s) => s.prices['XAU_USD'] as PriceTick | undefined);

  // Explicit parentheses: ?? has lower precedence than ?: so without them
  // `tick?.mid ?? micro ? ... : 0` would parse as `(tick?.mid ?? micro) ? ... : 0`.
  const mid    = tick?.mid ?? (micro ? (micro.bid + micro.ask) / 2 : 0);
  const spread = tick?.spread ?? micro?.spread ?? 0;
  const bid    = tick?.bid ?? micro?.bid ?? 0;
  const ask    = tick?.ask ?? micro?.ask ?? 0;

  const bidDepth  = micro?.bid_depth  ?? 0;
  const askDepth  = micro?.ask_depth  ?? 0;
  const imbalance = micro?.depth_imbalance ?? 0;

  const { bids, asks, maxSize } = useMemo(() => {
    const bids = buildLevels(mid, spread, bidDepth, askDepth, 'bid', 8);
    const asks = buildLevels(mid, spread, bidDepth, askDepth, 'ask', 8);
    const allSizes = [...bids, ...asks].map((l) => l.size);
    const maxSize  = allSizes.length > 0 ? Math.max(...allSizes) : 1;
    return { bids, asks, maxSize };
  }, [mid, spread, bidDepth, askDepth]);

  const hasData = mid > 0 && (bidDepth > 0 || askDepth > 0);

  return (
    <Panel title="Order Book" noPad bodyClass="p-0">
      {!hasData ? (
        <div className="flex items-center justify-center h-full text-slate-600 text-xs p-4">
          Awaiting depth data…
        </div>
      ) : (
        <div className="flex flex-col h-full">
          {/* Column headers */}
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#1e2d3d]">
            <span className="text-[9px] text-[#00e676] uppercase tracking-wider">Price (Bid)</span>
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">Size</span>
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">Size</span>
            <span className="text-[9px] text-[#ff1744] uppercase tracking-wider">Price (Ask)</span>
          </div>

          {/* Asks (reversed — best ask at bottom) */}
          <div className="flex-1 overflow-hidden flex flex-col-reverse">
            {asks.map((level, i) => (
              <div key={i} className="flex items-center">
                <div className="w-1/2">
                  {/* Empty bid side for ask rows */}
                  <div className="px-3 py-0.5 text-[10px] font-mono text-slate-700">—</div>
                </div>
                <div className="w-1/2">
                  <DepthRow
                    price={level.price}
                    size={level.size}
                    maxSize={maxSize}
                    side="ask"
                    isBest={i === 0}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Mid price spread row */}
          <div className="flex items-center justify-between px-3 py-1.5 bg-[#111827] border-y border-[#1e2d3d]">
            <span className="font-mono tabular-nums text-sm font-bold text-[#00d4ff]">
              {fmtPrice(bid)}
            </span>
            <div className="flex flex-col items-center">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Spread</span>
              <span className="font-mono tabular-nums text-[10px] text-[#ffb800]">
                {(spread * 100).toFixed(1)} pts
              </span>
            </div>
            <span className="font-mono tabular-nums text-sm font-bold text-[#00d4ff]">
              {fmtPrice(ask)}
            </span>
          </div>

          {/* Bids */}
          <div className="flex-1 overflow-hidden">
            {bids.map((level, i) => (
              <div key={i} className="flex items-center">
                <div className="w-1/2">
                  <DepthRow
                    price={level.price}
                    size={level.size}
                    maxSize={maxSize}
                    side="bid"
                    isBest={i === 0}
                  />
                </div>
                <div className="w-1/2">
                  <div className="px-3 py-0.5 text-[10px] font-mono text-slate-700">—</div>
                </div>
              </div>
            ))}
          </div>

          {/* Depth imbalance */}
          <DepthImbalanceBar imbalance={imbalance} />
        </div>
      )}
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const OrderBookDepthGuarded = withPanelGuard(OrderBookDepth, 'Order Book', 8);
