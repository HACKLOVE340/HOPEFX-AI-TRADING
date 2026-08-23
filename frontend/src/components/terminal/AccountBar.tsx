/**
 * components/terminal/AccountBar.tsx
 * Horizontal account metrics bar below the price ticker.
 * Shows: balance, equity, daily P&L, margin level, open trades, win rate.
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore, selectKillSwitch } from '../../store';
import { MetricTile } from '../ui/MetricTile';
import { fmtPctRaw, fmtPct, fmtRatio, pnlColor, fmtMarginLevel, marginLevelIsSafe, fmtPrice, fmtPnl } from '../../lib/utils';
import { notificationsApi } from '../../hooks/useApi';

function NotificationBell() {
  const navigate = useNavigate();
  const [count, setCount] = useState(0);

  useEffect(() => {
    const fetch = () =>
      notificationsApi.list({ page: 1, limit: 1, unread_only: true })
        .then(r => {
          const d = r.data as { total?: number; notifications?: unknown[] } | unknown[];
          const total = Array.isArray(d) ? d.length : ((d as { total?: number }).total ?? 0);
          setCount(typeof total === 'number' ? total : 0);
        })
        .catch(() => {/* non-fatal */});
    fetch();
    const id = setInterval(fetch, 60_000);
    return () => clearInterval(id);
  }, []);

  return (
    <button
      onClick={() => navigate('/notifications')}
      title={count > 0 ? `${count} unread notification${count === 1 ? '' : 's'}` : 'Notifications'}
      style={{
        position: 'relative', flexShrink: 0,
        background: 'transparent', border: 'none', cursor: 'pointer',
        padding: '2px 6px', borderRadius: 6,
        display: 'flex', alignItems: 'center',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)'}
      onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.background = 'transparent'}
    >
      <span style={{ fontSize: 14 }}>🔔</span>
      {count > 0 && (
        <span style={{
          position: 'absolute', top: 0, right: 2,
          minWidth: 14, height: 14, borderRadius: 7,
          background: '#ef4444', color: '#fff',
          fontSize: 9, fontWeight: 800, lineHeight: '14px',
          textAlign: 'center', padding: '0 3px',
        }}>
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  );
}

export function AccountBar() {
  const account = useStore((s) => s.account);
  // Shared selector: three surfaces used to derive this independently from two
  // different fields and could disagree about whether trading was halted
  // (S10-02).
  const killSwitch = useStore(selectKillSwitch);

  if (!account) {
    return (
      <div className="flex items-center gap-6 px-5 py-2.5 bg-[#0d1421] border-b border-[#1e2d3d]">
        <span className="text-[10px] text-slate-600 font-mono animate-pulse">
          Loading account data…
        </span>
      </div>
    );
  }

  // Account statistics are absent on a new account and before the first
  // evaluation cycle (audit #37). The shared fmt* helpers already render '—'
  // for null/undefined — this file just wasn't using them for every field.
  const marginColor =
    marginLevelIsSafe(account.margin_level) ? '#00e676' :
    (account.margin_level ?? 0) > 100 ? '#ffb800' : '#ff3b5c';

  return (
    <div className="flex items-center gap-6 px-5 py-2.5 bg-[#0d1421] border-b border-[#1e2d3d] overflow-x-auto scrollbar-terminal shrink-0">
      <MetricTile
        label="Balance"
        to="/wallet"
        toHint="Wallet"
        value={`$${fmtPrice(account.balance)}`}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Equity"
        to="/portfolio"
        toHint="Portfolio"
        value={`$${fmtPrice(account.equity)}`}
        valueColor="#00d4ff"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Daily P&L"
        to="/pnl"
        toHint="the P&L breakdown"
        value={fmtPctRaw(account.daily_pnl_pct)}
        sub={fmtPnl(account.daily_pnl)}
        valueColor={(account.daily_pnl ?? 0) >= 0 ? '#00e676' : '#ff1744'}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Total P&L"
        to="/pnl"
        toHint="the P&L breakdown"
        value={fmtPnl(account.total_pnl)}
        valueColor={pnlColor(account.total_pnl)}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Margin"
        to="/risk-calculator"
        toHint="the Risk Calculator"
        value={fmtMarginLevel(account.margin_level, account.margin_used)}
        sub={`Used: $${fmtPrice(account.margin_used, 0)}`}
        valueColor={marginColor}
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Win Rate"
        to="/journal"
        toHint="the trades behind it"
        value={fmtPct(account.win_rate, 1)}
        valueColor="#00e676"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Max DD"
        to="/performance"
        toHint="the drawdown curve"
        value={fmtPct(account.max_drawdown, 1)}
        valueColor="#ff3b5c"
        compact
      />
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Sharpe"
        to="/performance"
        toHint="risk-adjusted performance"
        value={fmtRatio(account.sharpe_ratio)}
        valueColor="#00d4ff"
        compact
      />
      {account.sortino_ratio != null && (
        <>
          <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
          <MetricTile
            label="Sortino"
        to="/performance"
        toHint="risk-adjusted performance"
            value={fmtRatio(account.sortino_ratio)}
            valueColor="#a78bfa"
            compact
          />
        </>
      )}
      <div className="w-px h-6 bg-[#1e2d3d] shrink-0" />
      <MetricTile
        label="Open Trades"
        to="/portfolio"
        toHint="your positions"
        value={account.open_trades?.toString() ?? '—'}
        compact
      />
      {killSwitch && (
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
      <div className="ml-auto shrink-0 flex items-center gap-1">
        <NotificationBell />
      </div>
    </div>
  );
}
