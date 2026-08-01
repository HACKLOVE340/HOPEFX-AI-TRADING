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
import { useStore } from '../store';
import { extractApiError, toSlashSymbol } from '../lib/utils';

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

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await watchlistApi.list() as { data: { items: Array<Omit<WatchlistItem, 'history'> & { history?: number[] }> } };
      if (!mountedRef.current) return;
      if (res.data.items?.length) {
        setItems(res.data.items.map(normalise));
      }
    } catch {
      // API unavailable — show empty list; no fake data
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
      } catch { /* keep existing prices */ }
    }, 5000);
    return () => clearInterval(id);
  }, [fetchWatchlist]);

  // Overlay live store prices for real-time feel.
  // Store keys on 'XAU/USD'; the watchlist stores 'XAUUSD'. The mapping used to
  // be a hardcoded chain of five .replace() calls against ten offered symbols,
  // so half of them never matched a feed key and simply showed no live price.
  const enrichedItems: WatchlistItem[] = items.map((item) => {
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

  // Live tick history per symbol, accumulated across renders. Capped at 60
  // points, which is what the sparkline draws.
  const [tickHistory, setTickHistory] = useState<Record<string, number[]>>({});

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

  return (
    <div className="page-content">
      <div style={{ ...s.header, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={s.title}>Watchlist</h1>
          <p style={s.subtitle}>Live prices refresh every 5 seconds. Click a symbol to open its chart.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => navigate('/trade')}
            style={{ padding: '6px 13px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            ⚡ Trade
          </button>
          <button onClick={() => navigate('/signals')}
            style={{ padding: '6px 13px', background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            📡 Signals
          </button>
          <button onClick={() => navigate('/alerts')}
            style={{ padding: '6px 13px', background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.35)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🔔 Alerts
          </button>
        </div>
      </div>

      <div style={s.addRow}>
        <select value={addSymbol} onChange={(e) => setAddSymbol(e.target.value)} style={s.select}>
          <option value="">Add symbol…</option>
          {AVAILABLE_SYMBOLS.filter((sym) => !items.find((i) => i.symbol === sym)).map((sym) => (
            <option key={sym} value={sym}>{sym}</option>
          ))}
        </select>
        <button onClick={handleAdd} disabled={!addSymbol || adding} style={{ ...s.addBtn, opacity: !addSymbol ? 0.5 : 1 }}>
          {adding ? '…' : '+ Add'}
        </button>
        {error && <span style={{ color: '#f87171', fontSize: 13 }}>{error}</span>}
      </div>

      {loading ? (
        <div style={s.empty}>Loading…</div>
      ) : enrichedItems.length === 0 ? (
        <div style={s.empty}>Your watchlist is empty. Use the dropdown above to start tracking.</div>
      ) : (
        <div style={s.table}>
          <div style={s.tableHeader}>
            <span style={{ flex: 1 }}>Symbol</span>
            <span style={{ width: 90, textAlign: 'right' }}>Bid</span>
            <span style={{ width: 90, textAlign: 'right' }}>Ask</span>
            <span style={{ width: 100, textAlign: 'right' }}>Mid</span>
            <span style={{ width: 80, textAlign: 'right' }}>24h</span>
            <span style={{ width: 70, textAlign: 'center' }}>Trend</span>
            <span style={{ width: 140, textAlign: 'center' }}>Actions</span>
          </div>
          {enrichedItems.map((item) => (
            <div key={item.symbol} style={s.tableRow}>
              <span
                style={{ flex: 1, fontWeight: 700, color: '#f1f5f9', cursor: 'pointer' }}
                onClick={() => navigate('/ai-chart', { state: { symbol: item.symbol } })}
                title={`Open ${item.symbol} chart`}
              >
                {item.symbol}
              </span>
              <span style={{ width: 90, textAlign: 'right', color: '#f87171', fontSize: 13, fontWeight: 600 }}>{formatPrice(item.symbol, item.bid)}</span>
              <span style={{ width: 90, textAlign: 'right', color: '#4ade80', fontSize: 13, fontWeight: 600 }}>{formatPrice(item.symbol, item.ask)}</span>
              <span style={{ width: 100, textAlign: 'right', color: '#f8fafc', fontSize: 13, fontWeight: 700 }}>{formatPrice(item.symbol, item.mid)}</span>
              <span style={{ width: 80, textAlign: 'right', fontWeight: 600, color: (item.change_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                {Number.isFinite(item.change_pct) ? `${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(2)}%` : '—'}
              </span>
              <span style={{ width: 70, display: 'flex', justifyContent: 'center' }}>
                <Sparkline history={item.history} />
              </span>
              <span style={{ width: 140, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                <button
                  onClick={() => navigate('/trade', { state: { signal: { symbol: toSlashSymbol(item.symbol) } } })}
                  style={{ background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 5, color: '#60a5fa', fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '3px 8px' }}
                  title={`Trade ${item.symbol}`}
                >
                  ⚡ Trade
                </button>
                <button
                  onClick={() => navigate('/alerts', { state: { symbol: item.symbol } })}
                  style={{ background: 'transparent', border: 'none', color: '#fbbf24', fontSize: 14, cursor: 'pointer', padding: '0 2px' }}
                  title={`Set alert for ${item.symbol}`}
                >
                  🔔
                </button>
                <button
                  onClick={() => handleRemove(item.symbol)}
                  style={s.removeBtn}
                  title="Remove from watchlist"
                >
                  ×
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page:        { padding: 24, maxWidth: 860, margin: '0 auto' },
  header:      { marginBottom: 20 },
  title:       { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:    { fontSize: 14, color: '#64748b', margin: 0 },
  addRow:      { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 },
  select:      { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14 },
  addBtn:      { background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '8px 16px' },
  table:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, overflow: 'hidden' },
  tableHeader: { display: 'flex', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid #334155', fontSize: 12, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 },
  tableRow:    { display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid #1e293b', cursor: 'pointer', transition: 'background 0.1s' },
  removeBtn:   { background: 'transparent', border: 'none', color: '#475569', fontSize: 18, cursor: 'pointer', lineHeight: 1, padding: '0 4px' },
  empty:       { textAlign: 'center', color: '#475569', padding: 40 },
};

export default WatchlistPage;
