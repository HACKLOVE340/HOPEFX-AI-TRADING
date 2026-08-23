/**
 * Watchlist page — add/remove symbols, live prices, sparklines, click to chart.
 *
 * Auth: JWT injected automatically via the api axios instance interceptor.
 * Wires to: GET    /api/watchlist
 *           POST   /api/watchlist/{symbol}
 *           DELETE /api/watchlist/{symbol}
 *           GET    /api/watchlist/prices
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { watchlistApi } from '../hooks/useApi';
import { useDataFreshness } from '../hooks/useDataFreshness';
import { StaleDataNotice } from '../components/ui/StaleDataNotice';
import { useStore, selectFeedLive } from '../store';
import { extractApiError, toSlashSymbol } from '../lib/utils';
import { PageHeader, Section, RelatedPages } from '../components';
import { DataTable, type Column } from '../components/DataTable';
import { EmptyState } from '../components/EmptyState';
import { Eye, Zap, BellPlus, X, Radio, LineChart, BookOpen } from 'lucide-react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface WatchlistItem {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  change_pct: number;
  timestamp: number;
  /** Ordered mid-price ticks used to render the sparkline. Populated by the
   *  /watchlist/prices endpoint; empty array when not yet available. */
  history: number[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const AVAILABLE_SYMBOLS = [
  'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD',
  'ETHUSD', 'USDCAD', 'AUDUSD', 'USDCHF', 'NZDUSD',
];

function formatPrice(symbol: string, price: number): string {
  if (price == null || !Number.isFinite(price)) return '—';
  if (symbol.includes('JPY')) return price.toFixed(2);
  if (symbol.includes('BTC') || symbol.includes('ETH') || symbol.includes('XAU')) return price.toFixed(2);
  return price.toFixed(5);
}

/**
 * Sparkline rendered from the item's real price history ticks.
 * Falls back to a flat line when fewer than 2 points are available.
 */
const Sparkline: React.FC<{ history: number[] }> = ({ history }) => {
  if (history.length < 2) {
    // Not enough data — render a neutral flat line
    return (
      <svg width={60} height={32} style={{ display: 'block' }}>
        <line x1={0} y1={16} x2={60} y2={16} stroke="#475569" strokeWidth={1.5} />
      </svg>
    );
  }

  const last  = history[history.length - 1];
  const first = history[0];
  // An empty history renders flat rather than throwing (audit #38).
  const up    = last !== undefined && first !== undefined ? last >= first : true;
  const color = up ? '#4ade80' : '#f87171';

  const min   = Math.min(...history);
  const max   = Math.max(...history);
  const range = max - min || 1;

  const normalized = history.map((p) => ((p - min) / range) * 28 + 2);
  const n          = normalized.length - 1;
  const path       = normalized
    .map((y, i) => `${i === 0 ? 'M' : 'L'}${(i / n) * 60},${30 - y}`)
    .join(' ');

  return (
    <svg width={60} height={32} style={{ display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
};

// ── Component ─────────────────────────────────────────────────────────────────

const WatchlistPage: React.FC = () => {
  const navigate    = useNavigate();
  const storePrices = useStore((s) => s.prices);
  const feedLive    = useStore(selectFeedLive);

  const [items,     setItems]     = useState<WatchlistItem[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [addSymbol, setAddSymbol] = useState('');
  const [adding,    setAdding]    = useState(false);
  const [error,     setError]     = useState('');

  /** Normalise an API item: guarantee `history` is always a number[]. */
  const normalise = (item: Omit<WatchlistItem, 'history'> & { history?: number[] }): WatchlistItem => ({
    ...item,
    history: item.history ?? [],
  });

  // F1-01: both fetches below used to swallow their failure, so the page
  // rendered its default symbol list — under the banner "Live prices refresh
  // every 5 seconds" — identically whether the backend was healthy or dead.
  const freshness = useDataFreshness('the watchlist');
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await watchlistApi.list() as { data: { items: Array<Omit<WatchlistItem, 'history'> & { history?: number[] }> } };
      if (!mountedRef.current) return;
      if (res.data.items?.length) {
        setItems(res.data.items.map(normalise));
      }
      if (mountedRef.current) freshness.markOk();
    } catch {
      // API unavailable. Keep whatever is on screen, but say so — rendering the
      // default list silently is what made this page indistinguishable from a
      // working one (F1-01).
      if (mountedRef.current) freshness.markFailed('the watchlist');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
    const id = setInterval(async () => {
      try {
        const res = await watchlistApi.prices() as { data: Array<Omit<WatchlistItem, 'history'> & { history?: number[] }> };
        if (Array.isArray(res.data) && res.data.length > 0) {
          setItems(res.data.map(normalise));
        }
        if (mountedRef.current) freshness.markOk();
      } catch {
        // Keep the last prices — but stop calling them live (F1-01).
        if (mountedRef.current) freshness.markFailed('live prices');
      }
    }, 5000);
    return () => clearInterval(id);
  }, [fetchWatchlist, freshness]);

  // Live tick history per symbol, accumulated across renders. Capped at 60
  // points, which is what the sparkline draws.
  //
  // Declared HERE, above `enrichedItems`, and not below it. `enrichedItems` is
  // a render-time computation that reads `tickHistory`; with the declaration
  // underneath, that read hit the const's temporal dead zone and threw
  // "Cannot access 'tickHistory' before initialization" on every render where
  // the branch was reachable — i.e. whenever the watchlist had a symbol and the
  // feed was live. A blank page for every user with a non-empty watchlist.
  //
  // Neither tsc nor the build caught it: TS2448 fires only for a direct
  // reference in the same scope, and this read is inside a `.map()` callback,
  // whose call time TypeScript cannot know. There is no ESLint in this project
  // to run `no-use-before-define`. Keep the declaration above its first read.
  const [tickHistory, setTickHistory] = useState<Record<string, number[]>>({});

  // Overlay live store prices for real-time feel.
  // Store keys on 'XAU/USD'; the watchlist stores 'XAUUSD'. The mapping used to
  // be a hardcoded chain of five .replace() calls against ten offered symbols,
  // so half of them never matched a feed key and simply showed no live price.
  //
  // F1-02: gated on the feed actually delivering. The overlay is socket data
  // laid over the 5-second HTTP snapshot, so a stalled feed did not merely fail
  // to update the row — it overwrote a *current* polled price with a frozen one,
  // under the banner "Live prices refresh every 5 seconds".
  const enrichedItems: WatchlistItem[] = items.map((item) => {
    if (!feedLive) return item;
    const tick = storePrices[toSlashSymbol(item.symbol)] ?? storePrices[item.symbol];
    if (!tick) return item;
    return {
      ...item,
      bid: tick.bid,
      ask: tick.ask,
      mid: tick.mid,
      change_pct: tick.change_pct,
      timestamp: tick.timestamp,
      // Ticks accumulate in `tickHistory` below. Deriving them here appended to
      // the server's snapshot on every render and threw the result away, so the
      // sparkline redrew the same two points forever.
      history: tickHistory[item.symbol] ?? item.history,
    };
  });

  const handleAdd = async () => {
    const sym = addSymbol.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    setError('');
    try {
      await watchlistApi.add(sym);
      setAddSymbol('');
      await fetchWatchlist();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409) setError(`${sym} is already in your watchlist`);
      else setError(`Failed to add ${sym}`);
    } finally {
      setAdding(false);
    }
  };

  // Accumulates into `tickHistory`, declared above `enrichedItems`.
  useEffect(() => {
    setTickHistory((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const item of items) {
        const tick = storePrices[toSlashSymbol(item.symbol)] ?? storePrices[item.symbol];
        if (!tick || !Number.isFinite(tick.mid)) continue;
        const series = next[item.symbol] ?? item.history ?? [];
        if (series[series.length - 1] === tick.mid) continue;   // no new tick
        next[item.symbol] = [...series, tick.mid].slice(-60);
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [items, storePrices]);

  const handleRemove = async (symbol: string) => {
    try {
      await watchlistApi.remove(symbol);
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
    } catch (err: unknown) {
      const msg = extractApiError(err, `Failed to remove ${symbol}.`);
      setError(msg);
    }
  };

  const columns: Column<WatchlistItem>[] = [
    {
      key: 'symbol', header: 'Symbol', width: '22%',
      sortValue: (r) => r.symbol,
      render: (r) => <span className="font-semibold text-slate-100">{r.symbol}</span>,
    },
    {
      key: 'bid', header: 'Bid', align: 'right', hideOnMobile: true,
      sortValue: (r) => r.bid,
      render: (r) => <span className="text-[#f87171]">{formatPrice(r.symbol, r.bid)}</span>,
    },
    {
      key: 'ask', header: 'Ask', align: 'right', hideOnMobile: true,
      sortValue: (r) => r.ask,
      render: (r) => <span className="text-[#4ade80]">{formatPrice(r.symbol, r.ask)}</span>,
    },
    {
      key: 'mid', header: 'Mid', align: 'right',
      sortValue: (r) => r.mid,
      render: (r) => <span className="font-semibold text-slate-50">{formatPrice(r.symbol, r.mid)}</span>,
    },
    {
      key: 'change', header: '24h', align: 'right',
      sortValue: (r) => (Number.isFinite(r.change_pct) ? r.change_pct : 0),
      render: (r) => (
        <span className={(r.change_pct ?? 0) >= 0 ? 'text-[#4ade80]' : 'text-[#f87171]'}>
          {Number.isFinite(r.change_pct)
            ? `${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%`
            : '—'}
        </span>
      ),
    },
    {
      key: 'trend', header: 'Trend', hideOnMobile: true, width: '80px',
      render: (r) => <Sparkline history={r.history} />,
    },
    {
      key: 'actions', header: 'Actions', align: 'right', width: '150px',
      render: (r) => (
        // stopPropagation: the row itself drills into the chart, so a control
        // inside it must not trigger that navigation as well.
        <span className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => navigate('/trade', { state: { signal: { symbol: toSlashSymbol(r.symbol) } } })}
            title={`Trade ${r.symbol}`}
            aria-label={`Trade ${r.symbol}`}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg
                       text-sky-400 cursor-pointer transition-colors duration-150
                       hover:bg-sky-500/15 focus-visible:outline-none focus-visible:ring-2
                       focus-visible:ring-sky-500 focus-visible:ring-inset"
          >
            <Zap size={15} strokeWidth={1.75} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => navigate('/alerts', { state: { symbol: r.symbol } })}
            title={`Set a price alert for ${r.symbol}`}
            aria-label={`Set a price alert for ${r.symbol}`}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg
                       text-amber-400 cursor-pointer transition-colors duration-150
                       hover:bg-amber-500/15 focus-visible:outline-none focus-visible:ring-2
                       focus-visible:ring-amber-500 focus-visible:ring-inset"
          >
            <BellPlus size={15} strokeWidth={1.75} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => void handleRemove(r.symbol)}
            title={`Remove ${r.symbol} from watchlist`}
            aria-label={`Remove ${r.symbol} from watchlist`}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg
                       text-slate-600 cursor-pointer transition-colors duration-150
                       hover:bg-red-500/15 hover:text-red-400 focus-visible:outline-none
                       focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-inset"
          >
            <X size={15} strokeWidth={2} aria-hidden />
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="page-content flex flex-col gap-4 pb-6">
      <PageHeader
        title="Watchlist"
        icon={Eye}
        subtitle={
          freshness.isLive && feedLive
            ? 'Live prices refresh every 5 seconds. Select a row to open the chart, or trade and set alerts inline.'
            : 'Prices are not updating right now. Select a row to open the chart.'
        }
        badge={<StaleDataNotice failed={freshness.failed} what={freshness.what} />}
      />

      <div className="px-4 sm:px-6">
        <Section
          title="Tracked symbols"
          description={`${enrichedItems.length} of ${AVAILABLE_SYMBOLS.length} available instruments`}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="wl-add" className="sr-only">Add a symbol to your watchlist</label>
              <select
                id="wl-add"
                value={addSymbol}
                onChange={(e) => setAddSymbol(e.target.value)}
                className="min-h-[44px] rounded-lg border border-[#1e2d3d] bg-[#111827] px-3
                           text-[12.5px] text-slate-200 cursor-pointer
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                <option value="">Add symbol…</option>
                {AVAILABLE_SYMBOLS.filter((sym) => !items.find((i) => i.symbol === sym)).map((sym) => (
                  <option key={sym} value={sym}>{sym}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={handleAdd}
                disabled={!addSymbol || adding}
                className="inline-flex min-h-[44px] items-center rounded-lg bg-sky-500/15 px-4
                           text-[12.5px] font-semibold text-sky-300 ring-1 ring-inset ring-sky-500/40
                           cursor-pointer transition-colors duration-150 hover:bg-sky-500/25
                           disabled:cursor-not-allowed disabled:opacity-40
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                {adding ? 'Adding…' : 'Add'}
              </button>
            </div>
          }
        >
          {error && (
            <p role="alert" className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-[12.5px] text-red-300
                                       ring-1 ring-inset ring-red-500/30">
              {error}
            </p>
          )}

          {loading ? (
            <EmptyState title="Loading your watchlist…" compact />
          ) : (
            <DataTable
              caption="Watchlist — live bid, ask, mid and 24-hour change for each tracked symbol"
              columns={columns}
              data={enrichedItems}
              rowKey={(r) => r.symbol}
              onRowClick={(r) => navigate('/ai-chart', { state: { symbol: r.symbol } })}
              empty={
                <EmptyState
                  title="Your watchlist is empty"
                  description="Add an instrument to follow its price, open its chart, and trade or set alerts from the row."
                  icon={Eye}
                  links={[
                    { label: 'Browse signals', href: '/signals' },
                    { label: 'Open the ticket', href: '/trade' },
                  ]}
                />
              }
            />
          )}
        </Section>

        <RelatedPages
          links={[
            { to: '/trade',    label: 'Trading ticket', hint: 'Place an order on a tracked symbol', icon: Zap },
            { to: '/signals',  label: 'Signal feed',    hint: 'What the model sees right now',      icon: Radio },
            { to: '/ai-chart', label: 'Charts',         hint: 'Full chart with indicators',         icon: LineChart },
            { to: '/alerts',   label: 'Price alerts',   hint: 'Alerts you have already set',        icon: BellPlus },
            { to: '/journal',  label: 'Trade journal',  hint: 'How these symbols have traded for you', icon: BookOpen },
          ]}
        />
      </div>
    </div>
  );
};

export default WatchlistPage;
