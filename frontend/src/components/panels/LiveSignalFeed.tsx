/**
 * components/panels/LiveSignalFeed.tsx
 * Live signal feed from the inference engine.
 * Shows: direction, confidence, model, entry/SL/TP, risk:reward, status.
 */

import React from 'react';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { Badge } from '../ui/Badge';
import { ConfidenceBar } from '../ui/ConfidenceBar';
import { fmtPrice, fmtRelative, confColor, dirColor, cn } from '../../lib/utils';
import type { Signal } from '../../types';

// ── Direction arrow ───────────────────────────────────────────────────────────

function DirectionArrow({ direction }: { direction: string }) {
  if (direction === 'long')  return <span className="text-[#00e676] text-base leading-none">▲</span>;
  if (direction === 'short') return <span className="text-[#ff1744] text-base leading-none">▼</span>;
  return <span className="text-slate-500 text-base leading-none">◆</span>;
}

// ── Signal card ───────────────────────────────────────────────────────────────

function SignalCard({ signal }: { signal: Signal }) {
  const dirVariant =
    signal.direction === 'long'  ? 'bull' :
    signal.direction === 'short' ? 'bear' : 'neutral';

  const statusVariant =
    signal.status === 'active'    ? 'active' :
    signal.status === 'triggered' ? 'bull'   : 'expired';

  const rr = signal.risk_reward ??
    (signal.entry_price > 0 && signal.stop_loss > 0 && signal.take_profit > 0
      ? Math.abs(signal.take_profit - signal.entry_price) /
        Math.abs(signal.entry_price - signal.stop_loss)
      : null);

  const isExpired = signal.status === 'expired' || signal.status === 'cancelled';

  return (
    <div
      className={cn(
        'flex flex-col gap-2 p-3 border-b border-[#1e2d3d] last:border-0 transition-opacity',
        isExpired && 'opacity-40',
      )}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DirectionArrow direction={signal.direction} />
          <span className="text-[11px] font-semibold text-slate-200 tracking-wider">
            {signal.symbol.replace('_', '/')}
          </span>
          <Badge variant={dirVariant}>{signal.direction}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={statusVariant} dot>{signal.status}</Badge>
          <span className="text-[9px] text-slate-600 font-mono">{fmtRelative(signal.generated_at)}</span>
        </div>
      </div>

      {/* Confidence bar */}
      <div className="flex items-center gap-2">
        <span className="text-[9px] text-slate-600 uppercase tracking-wider w-16 shrink-0">Confidence</span>
        <ConfidenceBar value={signal.confidence} height="sm" className="flex-1" />
        <span
          className="font-mono tabular-nums text-[11px] font-bold w-10 text-right"
          style={{ color: confColor(signal.confidence) }}
        >
          {(signal.confidence * 100).toFixed(0)}%
        </span>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] text-slate-600 uppercase tracking-wider">Entry</span>
          <span className="font-mono tabular-nums text-[11px] text-slate-200">
            {fmtPrice(signal.entry_price)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] text-[#ff1744] uppercase tracking-wider">Stop Loss</span>
          <span className="font-mono tabular-nums text-[11px] text-[#ff1744]">
            {fmtPrice(signal.stop_loss)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] text-[#00e676] uppercase tracking-wider">Take Profit</span>
          <span className="font-mono tabular-nums text-[11px] text-[#00e676]">
            {fmtPrice(signal.take_profit)}
          </span>
        </div>
      </div>

      {/* Footer: model + R:R */}
      <div className="flex items-center justify-between">
        <span className="text-[9px] text-slate-600 font-mono truncate max-w-[120px]">
          {signal.model}
        </span>
        {rr != null && (
          <span
            className={cn(
              'text-[10px] font-mono font-semibold',
              rr >= 2 ? 'text-[#00e676]' : rr >= 1 ? 'text-[#ffb800]' : 'text-[#ff3b5c]',
            )}
          >
            R:R {rr.toFixed(1)}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Open positions strip ──────────────────────────────────────────────────────

function PositionRow({ pos }: { pos: import('../../types').Position }) {
  const pnlColor = pos.unrealized_pnl >= 0 ? '#00e676' : '#ff1744';
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-[#1e2d3d] last:border-0">
      <div className="flex items-center gap-2">
        <DirectionArrow direction={pos.side} />
        <span className="text-[11px] text-slate-200 font-mono">{pos.symbol.replace('_', '/')}</span>
        <span className="text-[10px] text-slate-500 font-mono">{pos.size}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-slate-500 font-mono">@ {fmtPrice(pos.entry_price)}</span>
        <span
          className="font-mono tabular-nums text-[11px] font-semibold"
          style={{ color: pnlColor }}
        >
          {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function LiveSignalFeed() {
  const signals   = useStore((s) => s.signals);
  const positions = useStore((s) => s.positions);

  const activeSignals  = signals.filter((s) => s.status === 'active');
  const recentSignals  = signals.filter((s) => s.status !== 'active').slice(0, 5);
  const openPositions  = positions.filter((p) => p.unrealized_pnl !== undefined);

  const headerRight = (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-mono text-[#00e676]">{activeSignals.length} active</span>
      <span className="text-[10px] font-mono text-slate-600">|</span>
      <span className="text-[10px] font-mono text-slate-400">{openPositions.length} positions</span>
    </div>
  );

  return (
    <Panel title="Signals & Positions" headerRight={headerRight} noPad bodyClass="p-0">
      <div className="flex flex-col h-full overflow-y-auto scrollbar-terminal">

        {/* Open positions */}
        {openPositions.length > 0 && (
          <div className="border-b border-[#1e2d3d]">
            <div className="px-3 py-1.5 bg-[#111827]">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Open Positions</span>
            </div>
            {openPositions.map((p) => (
              <PositionRow key={p.id} pos={p} />
            ))}
          </div>
        )}

        {/* Active signals */}
        {activeSignals.length > 0 && (
          <div className="border-b border-[#1e2d3d]">
            <div className="px-3 py-1.5 bg-[#111827]">
              <span className="text-[9px] text-[#00e676] uppercase tracking-wider">Active Signals</span>
            </div>
            {activeSignals.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        )}

        {/* Recent signals */}
        {recentSignals.length > 0 && (
          <div>
            <div className="px-3 py-1.5 bg-[#111827]">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Recent</span>
            </div>
            {recentSignals.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {signals.length === 0 && positions.length === 0 && (
          <div className="flex items-center justify-center h-24 text-slate-600 text-xs">
            Awaiting signals from inference engine…
          </div>
        )}
      </div>
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const LiveSignalFeedGuarded = withPanelGuard(LiveSignalFeed, 'Signal Feed', 5);
