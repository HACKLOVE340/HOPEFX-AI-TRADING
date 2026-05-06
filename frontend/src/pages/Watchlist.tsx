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
import { Link } from 'react-router-dom';
import { watchlistApi, api } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader, EmptyState } from '../components';
import { useToast } from '../components/Toast';
import { useFlashHighlight } from '../hooks/useFlashHighlight';

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
  const up    = last >= first;
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

// ── Asset class grouping ──────────────────────────────────────────────────────

const ASSET_CLASS: Record<string, string> = {
  EURUSD: 'Forex', GBPUSD: 'Forex', USDJPY: 'Forex', AUDUSD: 'Forex',
  USDCAD: 'Forex', USDCHF: 'Forex', NZDUSD: 'Forex', EURGBP: 'Forex',
  XAUUSD: 'Metals', XAGUSD: 'Metals',
  BTCUSD: 'Crypto', ETHUSD: 'Crypto',
  US30: 'Indices', SPX500: 'Indices', NAS100: 'Indices', GER40: 'Indices',
  USOIL: 'Commodities', UKOIL: 'Commodities',
};

function getAssetClass(sym: string): string {
  return ASSET_CLASS[sym] ?? 'Other';
}

// ── Inline alert creation modal ───────────────────────────────────────────────

interface InlineAlertModalProps {
  symbol: string;
  currentPrice: number;
  onClose: () => void;
  onCreated: () => void;
}

const InlineAlertModal: React.FC<InlineAlertModalProps> = ({ symbol, currentPrice, onClose, onCreated }) => {
  const toast = useToast();
  const [price, setPrice]     = useState(String(currentPrice.toFixed(4)));
  const [condition, setCond]  = useState<'above' | 'below'>('above');
  const [channel, setChannel] = useState<'email' | 'discord' | 'telegram'>('email');
  const [saving, setSaving]   = useState(false);

  const handleCreate = async () => {
    setSaving(true);
    try {
      await api.post('/alerts/', {
        symbol,
        condition,
        price: parseFloat(price),
        channels: [channel],
        message: `${symbol} ${condition} ${price}`,
      });
      toast.success(`Alert set: ${symbol} ${condition} ${price}`);
      onCreated();
      onClose();
    } catch {
      toast.error('Failed to create alert.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)' }} onClick={onClose}>
      <div style={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 12, padding: 24, width: 340, display: 'flex', flexDirection: 'column', gap: 14 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 700, color: '#f1f5f9', fontSize: 15 }}>🔔 Create Alert — {symbol}</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', fontSize: 18, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['above', 'below'] as const).map((c) => (
            <button key={c} onClick={() => setCond(c)} style={{ flex: 1, padding: '6px 0', borderRadius: 6, border: `1px solid ${condition === c ? '#3b82f6' : '#1e2d3d'}`, background: condition === c ? 'rgba(59,130,246,0.15)' : 'transparent', color: condition === c ? '#60a5fa' : '#64748b', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              {c === 'above' ? '▲ Above' : '▼ Below'}
            </button>
          ))}
        </div>
        <input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          step="0.0001"
          style={{ background: '#0a0f1a', border: '1px solid #1e2d3d', borderRadius: 6, color: '#f1f5f9', fontSize: 14, padding: '8px 10px', outline: 'none', fontFamily: 'monospace' }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          {(['email', 'discord', 'telegram'] as const).map((ch) => (
            <button key={ch} onClick={() => setChannel(ch)} style={{ flex: 1, padding: '5px 0', borderRadius: 6, border: `1px solid ${channel === ch ? '#fbbf24' : '#1e2d3d'}`, background: channel === ch ? 'rgba(251,191,36,0.1)' : 'transparent', color: channel === ch ? '#fbbf24' : '#64748b', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>
              {ch}
            </button>
          ))}
        </div>
        <button onClick={handleCreate} disabled={saving || !price} style={{ padding: '9px 0', background: '#1d4ed8', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', opacity: saving ? 0.6 : 1 }}>
          {saving ? 'Creating…' : 'Create Alert'}
        </button>
      </div>
    </div>
  );
};

// ── Watchlist row with flash highlight ────────────────────────────────────────

const WatchlistRow: React.FC<{
  item: WatchlistItem;
  onRemove: (sym: string) => void;
  onAlert: (sym: string, price: number) => void;
  dragHandleProps: React.HTMLAttributes<HTMLSpanElement>;
  isDragging: boolean;
}> = ({ item, onRemove, onAlert, dragHandleProps, isDragging }) => {
  const flash = useFlashHighlight(item.mid);
  const spread = item.ask - item.bid;
  const spreadPips = item.symbol.includes('JPY') ? spread * 100 : spread * 10000;

  return (
    <div
      style={{
        ...s.tableRow,
        background: isDragging ? '#1e2d3d' : (flash !== 'transparent' ? flash : 'transparent'),
        transition: 'background 0.4s ease',
        opacity: isDragging ? 0.8 : 1,
        cursor: isDragging ? 'grabbing' : 'default',
      }}
    >
      <span {...dragHandleProps} style={{ color: '#334155', cursor: 'grab', fontSize: 14, padding: '0 6px', userSelect: 'none' }} title="Drag to reorder">⠿</span>
      <Link
        to="/ai-chart"
        state={{ symbol: item.symbol }}
        style={{ flex: 1, fontWeight: 700, color: '#f1f5f9', display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}
        title={`Open ${item.symbol} chart`}
      >
        {item.symbol}
        <span style={{ fontSize: 9, color: '#475569', background: '#0f172a', border: '1px solid #1e2d3d', borderRadius: 3, padding: '1px 4px' }}>{getAssetClass(item.symbol)}</span>
        <span style={{ fontSize: 10, color: '#475569' }}>↗</span>
      </Link>
      <span style={{ width: 90, textAlign: 'right', color: '#f87171', fontSize: 13, fontWeight: 600 }}>{formatPrice(item.symbol, item.bid)}</span>
      <span style={{ width: 90, textAlign: 'right', color: '#4ade80', fontSize: 13, fontWeight: 600 }}>{formatPrice(item.symbol, item.ask)}</span>
      <span style={{ width: 80, textAlign: 'right', color: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }} title="Bid-ask spread">
        {spreadPips.toFixed(1)}p
      </span>
      <span style={{ width: 100, textAlign: 'right', color: '#f8fafc', fontSize: 13, fontWeight: 700 }}>{formatPrice(item.symbol, item.mid)}</span>
      <span style={{ width: 80, textAlign: 'right', fontWeight: 600, color: item.change_pct >= 0 ? '#4ade80' : '#f87171' }}>
        {item.change_pct >= 0 ? '+' : ''}{item.change_pct.toFixed(2)}%
      </span>
      <span style={{ width: 70, display: 'flex', justifyContent: 'center' }}>
        <Sparkline history={item.history} />
      </span>
      <span style={{ width: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
        <Link
          to="/trade"
          state={{ signal: { symbol: item.symbol.slice(0, 3) + '/' + item.symbol.slice(3) } }}
          style={{ background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 5, color: '#60a5fa', fontSize: 11, fontWeight: 700, padding: '3px 8px', textDecoration: 'none' }}
          title={`Trade ${item.symbol}`}
        >
          ⚡
        </Link>
        <button
          onClick={() => onAlert(item.symbol, item.mid)}
          style={{ background: 'transparent', border: 'none', color: '#fbbf24', fontSize: 14, cursor: 'pointer', padding: '0 2px' }}
          title={`Set alert for ${item.symbol}`}
        >
          🔔
        </button>
        <button onClick={() => onRemove(item.symbol)} style={s.removeBtn} title="Remove from watchlist">×</button>
      </span>
    </div>
  );
};

// ── Component ─────────────────────────────────────────────────────────────────

const WatchlistPage: React.FC = () => {
  const storePrices = useStore((s) => s.prices);
  const toast       = useToast();

  const [items,       setItems]       = useState<WatchlistItem[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [addSymbol,   setAddSymbol]   = useState('');
  const [adding,      setAdding]      = useState(false);
  const [error,       setError]       = useState('');
  const [groupByAsset, setGroupByAsset] = useState(false);
  const [alertModal,  setAlertModal]  = useState<{ symbol: string; price: number } | null>(null);
  const dragItem    = useRef<number | null>(null);
  const dragOverItem = useRef<number | null>(null);

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
  // Store uses 'XAU/USD' format; watchlist uses 'XAUUSD' — normalise both ways.
  const enrichedItems: WatchlistItem[] = items.map((item) => {
    const slashKey = item.symbol
      .replace('XAUUSD', 'XAU/USD')
      .replace('EURUSD', 'EUR/USD')
      .replace('GBPUSD', 'GBP/USD')
      .replace('USDJPY', 'USD/JPY')
      .replace('BTCUSD', 'BTC/USD');
    const tick = storePrices[slashKey] ?? storePrices[item.symbol];
    if (!tick) return item;
    // Append the new mid to history so the sparkline reflects real ticks
    const updatedHistory = [...item.history, tick.mid].slice(-60);
    return {
      ...item,
      bid: tick.bid,
      ask: tick.ask,
      mid: tick.mid,
      change_pct: tick.change_pct,
      timestamp: tick.timestamp,
      history: updatedHistory,
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

  const handleRemove = async (symbol: string) => {
    try {
      await watchlistApi.remove(symbol);
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
      toast.success(`${symbol} removed from watchlist.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : `Failed to remove ${symbol}.`;
      setError(msg);
      toast.error(msg);
    }
  };

  // ── Drag-to-reorder ──────────────────────────────────────────────────────
  const handleDragStart = (index: number) => { dragItem.current = index; };
  const handleDragEnter = (index: number) => { dragOverItem.current = index; };
  const handleDragEnd   = () => {
    if (dragItem.current === null || dragOverItem.current === null) return;
    if (dragItem.current === dragOverItem.current) return;
    const reordered = [...items];
    const [moved] = reordered.splice(dragItem.current, 1);
    reordered.splice(dragOverItem.current, 0, moved!);
    setItems(reordered);
    dragItem.current = null;
    dragOverItem.current = null;
    // Persist order to backend (best-effort)
    watchlistApi.reorder?.(reordered.map((i) => i.symbol)).catch(() => {});
  };

  // Group items by asset class if enabled
  const displayItems = groupByAsset
    ? [...enrichedItems].sort((a, b) => getAssetClass(a.symbol).localeCompare(getAssetClass(b.symbol)))
    : enrichedItems;

  const groups = groupByAsset
    ? Array.from(new Set(displayItems.map((i) => getAssetClass(i.symbol))))
    : ['All'];

  return (
    <div style={s.page}>
      {alertModal && (
        <InlineAlertModal
          symbol={alertModal.symbol}
          currentPrice={alertModal.price}
          onClose={() => setAlertModal(null)}
          onCreated={() => setAlertModal(null)}
        />
      )}

      <PageHeader
        title="Watchlist"
        icon="👁️"
        subtitle="Live prices. Drag to reorder. Click symbol to chart."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Watchlist' },
        ]}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              onClick={() => setGroupByAsset((g) => !g)}
              style={{ padding: '6px 12px', background: groupByAsset ? 'rgba(139,92,246,0.2)' : 'rgba(139,92,246,0.08)', border: `1px solid ${groupByAsset ? '#7c3aed' : 'rgba(139,92,246,0.3)'}`, borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
            >
              {groupByAsset ? '⊞ Ungrouped' : '⊟ Group by Asset'}
            </button>
            <Link to="/ai-chart" style={{ padding: '6px 12px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>📈 Charts</Link>
            <Link to="/alerts"   style={{ padding: '6px 12px', background: 'rgba(251,191,36,0.1)',  border: '1px solid rgba(251,191,36,0.3)',  borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>🔔 Alerts</Link>
            <Link to="/trade"    style={{ padding: '6px 12px', background: 'rgba(34,197,94,0.12)',  border: '1px solid rgba(34,197,94,0.3)',   borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>⚡ Trade</Link>
          </div>
        }
      />

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
        <div style={{ ...s.table, padding: 0 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} style={{ height: 52, borderBottom: '1px solid #1e293b', background: i % 2 === 0 ? '#0d1421' : '#0a0f1a', animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
      ) : enrichedItems.length === 0 ? (
        <EmptyState
          icon="👁"
          title="Your watchlist is empty"
          description="Track live prices for your favourite instruments. Use the dropdown above to add symbols."
          action={
            <div style={{ display: 'flex', gap: 8 }}>
              <Link to="/ai-chart" style={{ padding: '8px 16px', background: '#3b82f6', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, textDecoration: 'none', display: 'inline-block' }}>📈 Browse Charts</Link>
              <Link to="/signals"  style={{ padding: '8px 16px', background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', fontSize: 13, textDecoration: 'none', display: 'inline-block' }}>📡 Signal Feed</Link>
            </div>
          }
        />
      ) : (
        <div style={s.table}>
          {/* Table header */}
          <div style={{ ...s.tableHeader, paddingLeft: 28 }}>
            <span style={{ flex: 1 }}>Symbol</span>
            <span style={{ width: 90, textAlign: 'right' }}>Bid</span>
            <span style={{ width: 90, textAlign: 'right' }}>Ask</span>
            <span style={{ width: 80, textAlign: 'right' }}>Spread</span>
            <span style={{ width: 100, textAlign: 'right' }}>Mid</span>
            <span style={{ width: 80, textAlign: 'right' }}>24h</span>
            <span style={{ width: 70, textAlign: 'center' }}>Trend</span>
            <span style={{ width: 150, textAlign: 'center' }}>Actions</span>
          </div>

          {/* Grouped or flat rows */}
          {groups.map((group) => {
            const groupItems = groupByAsset
              ? displayItems.filter((i) => getAssetClass(i.symbol) === group)
              : displayItems;
            return (
              <div key={group}>
                {groupByAsset && (
                  <div style={{ padding: '6px 12px', background: '#0a0f1a', borderBottom: '1px solid #1e2d3d', fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    {group} ({groupItems.length})
                  </div>
                )}
                {groupItems.map((item, idx) => {
                  const globalIdx = displayItems.indexOf(item);
                  return (
                    <div
                      key={item.symbol}
                      draggable={!groupByAsset}
                      onDragStart={() => handleDragStart(globalIdx)}
                      onDragEnter={() => handleDragEnter(globalIdx)}
                      onDragEnd={handleDragEnd}
                      onDragOver={(e) => e.preventDefault()}
                    >
                      <WatchlistRow
                        item={item}
                        onRemove={handleRemove}
                        onAlert={(sym, price) => setAlertModal({ symbol: sym, price })}
                        dragHandleProps={{
                          onMouseDown: () => {},
                        }}
                        isDragging={false}
                      />
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {/* Cross-links footer */}
      {enrichedItems.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
          {[
            { label: '📊 Portfolio', path: '/portfolio' },
            { label: '📈 AI Charts', path: '/ai-chart' },
            { label: '📡 Signals',   path: '/signals' },
            { label: '📓 Journal',   path: '/journal' },
          ].map(({ label, path }) => (
            <Link key={path} to={path} style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', transition: 'all 0.15s' }}>
              {label}
            </Link>
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
