/**
 * Trade page — real-time multi-symbol price board with integrated order entry.
 *
 * Layout:
 *   - Account metrics bar
 *   - Symbol selector strip (live bid/ask/mid/change% + sparkline per symbol)
 *   - Order entry (left) + Symbol positions (right)
 *   - Bottom tabbed section: All Positions | Trade History
 *
 * Data sources:
 *   1. Live WebSocket feed → Zustand store (prices, priceHistory, positions)
 *   2. REST polling fallback via usePositions / useAccount
 *   3. TanStack Query for trade history
 *
 * Wires to:
 *   POST   /api/trading/orders
 *   GET    /api/trading/trades
 *   DELETE /api/trading/positions/{id}
 *   DELETE /api/trading/positions
 */

import React, { useEffect, useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, Link } from 'react-router-dom';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import { useFlashHighlight } from '../hooks/useFlashHighlight';
import { PageHeader } from '../components';
import { useStore, selectWsStatus, useHasHydrated, selectIsAuth, selectSignals, selectRiskSnapshot } from '../store';
import { usePositions, useAccount } from '../hooks/useOrchestratorData';
import { tradingApi } from '../hooks/useApi';
import { OrderEntryForm } from '../components/panels/OrderEntryForm';
import { PositionsTable } from '../components/panels/PositionsTable';
import { Sparkline } from '../components/ui/Sparkline';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { cn, fmtPrice, fmtPnl, fmtDateTime } from '../lib/utils';
import type { PriceTick } from '../types';

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'ETH/USD'];

// ── Types ─────────────────────────────────────────────────────────────────────

interface ClosedTrade {
  id: string;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  opened_at: string;
  closed_at: string;
  duration_minutes?: number;
}

// ── Symbol card ───────────────────────────────────────────────────────────────

interface SymbolCardProps {
  symbol:   string;
  tick:     PriceTick | undefined;
  history:  PriceTick[];
  selected: boolean;
  onClick:  () => void;
}

const SymbolCard: React.FC<SymbolCardProps> = ({ symbol, tick, history, selected, onClick }) => {
  const change    = tick?.change_pct ?? 0;
  const isUp      = change >= 0;
  const sparkData = history.slice(-40).map((t) => t.mid);
  const flash     = useFlashHighlight(tick?.mid);

  return (
    <button
      onClick={onClick}
      style={{ background: selected ? undefined : flash, transition: 'background 0.4s ease' }}
      className={cn(
        'flex flex-col gap-1.5 px-3 py-2.5 rounded-lg border text-left transition-all',
        'min-w-[148px] flex-shrink-0',
        selected
          ? 'bg-[#1e3a5f] border-[#3b82f6] shadow-[0_0_0_1px_#3b82f6]'
          : 'bg-[#0d1421] border-[#1e2d3d] hover:border-[#334155]',
      )}
    >
      {/* Symbol + change badge */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-bold text-slate-200 tracking-wide">{symbol}</span>
        {tick && (
          <span
            className={cn(
              'text-[10px] font-semibold px-1.5 py-0.5 rounded',
              isUp ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]',
            )}
          >
            {isUp ? '+' : ''}{change.toFixed(2)}%
          </span>
        )}
      </div>

      {/* Mid price — prominent */}
      {tick ? (
        <span className="text-[15px] font-bold tabular-nums text-slate-100 leading-none">
          {fmtPrice(tick.mid)}
        </span>
      ) : (
        <span className="text-[12px] text-slate-600">No feed</span>
      )}

      {/* Bid / Ask / Spread row */}
      {tick && (
        <div className="flex gap-3 text-[10px] tabular-nums">
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Bid</span>
            <span className="text-[#ff3b5c] font-semibold">{fmtPrice(tick.bid)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Ask</span>
            <span className="text-[#00e676] font-semibold">{fmtPrice(tick.ask)}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] text-slate-600 uppercase">Sprd</span>
            <span className="text-slate-500">{fmtPrice(tick.ask - tick.bid, 3)}</span>
          </div>
        </div>
      )}

      {/* Sparkline */}
      {sparkData.length >= 2 && (
        <Sparkline data={sparkData} width={132} height={22} />
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
        { label: 'Balance',      value: `$${balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,    color: 'text-slate-200' },
        { label: 'Equity',       value: `$${equity.toLocaleString('en-US',  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,    color: 'text-slate-200' },
        { label: 'Free Margin',  value: `$${freeMargin.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: 'text-slate-300' },
        {
          label: 'Unrealized P&L',
          value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`,
          color: pnl >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
        },
        {
          label: 'Margin Level',
          value: account.margin_level != null ? `${account.margin_level.toFixed(0)}%` : '—',
          color:
            (account.margin_level ?? 300) > 200 ? 'text-[#00e676]' :
            (account.margin_level ?? 300) > 100 ? 'text-[#ffb800]' : 'text-[#ff1744]',
        },
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
            wsStatus === 'connected'  ? 'bg-[#00e676] animate-pulse' :
            wsStatus === 'connecting' ? 'bg-[#ffb800]' : 'bg-[#ff1744]',
          )}
        />
        <span className="text-[10px] text-slate-500 capitalize">{wsStatus}</span>
      </div>
    </div>
  );
};

// ── Trade history table ────────────────────────────────────────────────────────

function TradeHistoryTab() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const { data, isLoading, isError } = useQuery<ClosedTrade[]>({
    queryKey: ['recent-trades-tab'],
    queryFn: async () => {
      const r   = await tradingApi.trades({ limit: 30 });
      const raw = r.data as ClosedTrade[] | { trades?: ClosedTrade[] };
      return Array.isArray(raw) ? raw : (raw.trades ?? []);
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  if (isLoading) return <div className="p-4"><PanelSkeleton rows={5} /></div>;
  if (isError)   return <div className="p-4 text-[11px] text-[#ff1744]">Failed to load trade history</div>;
  if (!data?.length) return (
    <div className="flex items-center justify-center h-20 text-slate-600 text-[12px]">
      No closed trades yet
    </div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[#1e2d3d]">
            {['Symbol','Side','Size','Entry','Exit','P&L','Opened','Closed','Duration'].map((h) => (
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
          {data.map((t) => {
            const isLong = t.side === 'long' || t.side === 'buy';
            const pnlPos = t.realized_pnl >= 0;
            return (
              <tr key={t.id} className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/30 transition-colors">
                <td className="px-3 py-2 font-semibold text-slate-200 whitespace-nowrap">{t.symbol}</td>
                <td className="px-3 py-2">
                  <span className={cn(
                    'px-1.5 py-0.5 rounded text-[10px] font-bold uppercase',
                    isLong ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]',
                  )}>
                    {isLong ? '▲ Long' : '▼ Short'}
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{t.size}</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{fmtPrice(t.entry_price)}</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{fmtPrice(t.exit_price)}</td>
                <td className="px-3 py-2">
                  <span className={cn('font-semibold tabular-nums', pnlPos ? 'text-[#00e676]' : 'text-[#ff1744]')}>
                    {fmtPnl(t.realized_pnl)}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDateTime(t.opened_at)}</td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDateTime(t.closed_at)}</td>
                <td className="px-3 py-2 text-slate-500 tabular-nums">
                  {t.duration_minutes != null ? `${t.duration_minutes}m` : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── AI Signal panel for selected symbol ──────────────────────────────────────

const AISignalPanel: React.FC<{ symbol: string }> = ({ symbol }) => {
  const signals = useStore(selectSignals);
  const symSignals = signals
    .filter((s) => s.symbol === symbol && s.status === 'active')
    .slice(0, 3);

  if (symSignals.length === 0) {
    return (
      <div className="flex items-center justify-center h-16 text-slate-600 text-[11px]">
        No active AI signals for {symbol}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {symSignals.map((sig) => {
        const isLong = sig.direction === 'long';
        const conf   = sig.confidence * 100;
        return (
          <div key={sig.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-[#0a0f1a] border border-[#1e2d3d]">
            <span className={cn(
              'text-[10px] font-bold px-2 py-0.5 rounded uppercase',
              isLong ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]',
            )}>
              {isLong ? '▲ Long' : '▼ Short'}
            </span>
            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
              <div className="flex gap-3 text-[10px] tabular-nums">
                <span className="text-slate-500">Entry <span className="text-slate-300">{fmtPrice(sig.entry_price)}</span></span>
                <span className="text-[#ff3b5c]">SL {fmtPrice(sig.stop_loss)}</span>
                <span className="text-[#00e676]">TP {fmtPrice(sig.take_profit)}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1 rounded bg-[#1e2d3d]">
                  <div
                    className="h-1 rounded transition-all"
                    style={{
                      width: `${conf}%`,
                      background: conf >= 75 ? '#00e676' : conf >= 55 ? '#ffb800' : '#ff1744',
                    }}
                  />
                </div>
                <span className="text-[10px] text-slate-500 tabular-nums">{conf.toFixed(0)}%</span>
                <span className="text-[10px] text-slate-600">{sig.model}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ── Risk bar ──────────────────────────────────────────────────────────────────

const RiskBar: React.FC = () => {
  const risk = useStore(selectRiskSnapshot);
  if (!risk) return null;

  const items = [
    { label: 'Daily Loss', value: risk.daily_loss_pct != null ? `${risk.daily_loss_pct.toFixed(2)}%` : '—', warn: (risk.daily_loss_pct ?? 0) > 3 },
    { label: 'Max DD',     value: risk.max_drawdown_pct != null ? `${risk.max_drawdown_pct.toFixed(2)}%` : '—', warn: (risk.max_drawdown_pct ?? 0) > 8 },
    { label: 'Open Risk',  value: risk.open_risk_pct != null ? `${risk.open_risk_pct.toFixed(2)}%` : '—', warn: (risk.open_risk_pct ?? 0) > 5 },
    { label: 'Kill Switch', value: risk.kill_switch_active ? '🔴 ACTIVE' : '🟢 Off', warn: !!risk.kill_switch_active },
  ];

  return (
    <div className="flex flex-wrap gap-4 px-4 py-2 rounded-lg bg-[#0d1421] border border-[#1e2d3d] text-[11px]">
      {items.map(({ label, value, warn }) => (
        <div key={label} className="flex flex-col gap-0.5">
          <span className="text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
          <span className={cn('font-semibold tabular-nums', warn ? 'text-[#ff1744]' : 'text-slate-300')}>{value}</span>
        </div>
      ))}
    </div>
  );
};

// ── Bottom section (tabbed) ───────────────────────────────────────────────────

type BottomTab = 'all-positions' | 'history';

function BottomSection() {
  const [tab, setTab] = useState<BottomTab>('all-positions');

  const tabs: { id: BottomTab; label: string }[] = [
    { id: 'all-positions', label: 'All Positions' },
    { id: 'history',       label: 'Trade History' },
  ];

  return (
    <div className="bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden">
      <div className="flex items-center gap-1 px-3 py-2 border-b border-[#1e2d3d]">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              'px-3 py-1 rounded text-[11px] font-semibold border transition-colors',
              tab === id
                ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div>
        {tab === 'all-positions' && <PositionsTable />}
        {tab === 'history'       && <TradeHistoryTab />}
      </div>
    </div>
  );
}

// ── Keyboard shortcut hint bar ────────────────────────────────────────────────

const KeyboardHints: React.FC = () => (
  <div className="flex flex-wrap gap-3 px-3 py-1.5 rounded bg-[#0a0f1a] border border-[#1e2d3d] text-[10px] text-slate-600">
    {[
      ['1–6', 'Select symbol'],
      ['B', 'Buy market'],
      ['S', 'Sell market'],
      ['Esc', 'Cancel / deselect'],
      ['Cmd+K', 'Command palette'],
    ].map(([key, desc]) => (
      <span key={key} className="flex items-center gap-1">
        <kbd className="px-1.5 py-0.5 rounded bg-[#1e2d3d] text-slate-400 font-mono text-[9px]">{key}</kbd>
        <span>{desc}</span>
      </span>
    ))}
  </div>
);

// ── Page ──────────────────────────────────────────────────────────────────────

const Trade: React.FC = () => {
  const location    = useLocation();
  const signalState = (location.state as { signal?: {
    symbol?: string; direction?: string;
    stop_loss?: number; take_profit?: number;
  } } | null)?.signal;

  const [selectedSymbol, setSelectedSymbol] = useState(signalState?.symbol ?? 'XAU/USD');
  const [closingAll, setClosingAll]         = useState(false);
  const [pendingSide, setPendingSide]       = useState<'buy' | 'sell' | null>(null);
  const prices      = useStore((s) => s.prices);
  const allHistory  = useStore((s) => s.priceHistory);
  const qc          = useQueryClient();
  const confirm     = useConfirm();
  const toast       = useToast();

  usePositions();

  const handleCloseAll = useCallback(async () => {
    const ok = await confirm({
      title:        'Close all positions?',
      description:  'This will market-close every open position immediately. This cannot be undone.',
      confirmLabel: 'Close All',
      variant:      'danger',
    });
    if (!ok) return;
    setClosingAll(true);
    try {
      await tradingApi.closeAllPositions();
      await qc.invalidateQueries({ queryKey: ['positions'] });
      toast.success('All positions closed.');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Failed to close positions.');
    } finally {
      setClosingAll(false);
    }
  }, [confirm, qc, toast]);

  // ── Keyboard shortcuts ──────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore when typing in an input/textarea
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      // 1–6: select symbol by index
      const idx = parseInt(e.key, 10) - 1;
      if (idx >= 0 && idx < SYMBOLS.length) {
        setSelectedSymbol(SYMBOLS[idx]);
        return;
      }

      switch (e.key.toLowerCase()) {
        case 'b': setPendingSide('buy');  break;
        case 's': setPendingSide('sell'); break;
        case 'escape': setPendingSide(null); break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="flex flex-col gap-4 p-4 min-h-screen bg-[#0a0f1a]">

      <PageHeader
        title="Trade"
        subtitle="Real-time execution — market, limit and stop orders"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Trade' },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Link
              to="/watchlist"
              className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#0c1a2e] border border-[#1e3a5f] text-[#38bdf8] hover:bg-[#1e3a5f]/40 transition-colors"
              style={{ textDecoration: 'none' }}
            >
              👁 Watchlist
            </Link>
            <Link
              to="/portfolio"
              className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#1e1b4b] border border-[#4338ca] text-[#a78bfa] hover:bg-[#4338ca]/20 transition-colors"
              style={{ textDecoration: 'none' }}
            >
              💼 Portfolio
            </Link>
            <Link
              to="/risk-calculator"
              className="px-3 py-1.5 rounded text-[11px] font-semibold bg-[#1e293b] border border-[#334155] text-[#94a3b8] hover:bg-[#334155]/40 transition-colors"
              style={{ textDecoration: 'none' }}
            >
              🛡 Risk Calc
            </Link>
            <button
              onClick={handleCloseAll}
              disabled={closingAll}
              className="px-3 py-1.5 rounded text-[11px] font-bold bg-[#ff1744]/10 border border-[#ff1744]/30 text-[#ff1744] hover:bg-[#ff1744]/20 transition-colors disabled:opacity-50"
            >
              {closingAll ? 'Closing…' : '✕ Close All'}
            </button>
          </div>
        }
      />

      {/* Account metrics */}
      <AccountBar />

      {/* Risk bar */}
      <RiskBar />

      {/* Keyboard shortcut hints */}
      <KeyboardHints />

      {/* Symbol selector strip — numbers 1-6 select via keyboard */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-[#1e2d3d]">
        {SYMBOLS.map((sym, i) => (
          <SymbolCard
            key={sym}
            symbol={sym}
            tick={prices[sym]}
            history={allHistory[sym] ?? []}
            selected={selectedSymbol === sym}
            onClick={() => setSelectedSymbol(sym)}
          />
        ))}
      </div>

      {/* Order entry + symbol positions + AI signals */}
      <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-4 items-start">
        <OrderEntryForm
          symbol={selectedSymbol}
          defaultSide={
            pendingSide ??
            (signalState?.direction === 'SELL' ? 'sell' : signalState?.direction === 'BUY' ? 'buy' : undefined)
          }
          defaultSl={signalState?.stop_loss ? String(signalState.stop_loss) : undefined}
          defaultTp={signalState?.take_profit ? String(signalState.take_profit) : undefined}
          onOrderPlaced={() => {
            setPendingSide(null);
            void qc.invalidateQueries({ queryKey: ['positions'] });
          }}
        />
        <div className="flex flex-col gap-4">
          <PositionsTable symbol={selectedSymbol} />
          <div className="bg-[#0d1421] border border-[#1e2d3d] rounded-lg p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
              AI Signals — {selectedSymbol}
            </div>
            <AISignalPanel symbol={selectedSymbol} />
          </div>
        </div>
      </div>

      {/* Bottom: all positions + trade history tabs */}
      <BottomSection />
    </div>
  );
};

export default Trade;
