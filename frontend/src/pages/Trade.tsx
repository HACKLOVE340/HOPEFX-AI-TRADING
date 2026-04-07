/**
 * Trade page — real-time multi-symbol price board with integrated order entry.
 *
 * Layout:
 *   - Symbol selector strip (live bid/ask/change% per symbol)
 *   - Order entry form (market/limit/stop, SL/TP, risk preview)
 *   - Open positions table for the selected symbol
 *
 * Data sources:
 *   1. Live WebSocket feed → Zustand store (prices, positions)
 *   2. REST polling fallback via usePositions / useAccount
 *
 * Wires to:
 *   POST   /api/trading/orders
 *   DELETE /api/trading/positions/{id}
 *   DELETE /api/trading/positions
 */

import React, { useState } from 'react';
import { useStore, selectWsStatus } from '../store';
import { usePositions, useAccount } from '../hooks/useOrchestratorData';
import { OrderEntryForm } from '../components/panels/OrderEntryForm';
import { PositionsTable } from '../components/panels/PositionsTable';
import { cn, fmtPrice } from '../lib/utils';
import type { PriceTick } from '../types';

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'ETH/USD'];

// ── Symbol card ───────────────────────────────────────────────────────────────

interface SymbolCardProps {
  symbol:   string;
  tick:     PriceTick | undefined;
  selected: boolean;
  onClick:  () => void;
}

const SymbolCard: React.FC<SymbolCardProps> = ({ symbol, tick, selected, onClick }) => {
  const change  = tick?.change_pct ?? 0;
  const isUp    = change >= 0;
  const noData  = !tick;

  return (
    <button
      onClick={onClick}
      className={cn(
        'flex flex-col gap-1 px-4 py-3 rounded-lg border text-left transition-all',
        'min-w-[130px] flex-shrink-0',
        selected
          ? 'bg-[#1e3a5f] border-[#3b82f6] shadow-[0_0_0_1px_#3b82f6]'
          : 'bg-[#0d1421] border-[#1e2d3d] hover:border-[#334155]',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-bold text-slate-200 tracking-wide">{symbol}</span>
        {!noData && (
          <span
            className={cn(
              'text-[10px] font-semibold px-1.5 py-0.5 rounded',
              isUp
                ? 'bg-[#00e676]/10 text-[#00e676]'
                : 'bg-[#ff1744]/10 text-[#ff1744]',
            )}
          >
            {isUp ? '+' : ''}{change.toFixed(2)}%
          </span>
        )}
      </div>

      {noData ? (
        <span className="text-[11px] text-slate-600">No feed</span>
      ) : (
        <div className="flex gap-3 text-[11px] tabular-nums">
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] text-slate-600 uppercase">Bid</span>
            <span className="text-[#ff1744] font-semibold">{fmtPrice(tick!.bid)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] text-slate-600 uppercase">Ask</span>
            <span className="text-[#00e676] font-semibold">{fmtPrice(tick!.ask)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[9px] text-slate-600 uppercase">Spread</span>
            <span className="text-slate-400">{fmtPrice(tick!.ask - tick!.bid, 3)}</span>
          </div>
        </div>
      )}
    </button>
  );
};

// ── Account bar ───────────────────────────────────────────────────────────────

const AccountBar: React.FC = () => {
  const { data: account } = useAccount();
  const wsStatus = useStore(selectWsStatus);

  if (!account) return null;

  const equity     = account.equity      ?? account.balance ?? 0;
  const balance    = account.balance     ?? 0;
  const margin     = account.margin_used ?? 0;
  const freeMargin = account.margin_free ?? (equity - margin);
  const pnl        = account.total_pnl   ?? 0;

  return (
    <div className="flex flex-wrap gap-4 px-4 py-2.5 rounded-lg bg-[#0d1421] border border-[#1e2d3d] text-[11px]">
      {[
        { label: 'Balance',      value: `$${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,      color: 'text-slate-200' },
        { label: 'Equity',       value: `$${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,       color: 'text-slate-200' },
        { label: 'Free Margin',  value: `$${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,   color: 'text-slate-300' },
        { label: 'Unrealized P&L', value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`, color: pnl >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]' },
      ].map(({ label, value, color }) => (
        <div key={label} className="flex flex-col gap-0.5">
          <span className="text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
          <span className={cn('font-semibold tabular-nums', color)}>{value}</span>
        </div>
      ))}

      <div className="ml-auto flex items-center gap-1.5">
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full',
            wsStatus === 'connected'   ? 'bg-[#00e676]' :
            wsStatus === 'connecting'  ? 'bg-[#ffb800]' :
                                         'bg-[#ff1744]',
          )}
        />
        <span className="text-[10px] text-slate-500 capitalize">{wsStatus}</span>
      </div>
    </div>
  );
};

// ── Page ──────────────────────────────────────────────────────────────────────

const Trade: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState('XAU/USD');
  const prices = useStore((s) => s.prices);

  // Prefetch positions and account so they're ready when the page mounts
  usePositions();

  return (
    <div className="flex flex-col gap-4 p-4 min-h-screen bg-[#0a0f1a]">

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-slate-100">Trade</h1>
          <p className="text-[12px] text-slate-500 mt-0.5">
            Real-time execution — market, limit, and stop orders
          </p>
        </div>
      </div>

      {/* Account metrics bar */}
      <AccountBar />

      {/* Symbol selector strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-[#1e2d3d]">
        {SYMBOLS.map((sym) => (
          <SymbolCard
            key={sym}
            symbol={sym}
            tick={prices[sym]}
            selected={selectedSymbol === sym}
            onClick={() => setSelectedSymbol(sym)}
          />
        ))}
      </div>

      {/* Main content: order entry + positions */}
      <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4 items-start">

        {/* Order entry */}
        <div className="w-full">
          <OrderEntryForm
            symbol={selectedSymbol}
            onOrderPlaced={() => {
              // positions invalidated inside OrderEntryForm via queryClient
            }}
          />
        </div>

        {/* Positions for selected symbol */}
        <div className="w-full">
          <PositionsTable symbol={selectedSymbol} />
        </div>
      </div>

      {/* All open positions (cross-symbol summary) */}
      <PositionsTable />
    </div>
  );
};

export default Trade;
