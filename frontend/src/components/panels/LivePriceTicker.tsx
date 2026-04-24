/**
 * components/panels/LivePriceTicker.tsx
 * Top-of-dashboard XAUUSD live price bar.
 * Shows: bid/ask, spread, mid, change%, volume delta, OFI, tick quality.
 * Flashes green/red on price direction change.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import { fmtPrice, fmtPct, fmtSpread, cn } from '../../lib/utils';
import { StatusDot } from '../ui/StatusDot';
import { Sparkline } from '../ui/Sparkline';
import type { PriceTick } from '../../types';

// ── Single symbol ticker cell ─────────────────────────────────────────────────

interface TickerCellProps {
  symbol:  string;
  tick:    PriceTick | undefined;
  history: PriceTick[];
  active?: boolean;
}

function TickerCell({ symbol, tick, history, active }: TickerCellProps) {
  const prevMid  = useRef<number | null>(null);
  const [flash, setFlash] = useState<'bull' | 'bear' | null>(null);

  useEffect(() => {
    if (!tick) return;
    if (prevMid.current !== null) {
      const dir = tick.mid > prevMid.current ? 'bull' : tick.mid < prevMid.current ? 'bear' : null;
      if (dir) {
        setFlash(dir);
        const t = setTimeout(() => setFlash(null), 400);
        return () => clearTimeout(t);
      }
    }
    prevMid.current = tick.mid;
  }, [tick?.mid]);

  const sparkData = history.slice(-40).map((t) => t.mid);
  const change    = tick?.change_pct ?? 0;
  const isUp      = change >= 0;

  return (
    <div
      className={cn(
        'flex items-center gap-4 px-5 py-3 border-r border-[#1e2d3d] transition-colors duration-300',
        active && 'bg-[#111827]',
        flash === 'bull' && 'bg-[#00e676]/5',
        flash === 'bear' && 'bg-[#ff1744]/5',
      )}
    >
      {/* Symbol */}
      <div className="flex flex-col gap-0.5 min-w-[72px]">
        <span className="text-[11px] font-semibold text-slate-200 tracking-wider">{symbol}</span>
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">
          {tick?.quality ?? '—'}
        </span>
      </div>

      {/* Bid / Ask */}
      <div className="flex flex-col gap-0.5 min-w-[120px]">
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] text-slate-600 w-5">BID</span>
          <span
            className={cn(
              'font-mono tabular-nums text-sm font-semibold transition-colors duration-200',
              flash === 'bear' ? 'text-[#ff1744]' : 'text-slate-200',
            )}
          >
            {tick ? fmtPrice(tick.bid) : '—'}
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] text-slate-600 w-5">ASK</span>
          <span
            className={cn(
              'font-mono tabular-nums text-sm font-semibold transition-colors duration-200',
              flash === 'bull' ? 'text-[#00e676]' : 'text-slate-200',
            )}
          >
            {tick ? fmtPrice(tick.ask) : '—'}
          </span>
        </div>
      </div>

      {/* Mid + change */}
      <div className="flex flex-col gap-0.5 min-w-[100px]">
        <span className="font-mono tabular-nums text-base font-bold text-[#00d4ff]">
          {tick ? fmtPrice(tick.mid) : '—'}
        </span>
        <span
          className={cn(
            'text-[11px] font-mono tabular-nums font-semibold',
            isUp ? 'text-[#00e676]' : 'text-[#ff1744]',
          )}
        >
          {tick ? fmtPct(change / 100) : '—'}
        </span>
      </div>

      {/* Spread */}
      <div className="flex flex-col gap-0.5 min-w-[72px]">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">Spread</span>
        <span className="font-mono tabular-nums text-xs text-[#ffb800]">
          {tick ? fmtSpread(tick.spread) : '—'}
        </span>
      </div>

      {/* Sparkline */}
      <div className="hidden sm:block">
        <Sparkline data={sparkData} width={72} height={24} />
      </div>
    </div>
  );
}

// ── Microstructure strip ──────────────────────────────────────────────────────

function MicroStrip() {
  const micro = useStore((s) => s.microstructure);

  if (!micro) return null;

  const ofi      = micro.order_flow_imbalance;
  const delta    = micro.volume_delta;
  const pressure = micro.buy_pressure;
  const ofiColor = ofi > 0.1 ? '#00e676' : ofi < -0.1 ? '#ff1744' : '#ffb800';

  return (
    <div className="flex items-center gap-6 px-5 py-2 border-t border-[#1e2d3d] bg-[#080c14]">
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">OFI</span>
        <span className="font-mono tabular-nums text-[11px] font-semibold" style={{ color: ofiColor }}>
          {(ofi * 100).toFixed(1)}%
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">Δ Vol</span>
        <span
          className={cn(
            'font-mono tabular-nums text-[11px] font-semibold',
            delta >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
          )}
        >
          {delta >= 0 ? '+' : ''}{delta.toFixed(0)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">Buy Press</span>
        <div className="flex items-center gap-1">
          <div className="w-16 h-1 bg-[#1e2d3d] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width:           `${pressure * 100}%`,
                backgroundColor: pressure > 0.6 ? '#00e676' : pressure < 0.4 ? '#ff1744' : '#ffb800',
              }}
            />
          </div>
          <span className="font-mono tabular-nums text-[10px] text-slate-400">
            {(pressure * 100).toFixed(0)}%
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">VWAP</span>
        <span className="font-mono tabular-nums text-[11px] text-slate-300">
          {fmtPrice(micro.vwap)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-widest">Ticks</span>
        <span className="font-mono tabular-nums text-[11px] text-slate-400">
          {micro.tick_count.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

// ── Main ticker bar ───────────────────────────────────────────────────────────

// Slash format matches the WebSocket price_tick symbol keys sent by ws_live.py.
const SYMBOLS = ['XAU/USD', 'XAG/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY'];

export function LivePriceTicker() {
  const prices    = useStore((s) => s.prices);
  const histories = useStore((s) => s.priceHistory);
  const wsStatus  = useStore((s) => s.wsStatus);
  const quality   = useStore((s) => s.orchestratorHealth?.quality_score);

  return (
    <div className="bg-[#0d1421] border-b border-[#1e2d3d] shrink-0">
      {/* Top bar: symbols */}
      <div className="flex items-stretch overflow-x-auto scrollbar-terminal">
        {SYMBOLS.map((sym) => (
          <TickerCell
            key={sym}
            symbol={sym}
            tick={prices[sym]}
            history={histories[sym] ?? []}
            active={sym === 'XAU/USD'}
          />
        ))}

        {/* Right: connection status + quality */}
        <div className="ml-auto flex items-center gap-4 px-5 shrink-0">
          {quality != null && (
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[9px] text-slate-600 uppercase tracking-widest">Data Quality</span>
              <span
                className="font-mono tabular-nums text-xs font-semibold"
                style={{ color: quality > 0.8 ? '#00e676' : quality > 0.5 ? '#ffb800' : '#ff3b5c' }}
              >
                {(quality * 100).toFixed(0)}%
              </span>
            </div>
          )}
          <StatusDot status={wsStatus} label={wsStatus} size="md" />
        </div>
      </div>

      {/* Microstructure strip */}
      <MicroStrip />
    </div>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const LivePriceTickerGuarded = withPanelGuard(LivePriceTicker, 'Price Ticker', 2);
