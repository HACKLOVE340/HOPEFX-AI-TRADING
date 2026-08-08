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
import { useStore, selectFeedLive } from '../../store';
import { tradingApi } from '../../hooks/useApi';
import { Panel } from '../ui/Panel';
import { PanelSkeleton } from '../ui/Skeleton';
import { withPanelGuard } from '../ui/withPanelGuard';
import { fmtPrice, fmtPnl, fmtDateTime, cn, sameSymbol, positionSide, describeCloseAll, describeSubmitFailure } from '../../lib/utils';
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

function SideBadge({ side }: { side: 'long' | 'short' | null }) {
  if (side === null) {
    // Not reported by the API. Defaulting to Short would state the opposite of
    // the truth half the time (audit #37).
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-500/10 text-slate-400">
        —
      </span>
    );
  }
  const isLong = side === 'long';
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

/**
 * Empty state for the positions table.
 *
 * Three outcomes, deliberately distinct (audit S9-03):
 *
 *   - `positionsKnown === false` — the feed is stale or the socket is down, so
 *     an empty list means "we don't know", NOT "you are flat". This panel is
 *     what a trader checks before deciding whether to intervene, and rendering
 *     an unknown state as a confident zero is the one false negative here that
 *     can cost money.
 *   - `brokerReady === false` — broker still starting up.
 *   - otherwise — genuinely flat.
 */
function EmptyPositions({
  brokerReady,
  positionsKnown = true,
}: {
  brokerReady?: boolean;
  positionsKnown?: boolean;
}) {
  if (!positionsKnown) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-2 px-4 text-center">
        <span className="text-2xl opacity-40">⚠️</span>
        <span className="text-[12px] text-[#ffb800]">Can&apos;t confirm positions</span>
        <span className="text-[11px] text-slate-500">
          The live feed is not up to date, so this list may be incomplete. Check your
          broker directly before acting.
        </span>
      </div>
    );
  }
  if (brokerReady === false) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-2 px-4 text-center">
        <span className="text-2xl opacity-40">⏳</span>
        <span className="text-[12px] text-[#ffb800]">Broker initialising</span>
        <span className="text-[11px] text-slate-500">
          The paper trading engine is starting up. Positions will appear here once ready.
        </span>
      </div>
    );
  }
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
  const positions    = useStore((s) => s.positions);
  const removePos    = useStore((s) => s.removePosition);
  const setPositions = useStore((s) => s.setPositions);
  const account      = useStore((s) => s.account);
  // An empty positions list only means "flat" when the feed is actually
  // delivering. Stale or disconnected, it means "unknown" — see S9-03.
  // The expression used to live here inline; it is now `selectFeedLive`, shared
  // with the other surfaces that ask the same question (F1-02).
  const positionsKnown = useStore(selectFeedLive);
  const qc           = useQueryClient();

  // Broker is considered ready once we have account data with a balance.
  // null = unknown (still loading), true/false = known state.
  const brokerReady: boolean | undefined =
    account != null ? (account.balance != null && account.balance >= 0) : undefined;

  const [closingId, setClosingId]       = useState<string | null>(null);
  const [closingAll, setClosingAll]     = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [confirmCloseAll, setConfirmCloseAll] = useState(false);

  // sameSymbol, not ===: the panel's `symbol` is UI form ("XAU/USD") while a
  // position's symbol is canonical ("XAUUSD"). A raw === hid every open trade.
  const filtered = symbol
    ? positions.filter((p) => sameSymbol(p.symbol, symbol))
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
      // F2-01: "Close failed" after a 30s timeout is a claim we cannot make —
      // the close may have gone through. Refetch rather than leave the row
      // showing an exposure that may no longer exist.
      const outcome = describeSubmitFailure(e, 'close');
      setError(outcome.message);
      if (!outcome.outcomeKnown) invalidate();
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
      // Worse here than for a single close: a close-all that timed out may have
      // closed some, all, or none of them. Ask the server rather than guess.
      const outcome = describeSubmitFailure(e, 'close-all');
      setError(outcome.message);
      if (!outcome.outcomeKnown) invalidate();
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
          message={describeCloseAll(filtered)}
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
        <EmptyPositions brokerReady={brokerReady} positionsKnown={positionsKnown} />
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
  // F5-02: `pos.side === 'long' ? 1 : -1` decided the sign of this number, and
  // the API reports direction as `side` or `direction`, in either case, with
  // 'buy'/'sell' as well as 'long'/'short'. A profitable long arriving as
  // side:'buy' rendered as a −10% loss — beside a badge that read LONG, because
  // that one line below already called `positionSide`. An unreported side fell
  // to −1, i.e. defaulted to short, which is exactly what the helper's docstring
  // forbids. Null now means unknown and shows no signed percentage at all.
  const side = positionSide(pos);
  const pnlPct =
    pos.entry_price > 0 && side !== null
      ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100 *
        (side === 'long' ? 1 : -1)
      : null;

  return (
    <tr className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/40 transition-colors">
      <td className="px-3 py-2.5 font-semibold text-slate-200 whitespace-nowrap">
        {pos.symbol}
      </td>
      <td className="px-3 py-2.5">
        <SideBadge side={positionSide(pos)} />
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
          {pnlPct === null ? (
            // Direction not reported: the percentage cannot be signed, and a
            // guessed sign is worse than no number (F5-02).
            <span className="text-[10px] tabular-nums text-slate-500" title="Direction not reported">
              —
            </span>
          ) : (
            <span className={cn(
              'text-[10px] tabular-nums',
              pnlPct >= 0 ? 'text-[#00e676]/70' : 'text-[#ff1744]/70',
            )}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          )}
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
