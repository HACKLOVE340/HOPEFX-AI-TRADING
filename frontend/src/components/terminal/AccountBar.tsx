/**
 * components/terminal/AccountBar.tsx
 * Horizontal account metrics bar below the price ticker.
 * Shows: balance, equity, daily P&L, margin level, open trades, win rate.
 */

import React from 'react';
import { useStore } from '../../store';
import { MetricTile } from '../ui/MetricTile';
import { fmtPrice, fmtPct, fmtRatio, pnlColor, cn } from '../../lib/utils';

export function AccountBar() {
  const account = useStore((s) => s.account);

  if (!account) {
    return (
      <div className="flex items-center gap-6 px-5 py-2.5 bg-[#0d1421] border-b border-[#1e2d3d]">
        <span className="text-[10px] text-slate-600 font-mono animate-pulse">
          Loading account data…
        </span>
      </div>
    );
  }

  const marginColor =
    account.margin_level > 200 ? '#00e676' :
    account.margin_level > 100 ? '#ffb800' : '#ff3b5c';

  return (
    <div className="flex items-center gap-6 px-5 py-2.5 bg-[#0d1421] border-b border-[#1e2d3d] overflow-x-auto scrollbar-terminal shrink-0">
      <MetricTile
        label="Balance"
        value={`$${account.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Equity"
        value={`$${account.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
        valueColor="#00d4ff"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Daily P&L"
        value={fmtPct(account.daily_pnl_pct / 100)}
        sub={`$${account.daily_pnl >= 0 ? '+' : ''}${account.daily_pnl.toFixed(2)}`}
        valueColor={account.daily_pnl >= 0 ? '#00e676' : '#ff1744'}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Total P&L"
        value={`$${account.total_pnl >= 0 ? '+' : ''}${account.total_pnl.toFixed(2)}`}
        valueColor={pnlColor(account.total_pnl)}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Margin"
        value={`${account.margin_level.toFixed(0)}%`}
        sub={`Used: $${account.margin_used.toFixed(0)}`}
        valueColor={marginColor}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Win Rate"
        value={`${(account.win_rate * 100).toFixed(1)}%`}
        valueColor="#00e676"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Max DD"
        value={`${(account.max_drawdown * 100).toFixed(1)}%`}
        valueColor="#ff3b5c"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Sharpe"
        value={fmtRatio(account.sharpe_ratio)}
        valueColor="#00d4ff"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Open Trades"
        value={account.open_trades.toString()}
        compact
      />
      {account.kill_switch && (
        <>
          <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
          <div className="flex items-center gap-1.5 px-2 py-1 bg-[#ff1744]/10 border border-[#ff1744]/30 rounded animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-[#ff1744]" />
            <span className="text-[10px] font-semibold text-[#ff1744] uppercase tracking-wider">
              Kill Switch
            </span>
          </div>
        </>
      )}
    </div>
  );
}
