/**
 * components/panels/PositionsTable.tsx
 * Standalone positions table with per-row close button and close-all action.
 *
 * Wires to:
 *   GET  /api/trading/positions        (via usePositions TanStack Query hook)
 *   DELETE /api/trading/positions/{id} (close single)
 *   DELETE /api/trading/positions      (close all)
 *
 * Uses an inline confirmation dialog instead of window.confirm so the UI
 * remains non-blocking and works correctly in sandboxed iframes.
 */

import React, { useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useStore } from '../../store';
import { tradingApi } from '../../hooks/useApi';
import { Panel } from '../ui/Panel';
import { PanelSkeleton } from '../ui/Skeleton';
import { withPanelGuard } from '../ui/withPanelGuard';
import { fmtPrice, fmtPnl, fmtDateTime, cn } from '../../lib/utils';
import type { Position } from '../../types';

// ── Inline confirmation dialog ────────────────────────────────────────────────

function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="mx-4 mt-3 px-3 py-2.5 rounded bg-[#1e2d3d] border border-[#ff1744]/30 flex items-center justify-between gap-3">
      <span className="text-[12px] text-slate-300">{message}</span>
      <div className="flex gap-2 shrink-0">
        <button
          onClick={onCancel}
          className="px-2.5 py-1 rounded text-[11px] font-semibold border border-[#334155] text-slate-400 hover:text-slate-200 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className="px-2.5 py-1 rounded text-[11px] font-semibold bg-[#ff1744]/20 border border-[#ff1744]/40 text-[#ff1744] hover:bg-[#ff1744]/30 transition-colors"
        >
          Confirm
        </button>
      </div>
    </div>
  );
}

// ── P&L badge ─────────────────────────────────────────────────────────────────

function PnlBadge({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span
      className={cn(
        'inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold tabular-nums',
        positive
          ? 'bg-[#00e676]/10 text-[#00e676]'
          : 'bg-[#ff1744]/10 text-[#ff1744]',
      )}
    >
      {fmtPnl(value)}
    </span>
  );
}

// ── Side badge ────────────────────────────────────────────────────────────────

function SideBadge({ side }: { side: string }) {
  const isLong = side === 'long' || side === 'buy';
  return (
    <span
      className={cn(
        'inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider',
        isLong
          ? 'bg-[#00e676]/10 text-[#00e676]'
          : 'bg-[#ff1744]/10 text-[#ff1744]',
      )}
    >
      {isLong ? '▲ Long' : '▼ Short'}
    </span>
  );
}

// ── Close button ──────────────────────────────────────────────────────────────

function CloseBtn({
  label,
  onClick,
  loading,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  loading: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={cn(
        'px-2 py-1 rounded text-[11px] font-semibold border transition-colors',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        danger
          ? 'border-[#ff1744]/40 text-[#ff1744] hover:bg-[#ff1744]/10'
          : 'border-[#334155] text-slate-400 hover:text-slate-200 hover:border-[#475569]',
      )}
    >
      {loading ? '…' : label}
    </button>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyPositions() {
  return (
    <div className="flex flex-col items-center justify-center py-10 gap-2">
      <span className="text-2xl opacity-30">📭</span>
      <span className="text-[12px] text-slate-500">No open positions</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface PositionsTableProps {
  /** If provided, only show positions for this symbol */
  symbol?: string;
  /** Called after a position is successfully closed */
  onClosed?: (id: string) => void;
}

function PositionsTableInner({ symbol, onClosed }: PositionsTableProps) {
  const positions   = useStore((s) => s.positions);
  const removePos   = useStore((s) => s.removePosition);
  const setPositions = useStore((s) => s.setPositions);
  const qc          = useQueryClient();

  const [closingId, setClosingId]       = useState<string | null>(null);
  const [closingAll, setClosingAll]     = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [confirmCloseAll, setConfirmCloseAll] = useState(false);

  const filtered = symbol
    ? positions.filter((p) => p.symbol === symbol)
    : positions;

  const totalPnl = filtered.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['positions'] });
  }, [qc]);

  const handleClose = useCallback(async (id: string) => {
    setClosingId(id);
    setError(null);
    try {
      await tradingApi.closePosition(id);
      removePos(id);
      onClosed?.(id);
      invalidate();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as { message?: string })?.message ?? 'Close failed';
      setError(msg);
    } finally {
      setClosingId(null);
    }
  }, [removePos, onClosed, invalidate]);

  const handleCloseAllConfirmed = useCallback(async () => {
    setConfirmCloseAll(false);
    setClosingAll(true);
    setError(null);
    try {
      await tradingApi.closeAllPositions();
      setPositions([]);
      invalidate();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as { message?: string })?.message ?? 'Close all failed';
      setError(msg);
    } finally {
      setClosingAll(false);
    }
  }, [setPositions, invalidate]);

  const headerRight = filtered.length > 0 ? (
    <div className="flex items-center gap-3">
      <span className={cn(
        'text-[11px] font-semibold tabular-nums',
        totalPnl >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
      )}>
        Total P&L: {fmtPnl(totalPnl)}
      </span>
      <CloseBtn
        label="Close All"
        onClick={() => setConfirmCloseAll(true)}
        loading={closingAll}
        danger
      />
    </div>
  ) : undefined;

  return (
    <Panel
      title={`Open Positions${filtered.length > 0 ? ` (${filtered.length})` : ''}`}
      headerRight={headerRight}
      noPad
    >
      {confirmCloseAll && (
        <ConfirmDialog
          message={`Close all ${filtered.length} open position(s)? This cannot be undone.`}
          onConfirm={handleCloseAllConfirmed}
          onCancel={() => setConfirmCloseAll(false)}
        />
      )}

      {error && (
        <div className="mx-4 mt-3 px-3 py-2 rounded bg-[#ff1744]/10 border border-[#ff1744]/20 text-[#ff1744] text-[11px]">
          {error}
        </div>
      )}

      {filtered.length === 0 ? (
        <EmptyPositions />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-[#1e2d3d]">
                {['Symbol', 'Side', 'Size', 'Entry', 'Current', 'SL', 'TP', 'P&L', 'Opened', ''].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((pos) => (
                <PositionRow
                  key={pos.id}
                  pos={pos}
                  closing={closingId === pos.id}
                  onClose={() => handleClose(pos.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

// ── Position row ──────────────────────────────────────────────────────────────

function PositionRow({
  pos,
  closing,
  onClose,
}: {
  pos: Position;
  closing: boolean;
  onClose: () => void;
}) {
  const pnlPct =
    pos.entry_price > 0
      ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100 *
        (pos.side === 'long' ? 1 : -1)
      : 0;

  return (
    <tr className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/40 transition-colors">
      <td className="px-3 py-2.5 font-semibold text-slate-200 whitespace-nowrap">
        {pos.symbol}
      </td>
      <td className="px-3 py-2.5">
        <SideBadge side={pos.side} />
      </td>
      <td className="px-3 py-2.5 tabular-nums text-slate-300">
        {pos.size}
      </td>
      <td className="px-3 py-2.5 tabular-nums text-slate-300">
        {fmtPrice(pos.entry_price)}
      </td>
      <td className="px-3 py-2.5 tabular-nums text-slate-200 font-medium">
        {fmtPrice(pos.current_price)}
      </td>
      <td className="px-3 py-2.5 tabular-nums text-slate-500">
        {pos.stop_loss ? fmtPrice(pos.stop_loss) : '—'}
      </td>
      <td className="px-3 py-2.5 tabular-nums text-slate-500">
        {pos.take_profit ? fmtPrice(pos.take_profit) : '—'}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex flex-col gap-0.5">
          <PnlBadge value={pos.unrealized_pnl} />
          <span className={cn(
            'text-[10px] tabular-nums',
            pnlPct >= 0 ? 'text-[#00e676]/70' : 'text-[#ff1744]/70',
          )}>
            {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
          </span>
        </div>
      </td>
      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
        {fmtDateTime(pos.opened_at)}
      </td>
      <td className="px-3 py-2.5">
        <CloseBtn
          label="Close"
          onClick={onClose}
          loading={closing}
          danger
        />
      </td>
    </tr>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

export function PositionsTableSkeleton() {
  return <PanelSkeleton rows={4} />;
}

// ── Exports ───────────────────────────────────────────────────────────────────

export { PositionsTableInner as PositionsTable };
export const PositionsTableGuarded = withPanelGuard(PositionsTableInner, 'Positions', 4);
export default PositionsTableInner;
