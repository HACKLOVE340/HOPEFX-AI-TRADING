/**
 * Trading page — live candlestick chart, order panel, positions, risk metrics.
 *
 * Wires to: GET /api/trading/ohlcv/{symbol}
 *           GET /api/trading/positions
 *           GET /api/trading/account
 *           POST /api/trading/orders
 *           DELETE /api/trading/positions/{id}
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData } from 'lightweight-charts';
import { useStore, selectUser } from '../store';
import { tradingApi } from '../hooks/useApi';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Position {
  id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  opened_at: string;
}

interface AccountInfo {
  balance: number;
  equity: number;
  margin_used: number;
  daily_pnl: number;
  open_risk_pct: number;
}

// ── Order Panel ───────────────────────────────────────────────────────────────

const OrderPanel: React.FC<{ symbol: string; bid: number; ask: number; onOrderPlaced: () => void }> = ({
  symbol, bid, ask, onOrderPlaced,
}) => {
  const [side, setSide]       = useState<'buy' | 'sell'>('buy');
  const [size, setSize]       = useState('0.01');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [placing, setPlacing] = useState(false);
  const [msg, setMsg]         = useState('');

  const handlePlace = async () => {
    setPlacing(true);
    setMsg('');
    try {
      await tradingApi.placeOrder({
        symbol,
        side,
        size: parseFloat(size),
        order_type: 'market',
        stop_loss: stopLoss ? parseFloat(stopLoss) : undefined,
        take_profit: takeProfit ? parseFloat(takeProfit) : undefined,
      });
      setMsg('Order placed');
      onOrderPlaced();
    } catch {
      setMsg('Order failed');
    }
    setPlacing(false);
  };

  return (
    <div style={s.card}>
      <h3 style={s.cardTitle}>Place Order</h3>
      <div style={s.sideBtns}>
        <button
          onClick={() => setSide('buy')}
          style={{ ...s.sideBtn, ...(side === 'buy' ? s.buyActive : {}) }}
        >
          BUY {ask > 0 ? ask.toFixed(2) : '—'}
        </button>
        <button
          onClick={() => setSide('sell')}
          style={{ ...s.sideBtn, ...(side === 'sell' ? s.sellActive : {}) }}
        >
          SELL {bid > 0 ? bid.toFixed(2) : '—'}
        </button>
      </div>

      <label style={s.label}>Lots</label>
      <input
        type="number"
        value={size}
        onChange={(e) => setSize(e.target.value)}
        step="0.01"
        min="0.01"
        style={s.input}
      />

      <label style={s.label}>Stop Loss</label>
      <input
        type="number"
        value={stopLoss}
        onChange={(e) => setStopLoss(e.target.value)}
        placeholder="Optional"
        style={s.input}
      />

      <label style={s.label}>Take Profit</label>
      <input
        type="number"
        value={takeProfit}
        onChange={(e) => setTakeProfit(e.target.value)}
        placeholder="Optional"
        style={s.input}
      />

      <button
        onClick={handlePlace}
        disabled={placing}
        style={{
          ...s.placeBtn,
          background: side === 'buy' ? '#16a34a' : '#dc2626',
          opacity: placing ? 0.6 : 1,
        }}
      >
        {placing ? 'Placing…' : `${side === 'buy' ? 'Buy' : 'Sell'} ${symbol}`}
      </button>
      {msg && <div style={{ fontSize: 13, color: msg === 'Order placed' ? '#4ade80' : '#f87171', marginTop: 8 }}>{msg}</div>}
    </div>
  );
};

// ── Position Table ────────────────────────────────────────────────────────────

const PositionTable: React.FC<{ positions: Position[]; onClose: (id: string) => void }> = ({ positions, onClose }) => {
  if (positions.length === 0) {
    return (
      <div style={s.card}>
        <h3 style={s.cardTitle}>Open Positions</h3>
        <div style={s.empty}>No open positions.</div>
      </div>
    );
  }

  return (
    <div style={s.card}>
      <h3 style={s.cardTitle}>Open Positions ({positions.length})</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={s.table}>
          <thead>
            <tr>
              {['Symbol', 'Side', 'Size', 'Entry', 'Current', 'P&L', ''].map((h) => (
                <th key={h} style={s.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id} style={s.tr}>
                <td style={s.td}>{p.symbol}</td>
                <td style={s.td}>
                  <span style={{ color: p.side === 'long' ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                    {p.side.toUpperCase()}
                  </span>
                </td>
                <td style={s.td}>{p.size}</td>
                <td style={s.td}>{p.entry_price.toFixed(2)}</td>
                <td style={s.td}>{p.current_price.toFixed(2)}</td>
                <td style={{ ...s.td, color: p.unrealized_pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                  {p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl.toFixed(2)}
                </td>
                <td style={s.td}>
                  <button onClick={() => onClose(p.id)} style={s.closeBtn}>Close</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

const Trading: React.FC = () => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef          = useRef<IChartApi | null>(null);
  const seriesRef         = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const prices    = useStore((s) => s.prices);
  const tick      = prices['XAUUSD'];

  const [symbol]          = useState('XAUUSD');
  const [positions, setPositions] = useState<Position[]>([]);
  const [account, setAccount]     = useState<AccountInfo | null>(null);
  const [timeframe, setTimeframe] = useState('1h');

  const fetchPositions = useCallback(async () => {
    try {
      const res = await tradingApi.positions();
      setPositions(res.data?.positions ?? res.data ?? []);
    } catch { /* silent */ }
  }, []);

  const fetchAccount = useCallback(async () => {
    try {
      const res = await tradingApi.account();
      setAccount(res.data);
    } catch { /* silent */ }
  }, []);

  // Init chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155' },
      width: chartContainerRef.current.clientWidth,
      height: 480,
    });

    const series = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    chartRef.current = chart;
    seriesRef.current = series;

    fetch(`/api/trading/ohlcv/${symbol}?timeframe=${timeframe}&limit=200`)
      .then((r) => r.json())
      .then((data) => {
        const candles = Array.isArray(data) ? data : (data.data ?? []);
        series.setData(candles.map((c: any) => ({
          time: (typeof c.timestamp === 'number' ? c.timestamp : new Date(c.timestamp).getTime() / 1000) as any,
          open: c.open, high: c.high, low: c.low, close: c.close,
        })));
      })
      .catch(() => {});

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol, timeframe]);

  // Real-time tick updates
  useEffect(() => {
    if (tick && seriesRef.current) {
      const candle: CandlestickData = {
        time: Math.floor(new Date(tick.timestamp).getTime() / 1000) as any,
        open: tick.bid,
        high: Math.max(tick.bid, tick.ask),
        low: Math.min(tick.bid, tick.ask),
        close: tick.ask,
      };
      seriesRef.current.update(candle);
    }
  }, [tick]);

  useEffect(() => {
    fetchPositions();
    fetchAccount();
    const id = setInterval(() => { fetchPositions(); fetchAccount(); }, 10_000);
    return () => clearInterval(id);
  }, [fetchPositions, fetchAccount]);

  const handleClosePosition = async (id: string) => {
    try {
      await tradingApi.closePosition(id);
      await fetchPositions();
    } catch { /* silent */ }
  };

  const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

  return (
    <div style={s.page}>
      {/* Chart section */}
      <div style={s.chartSection}>
        <div style={s.card}>
          {/* Header */}
          <div style={s.chartHeader}>
            <div>
              <span style={s.symbolLabel}>{symbol}</span>
              <div style={s.priceRow}>
                <span style={s.priceItem}>Bid: <strong>{tick?.bid.toFixed(2) ?? '—'}</strong></span>
                <span style={s.priceItem}>Ask: <strong>{tick?.ask.toFixed(2) ?? '—'}</strong></span>
                <span style={{ ...s.priceItem, color: '#fbbf24' }}>
                  Spread: {tick ? (tick.ask - tick.bid).toFixed(3) : '—'}
                </span>
              </div>
            </div>
            <div style={s.tfRow}>
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  style={{ ...s.tfBtn, ...(timeframe === tf ? s.tfBtnActive : {}) }}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          <div ref={chartContainerRef} style={{ width: '100%', height: 480 }} />
        </div>

        <PositionTable positions={positions} onClose={handleClosePosition} />
      </div>

      {/* Sidebar */}
      <div style={s.sidebar}>
        <OrderPanel
          symbol={symbol}
          bid={tick?.bid ?? 0}
          ask={tick?.ask ?? 0}
          onOrderPlaced={fetchPositions}
        />

        {account && (
          <div style={s.card}>
            <h3 style={s.cardTitle}>Risk Metrics</h3>
            <div style={s.metricList}>
              <MetricRow label="Daily P&L" value={`${account.daily_pnl >= 0 ? '+' : ''}$${account.daily_pnl?.toFixed(2) ?? '—'}`} positive={account.daily_pnl >= 0} />
              <MetricRow label="Open Risk" value={`${account.open_risk_pct?.toFixed(2) ?? '—'}%`} />
              <MetricRow label="Balance" value={`$${account.balance?.toLocaleString() ?? '—'}`} />
              <MetricRow label="Equity" value={`$${account.equity?.toLocaleString() ?? '—'}`} />
              <MetricRow label="Margin Used" value={`$${account.margin_used?.toLocaleString() ?? '—'}`} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

const MetricRow: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
  <div style={s.metricRow}>
    <span style={{ color: '#64748b', fontSize: 13 }}>{label}</span>
    <span style={{
      fontSize: 13, fontWeight: 600,
      color: positive === undefined ? '#f1f5f9' : positive ? '#4ade80' : '#f87171',
    }}>
      {value}
    </span>
  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:        { display: 'flex', gap: 16, padding: 16, minHeight: '100vh', alignItems: 'flex-start' },
  chartSection:{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 },
  sidebar:     { width: 280, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 16 },
  card:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 16 },
  cardTitle:   { fontSize: 15, fontWeight: 700, color: '#f1f5f9', margin: '0 0 12px' },
  chartHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, flexWrap: 'wrap', gap: 8 },
  symbolLabel: { fontSize: 20, fontWeight: 800, color: '#f1f5f9' },
  priceRow:    { display: 'flex', gap: 16, marginTop: 4 },
  priceItem:   { fontSize: 13, color: '#64748b' },
  tfRow:       { display: 'flex', gap: 4 },
  tfBtn:       { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '4px 8px' },
  tfBtnActive: { background: '#1e3a5f', borderColor: '#3b82f6', color: '#60a5fa' },
  sideBtns:    { display: 'flex', gap: 8, marginBottom: 12 },
  sideBtn:     { flex: 1, border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', fontSize: 13, fontWeight: 700, padding: '10px 0', background: '#0f172a' },
  buyActive:   { background: '#14532d', borderColor: '#16a34a', color: '#4ade80' },
  sellActive:  { background: '#450a0a', borderColor: '#dc2626', color: '#f87171' },
  label:       { display: 'block', fontSize: 12, color: '#64748b', marginBottom: 4, marginTop: 8 },
  input:       { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', padding: '7px 10px', fontSize: 13, boxSizing: 'border-box' },
  placeBtn:    { width: '100%', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer', padding: '11px 0', marginTop: 12 },
  table:       { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th:          { textAlign: 'left', color: '#475569', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', padding: '6px 10px', borderBottom: '1px solid #334155' },
  tr:          { borderBottom: '1px solid #1e293b' },
  td:          { padding: '8px 10px', color: '#94a3b8' },
  closeBtn:    { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 4, color: '#f87171', cursor: 'pointer', fontSize: 11, padding: '3px 8px' },
  metricList:  { display: 'flex', flexDirection: 'column', gap: 8 },
  metricRow:   { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  empty:       { textAlign: 'center', color: '#475569', padding: 20, fontSize: 13 },
};

export default Trading;
