/**
 * Watchlist page — add/remove symbols, live prices, sparklines, click to chart.
 *
 * Wires to: GET    /api/watchlist?user_id=...
 *           POST   /api/watchlist/{symbol}?user_id=...
 *           DELETE /api/watchlist/{symbol}?user_id=...
 *           GET    /api/watchlist/prices?user_id=...
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store/useStore';

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

// Tiny sparkline using SVG — last 10 random points around current price
const Sparkline: React.FC<{ change_pct: number }> = ({ change_pct }) => {
  const up = change_pct >= 0;
  const color = up ? '#4ade80' : '#f87171';
  // Generate 10 points trending in the direction of change_pct
  const points = Array.from({ length: 10 }, (_, i) => {
    const trend = (change_pct / 10) * i;
    const noise = (Math.random() - 0.5) * 0.5;
    return 20 - (trend + noise) * 2;
  });
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const normalized = points.map((p) => ((p - min) / range) * 28 + 2);
  const path = normalized.map((y, i) => `${i === 0 ? 'M' : 'L'}${(i / 9) * 60},${y}`).join(' ');
  return (
    <svg width={60} height={32} style={{ display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
};

// ── Component ─────────────────────────────────────────────────────────────────

const WatchlistPage: React.FC = () => {
  const token  = useStore((s) => s.token);
  const user   = useStore((s) => s.user);
  const userId = user?.id ?? 'demo';
  const navigate = useNavigate();

  const [items, setItems]       = useState<WatchlistItem[]>([]);
  const [loading, setLoading]   = useState(true);
  const [addSymbol, setAddSymbol] = useState('');
  const [adding, setAdding]     = useState(false);
  const [error, setError]       = useState('');

  const headers = { ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const qs = `?user_id=${userId}`;

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch(`/api/watchlist${qs}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items ?? []);
      }
    } catch { /* silent */ }
    setLoading(false);
  }, [userId]);

  // Refresh prices every 5s
  useEffect(() => {
    fetchWatchlist();
    const id = setInterval(async () => {
      try {
        const res = await fetch(`/api/watchlist/prices${qs}`, { headers });
        if (res.ok) setItems(await res.json());
      } catch { /* silent */ }
    }, 5000);
    return () => clearInterval(id);
  }, [fetchWatchlist]);

  const handleAdd = async () => {
    const sym = addSymbol.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    setError('');
    try {
      const res = await fetch(`/api/watchlist/${sym}${qs}`, { method: 'POST', headers });
      if (res.status === 409) { setError(`${sym} is already in your watchlist`); }
      else if (!res.ok) { setError(`Failed to add ${sym}`); }
      else { setAddSymbol(''); await fetchWatchlist(); }
    } catch { setError('Network error'); }
    setAdding(false);
  };

  const handleRemove = async (symbol: string) => {
    try {
      await fetch(`/api/watchlist/${symbol}${qs}`, { method: 'DELETE', headers });
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
    } catch { /* silent */ }
  };

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Watchlist</h1>
          <p style={s.subtitle}>Live prices refresh every 5 seconds. Click a symbol to open its chart.</p>
        </div>
      </div>

      {/* Add symbol */}
      <div style={s.addRow}>
        <select
          value={addSymbol}
          onChange={(e) => setAddSymbol(e.target.value)}
          style={s.select}
        >
          <option value="">Add symbol…</option>
          {AVAILABLE_SYMBOLS.filter((s) => !items.find((i) => i.symbol === s)).map((sym) => (
            <option key={sym} value={sym}>{sym}</option>
          ))}
        </select>
        <button onClick={handleAdd} disabled={!addSymbol || adding} style={{ ...s.addBtn, opacity: !addSymbol ? 0.5 : 1 }}>
          {adding ? '…' : '+ Add'}
        </button>
        {error && <span style={{ color: '#f87171', fontSize: 13 }}>{error}</span>}
      </div>

      {/* Watchlist table */}
      {loading ? (
        <div style={s.empty}>Loading…</div>
      ) : items.length === 0 ? (
        <div style={s.empty}>Your watchlist is empty. Add symbols above.</div>
      ) : (
        <div style={s.table}>
          <div style={s.tableHeader}>
            <span style={{ flex: 1 }}>Symbol</span>
            <span style={{ width: 80, textAlign: 'right' }}>Bid</span>
            <span style={{ width: 80, textAlign: 'right' }}>Ask</span>
            <span style={{ width: 80, textAlign: 'right' }}>24h</span>
            <span style={{ width: 70, textAlign: 'center' }}>Trend</span>
            <span style={{ width: 40 }}></span>
          </div>
          {items.map((item) => (
            <div
              key={item.symbol}
              style={s.tableRow}
              onClick={() => navigate('/trading')}
              title={`Open ${item.symbol} chart`}
            >
              <span style={{ flex: 1, fontWeight: 700, color: '#f1f5f9', cursor: 'pointer' }}>
                {item.symbol}
              </span>
              <span style={{ width: 80, textAlign: 'right', color: '#94a3b8', fontSize: 13 }}>
                {formatPrice(item.symbol, item.bid)}
              </span>
              <span style={{ width: 80, textAlign: 'right', color: '#94a3b8', fontSize: 13 }}>
                {formatPrice(item.symbol, item.ask)}
              </span>
              <span style={{
                width: 80, textAlign: 'right', fontWeight: 600,
                color: item.change_pct >= 0 ? '#4ade80' : '#f87171',
              }}>
                {item.change_pct >= 0 ? '+' : ''}{item.change_pct.toFixed(2)}%
              </span>
              <span style={{ width: 70, display: 'flex', justifyContent: 'center' }}>
                <Sparkline change_pct={item.change_pct} />
              </span>
              <span style={{ width: 40, textAlign: 'right' }}>
                <button
                  onClick={(e) => { e.stopPropagation(); handleRemove(item.symbol); }}
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

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:        { padding: 24, maxWidth: 800, margin: '0 auto' },
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
