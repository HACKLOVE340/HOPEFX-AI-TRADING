/**
 * Trading page (legacy /trading/legacy) — candlestick chart, order entry,
 * positions table, risk metrics.
 *
 * Wires to:
 *   GET  /api/trading/ohlcv/{symbol}   — OHLCV candles
 *   GET  /api/trading/positions        — via usePositions (TanStack Query)
 *   GET  /api/trading/account          — via useAccount (TanStack Query)
 *   POST /api/trading/orders           — via OrderEntryForm
 *   DELETE /api/trading/positions/{id} — via PositionsTable
 *
 * Live prices come from Zustand store (WebSocket → REST fallback).
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData, CandlestickSeries } from 'lightweight-charts';
import { useStore } from '../store';
import { tradingApi } from '../hooks/useApi';
import { usePositions, useAccount } from '../hooks/useOrchestratorData';
import { PositionsTable } from '../components/panels/PositionsTable';
import { OrderEntryForm } from '../components/panels/OrderEntryForm';
import { PanelSkeleton } from '../components/ui/Skeleton';

// ── Types ─────────────────────────────────────────────────────────────────────

interface OHLCVCandle {
  timestamp: number | string;
  open:  number;
  high:  number;
  low:   number;
  close: number;
}

// ── Risk metrics panel ────────────────────────────────────────────────────────

function RiskMetrics() {
  const { data: account, isLoading } = useAccount();

  if (isLoading) return <div style={s.card}><PanelSkeleton rows={4} /></div>;
  if (!account)  return null;

  const rows = [
    { label: 'Daily P&L',   value: `${account.daily_pnl >= 0 ? '+' : ''}$${account.daily_pnl?.toFixed(2) ?? '—'}`,  positive: account.daily_pnl >= 0 },
    { label: 'Open Risk',   value: `${account.open_risk_pct?.toFixed(2) ?? '—'}%` },
    { label: 'Balance',     value: `$${account.balance?.toLocaleString() ?? '—'}` },
    { label: 'Equity',      value: `$${account.equity?.toLocaleString() ?? '—'}` },
    { label: 'Margin Used', value: `$${account.margin_used?.toLocaleString() ?? '—'}` },
    { label: 'Win Rate',    value: account.win_rate != null ? `${account.win_rate}%` : '—' },
    { label: 'Sharpe',      value: account.sharpe_ratio != null ? account.sharpe_ratio.toFixed(2) : '—' },
  ];

  return (
    <div style={s.card}>
      <h3 style={s.cardTitle}>Risk Metrics</h3>
      <div style={s.metricList}>
        {rows.map(({ label, value, positive }) => (
          <div key={label} style={s.metricRow}>
            <span style={{ color: '#64748b', fontSize: 13 }}>{label}</span>
            <span style={{
              fontSize: 13, fontWeight: 600,
              color: positive === undefined ? '#f1f5f9' : positive ? '#4ade80' : '#f87171',
            }}>
              {value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

const Trading: React.FC = () => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef          = useRef<IChartApi | null>(null);
  const seriesRef         = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const prices = useStore((s) => s.prices);
  const wsStatus = useStore((s) => s.wsStatus);

  const [symbol,    setSymbol]    = useState('XAU/USD');
  const [timeframe, setTimeframe] = useState('1h');
  const [chartError, setChartError] = useState<string | null>(null);

  const tick = prices[symbol];

  // Bootstrap positions + account via TanStack Query (WS-aware polling)
  usePositions();
  useAccount();

  // ── Chart init ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid:   { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      rightPriceScale: { borderColor: '#334155' },
      timeScale:       { borderColor: '#334155' },
      width:  chartContainerRef.current.clientWidth,
      height: 460,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor:        '#22c55e', downColor:        '#ef4444',
      borderUpColor:  '#22c55e', borderDownColor:  '#ef4444',
      wickUpColor:    '#22c55e', wickDownColor:    '#ef4444',
    });

    chartRef.current  = chart;
    seriesRef.current = series;
    setChartError(null);

    tradingApi.ohlcv(symbol, timeframe, 200)
      .then((r) => {
        const raw = r.data as OHLCVCandle[] | { data?: OHLCVCandle[] };
        const candles: OHLCVCandle[] = Array.isArray(raw) ? raw : (raw.data ?? []);
        if (candles.length === 0) {
          setChartError('No OHLCV data available for this symbol/timeframe');
          return;
        }
        series.setData(candles.map((c) => ({
          time: Math.floor(
            typeof c.timestamp === 'number' ? c.timestamp : new Date(c.timestamp).getTime() / 1000
          ) as import('lightweight-charts').UTCTimestamp,
          open: c.open, high: c.high, low: c.low, close: c.close,
        })));
      })
      .catch((err) => {
        const msg = err?.response?.data?.detail ?? err?.message ?? 'Failed to load chart data';
        setChartError(msg);
      });

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

  // ── Real-time tick updates ──────────────────────────────────────────────────
  useEffect(() => {
    if (tick && seriesRef.current) {
      const candle: CandlestickData = {
        time:  Math.floor(tick.timestamp / 1000) as import('lightweight-charts').UTCTimestamp,
        open:  tick.bid,
        high:  Math.max(tick.bid, tick.ask),
        low:   Math.min(tick.bid, tick.ask),
        close: tick.ask,
      };
      seriesRef.current.update(candle);
    }
  }, [tick]);

  const handleOrderPlaced = useCallback(() => {
    // TanStack Query will auto-refetch positions via invalidation in OrderEntryForm
  }, []);

  return (
    <div style={s.page}>
      {/* Chart section */}
      <div style={s.chartSection}>
        <div style={s.card}>
          {/* Header */}
          <div style={s.chartHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {/* Symbol selector */}
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                style={s.select}
              >
                {SYMBOLS.map((sym) => <option key={sym} value={sym}>{sym}</option>)}
              </select>

              {/* Live price */}
              {tick && (
                <div style={s.priceRow}>
                  <span style={s.priceItem}>Bid: <strong style={{ color: '#f87171' }}>{tick.bid.toFixed(2)}</strong></span>
                  <span style={s.priceItem}>Ask: <strong style={{ color: '#4ade80' }}>{tick.ask.toFixed(2)}</strong></span>
                  <span style={{ ...s.priceItem, color: '#fbbf24' }}>
                    Spread: {(tick.ask - tick.bid).toFixed(3)}
                  </span>
                </div>
              )}

              {/* WS status */}
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                background: wsStatus === 'connected' ? '#14532d' : '#450a0a',
                color:      wsStatus === 'connected' ? '#4ade80' : '#f87171',
              }}>
                {wsStatus === 'connected' ? '● LIVE' : '○ REST'}
              </span>
            </div>

            {/* Timeframe buttons */}
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

          {/* Chart */}
          {chartError ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 460, color: '#f87171', fontSize: 13, flexDirection: 'column', gap: 8 }}>
              <span>⚠ {chartError}</span>
              <span style={{ color: '#475569', fontSize: 11 }}>Connect a broker or load historical data to see the chart</span>
            </div>
          ) : (
            <div ref={chartContainerRef} style={{ width: '100%', height: 460 }} />
          )}
        </div>

        {/* Positions table — uses new data layer */}
        <PositionsTable symbol={symbol} />
      </div>

      {/* Sidebar */}
      <div style={s.sidebar}>
        {/* Order entry — uses new data layer */}
        <OrderEntryForm symbol={symbol} onOrderPlaced={handleOrderPlaced} />

        {/* Risk metrics */}
        <RiskMetrics />
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:        { display: 'flex', gap: 16, padding: 16, minHeight: '100vh', alignItems: 'flex-start' },
  chartSection:{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 },
  sidebar:     { width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 16 },
  card:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 16 },
  cardTitle:   { fontSize: 13, fontWeight: 700, color: '#f1f5f9', margin: '0 0 12px' },
  chartHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 },
  priceRow:    { display: 'flex', gap: 12 },
  priceItem:   { fontSize: 12, color: '#64748b' },
  tfRow:       { display: 'flex', gap: 4 },
  tfBtn:       { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 11, padding: '4px 8px' },
  tfBtnActive: { background: '#1e3a5f', borderColor: '#3b82f6', color: '#60a5fa' },
  select:      { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', fontSize: 14, fontWeight: 700, padding: '6px 10px', cursor: 'pointer' },
  metricList:  { display: 'flex', flexDirection: 'column', gap: 8 },
  metricRow:   { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
};

export default Trading;
