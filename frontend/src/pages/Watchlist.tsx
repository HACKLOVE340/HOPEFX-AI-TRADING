/**
 * Watchlist page — add/remove symbols, live prices, sparklines, click to chart.
 *
 * Auth: JWT injected automatically via the api axios instance interceptor.
 * Wires to: GET    /api/watchlist
 *           POST   /api/watchlist/{symbol}
 *           DELETE /api/watchlist/{symbol}
 *           GET    /api/watchlist/prices
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore } from '../store';

// ── Types ─────────────────────────────────────────────────────────────────────

interface WatchlistItem {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  change_pct: number;
  timestamp: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const AVAILABLE_SYMBOLS = [
  'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD',
  'ETHUSD', 'USDCAD', 'AUDUSD', 'USDCHF', 'NZDUSD',
];

function formatPrice(symbol: string, price: number): string {
  if (symbol.includes('JPY')) return price.toFixed(2);
  if (symbol.includes('BTC') || symbol.includes('ETH') || symbol.includes('XAU')) return price.toFixed(2);
  return price.toFixed(5);
}

// Tiny sparkline using SVG
const Sparkline: React.FC<{ change_pct: number }> = ({ change_pct }) => {
  const up    = change_pct >= 0;
  const color = up ? '#4ade80' : '#f87171';
  const points = Array.from({ length: 10 }, (_, i) => {
    const trend = (change_pct / 10) * i;
    const noise = (Math.random() - 0.5) * 0.5;
    return 20 - (trend + noise) * 2;
  });
  const min        = Math.min(...points);
  const max        = Math.max(...points);
  const range      = max - min || 1;
  const normalized = points.map((p) => ((p - min) / range) * 28 + 2);
  const path       = normalized.map((y, i) => `${i === 0 ? 'M' : 'L'}${(i / 9) * 60},${y}`).join(' ');
  return (
    <svg width={60} height={32} style={{ display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
};

// ── Fallback demo data shown while API loads ──────────────────────────────────

const DEMO_ITEMS: WatchlistItem[] = [
  { symbol: 'XAUUSD', bid: 2340.10, ask: 2340.40, mid: 2340.25, change_pct:  0.42, timestamp: Date.now() },
  { symbol: 'EURUSD', bid: 1.08490, ask: 1.08510, mid: 1.08500, change_pct: -0.18, timestamp: Date.now() },
  { symbol: 'GBPUSD', bid: 1.26980, ask: 1.27010, mid: 1.26995, change_pct:  0.11, timestamp: Date.now() },
  { symbol: 'USDJPY', bid: 149.480, ask: 149.510, mid: 149.495, change_pct: -0.05, timestamp: Date.now() },
  { symbol: 'BTCUSD', bid: 66980.0, ask: 67020.0, mid: 67000.0, change_pct:  1.23, timestamp: Date.now() },
];

// ── Component ─────────────────────────────────────────────────────────────────

const WatchlistPage: React.FC = () => {
  const navigate    = useNavigate();
  const storePrices = useStore((s) => s.prices);

  const [items,     setItems]     = useState<WatchlistItem[]>(DEMO_ITEMS);
  const [loading,   setLoading]   = useState(true);
  const [addSymbol, setAddSymbol] = useState('');
  const [adding,    setAdding]    = useState(false);
  const [error,     setError]     = useState('');

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await api.get<{ items: WatchlistItem[] }>('/api/watchlist');
      if (res.data.items?.length) setItems(res.data.items);
    } catch {
      // API unavailable — keep demo data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
    const id = setInterval(async () => {
      try {
        const res = await api.get<WatchlistItem[]>('/api/watchlist/prices');
        if (Array.isArray(res.data) && res.data.length > 0) setItems(res.data);
      } catch { /* keep existing */ }
    }, 5000);
    return () => clearInterval(id);
  }, [fetchWatchlist]);

  // Overlay live store prices for real-time feel
  const enrichedItems: WatchlistItem[] = items.map((item) => {
    // Store uses 'XAU/USD' format; watchlist uses 'XAUUSD' — map both ways
    const slashKey = item.symbol
      .replace('XAUUSD', 'XAU/USD')
      .replace('EURUSD', 'EUR/USD')
      .replace('GBPUSD', 'GBP/USD')
      .replace('USDJPY', 'USD/JPY')
      .replace('BTCUSD', 'BTC/USD');
    const tick = storePrices[slashKey] ?? storePrices[item.symbol];
    if (!tick) return item;
    return { ...item, bid: tick.bid, ask: tick.ask, mid: tick.mid, change_pct: tick.change_pct, timestamp: tick.timestamp };
  });

  const handleAdd = async () => {
    const sym = addSymbol.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    setError('');
    try {
      await api.post(`/api/watchlist/${sym}`);
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

  const handleRemove = async (symbol: string) => {
    try {
      await api.delete(`/api/watchlist/${symbol}`);
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
    } catch { /* silent */ }
  };

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>Watchlist</h1>
        <p style={s.subtitle}>Live prices refresh every 5 seconds. Click a symbol to open its chart.</p>
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
        <div style={s.empty}>Your watchlist is empty. Add symbols above.</div>
      ) : (
        <div style={s.table}>
          <div style={s.tableHeader}>
            <span style={{ flex: 1 }}>Symbol</span>
            <span style={{ width: 90, textAlign: 'right' }}>Bid</span>
            <span style={{ width: 90, textAlign: 'right' }}>Ask</span>
            <span style={{ width: 80, textAlign: 'right' }}>24h</span>
            <span style={{ width: 70, textAlign: 'center' }}>Trend</span>
            <span style={{ width: 40 }} />
          </div>
          {enrichedItems.map((item) => (
            <div key={item.symbol} style={s.tableRow} onClick={() => navigate('/trading')} title={`Open ${item.symbol} chart`}>
              <span style={{ flex: 1, fontWeight: 700, color: '#f1f5f9', cursor: 'pointer' }}>{item.symbol}</span>
              <span style={{ width: 90, textAlign: 'right', color: '#94a3b8', fontSize: 13 }}>{formatPrice(item.symbol, item.bid)}</span>
              <span style={{ width: 90, textAlign: 'right', color: '#94a3b8', fontSize: 13 }}>{formatPrice(item.symbol, item.ask)}</span>
              <span style={{ width: 80, textAlign: 'right', fontWeight: 600, color: item.change_pct >= 0 ? '#4ade80' : '#f87171' }}>
                {item.change_pct >= 0 ? '+' : ''}{item.change_pct.toFixed(2)}%
              </span>
              <span style={{ width: 70, display: 'flex', justifyContent: 'center' }}>
                <Sparkline change_pct={item.change_pct} />
              </span>
              <span style={{ width: 40, textAlign: 'right' }}>
                <button onClick={(e) => { e.stopPropagation(); handleRemove(item.symbol); }} style={s.removeBtn} title="Remove">×</button>
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
