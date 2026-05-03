/**
 * Trading.tsx — production trading terminal.
 * Three-column layout: left sidebar | chart+tables | right sidebar
 * All data wired to real backend endpoints — no mocks.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  createChart, IChartApi, ISeriesApi,
  CandlestickSeries, LineSeries, HistogramSeries,
} from 'lightweight-charts';
import type { UTCTimestamp } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useStore, useHasHydrated, selectIsAuth } from '../store';
import { tradingApi } from '../hooks/useApi';
import { usePositions, useAccount, useSignals } from '../hooks/useOrchestratorData';
// Import guarded variants from the barrel — each panel has its own
// PanelErrorBoundary so a crash in one never takes down the terminal.
import {
  PositionsTable,
  OrderEntryForm,
  LiveSignalFeedGuarded   as LiveSignalFeed,
  RiskDashboardGuarded    as RiskDashboard,
  MLModelPanelGuarded     as MLModelPanel,
  MicrostructurePanelGuarded as MicrostructurePanel,
  SentimentGaugeGuarded   as SentimentGauge,
} from '../components/panels';
import { Panel } from '../components/ui/Panel';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { cn, fmtPrice, fmtPnl, fmtDateTime, fmtRelative } from '../lib/utils';
import type { PriceTick } from '../store';

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMBOLS    = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'ETH/USD'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

// ── Local types ───────────────────────────────────────────────────────────────

interface OHLCVCandle {
  timestamp: number | string;
  open: number; high: number; low: number; close: number;
  volume?: number;
}

interface ClosedTrade {
  id: string; symbol: string; side: string; size: number;
  entry_price: number; exit_price: number; realized_pnl: number;
  opened_at: string; closed_at: string; duration_minutes?: number;
}

interface MarketRegime {
  regime: string; confidence: number; volatility: string;
  trend: string; description?: string; updated_at?: string;
}

interface BrainState {
  status: string; mode: string; active_strategies: string[];
  last_decision?: string; confidence?: number; updated_at?: string;
}

interface AIAnalysisResult {
  direction: string; confidence: number; reasoning: string;
  entry_zone?: [number, number]; stop_loss?: number; take_profit?: number;
  key_levels?: number[]; regime?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function apiSym(s: string) { return s.replace('/', '_'); }

function toUTC(ts: number | string): UTCTimestamp {
  if (typeof ts === 'string') return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
  // Auto-detect ms vs seconds: values > 1e10 are milliseconds
  return Math.floor(ts > 1_000_000_000_000 ? ts / 1000 : ts) as UTCTimestamp;
}

// ── TopBar ────────────────────────────────────────────────────────────────────

interface TopBarProps {
  symbol: string; setSymbol: (s: string) => void;
  timeframe: string; setTimeframe: (t: string) => void;
  tick: PriceTick | undefined; wsStatus: string;
}

function TopBar({ symbol, setSymbol, timeframe, setTimeframe, tick, wsStatus }: TopBarProps) {
  const account = useStore((s) => s.account);

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-[#0a1628] border-b border-[#1e2d3d] shrink-0 flex-wrap">
      {/* Branding */}
      <span className="text-[13px] font-bold text-[#00d4ff] tracking-widest shrink-0">
        HOPEFX
      </span>
      <span className="text-[10px] text-slate-600 shrink-0">TERMINAL</span>

      <div className="w-px h-4 bg-[#1e2d3d]" />

      {/* Symbol selector */}
      <select
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        className="bg-[#0d1421] border border-[#1e2d3d] rounded px-2 py-1 text-[13px] font-bold text-slate-200 focus:outline-none focus:border-[#3b82f6] cursor-pointer"
      >
        {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      {/* Live price */}
      {tick ? (
        <div className="flex items-center gap-3 text-[12px]">
          <span className="text-slate-500">Bid</span>
          <span className="font-bold text-[#ff1744] tabular-nums">{fmtPrice(tick.bid)}</span>
          <span className="text-slate-500">Ask</span>
          <span className="font-bold text-[#00e676] tabular-nums">{fmtPrice(tick.ask)}</span>
          <span className="text-slate-500">Spread</span>
          <span className="text-[#ffb800] tabular-nums">{fmtPrice(tick.ask - tick.bid, 3)}</span>
          {tick.change_pct !== undefined && (
            <span className={cn('tabular-nums font-semibold', tick.change_pct >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]')}>
              {tick.change_pct >= 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
            </span>
          )}
        </div>
      ) : (
        <span className="text-[11px] text-slate-600">Awaiting price…</span>
      )}

      <div className="w-px h-4 bg-[#1e2d3d]" />

      {/* Timeframe buttons */}
      <div className="flex gap-1">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => setTimeframe(tf)}
            className={cn(
              'px-2 py-0.5 rounded text-[11px] font-semibold border transition-colors',
              timeframe === tf
                ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
            )}
          >
            {tf}
          </button>
        ))}
      </div>

      <div className="flex-1" />

      {/* Account summary */}
      {account && (
        <div className="flex items-center gap-4 text-[11px]">
          <span className="text-slate-500">Balance <span className="text-slate-300 font-semibold">${account.balance.toLocaleString()}</span></span>
          <span className="text-slate-500">Equity <span className="text-slate-300 font-semibold">${account.equity.toLocaleString()}</span></span>
          <span className="text-slate-500">P&L <span className={cn('font-semibold', account.daily_pnl >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]')}>{fmtPnl(account.daily_pnl)}</span></span>
        </div>
      )}

      {/* WS status */}
      <span className={cn(
        'text-[10px] px-2 py-0.5 rounded font-bold border',
        wsStatus === 'connected'
          ? 'bg-[#00e676]/10 border-[#00e676]/30 text-[#00e676]'
          : 'bg-[#ff1744]/10 border-[#ff1744]/30 text-[#ff1744]',
      )}>
        {wsStatus === 'connected' ? '● LIVE' : '○ REST'}
      </span>
    </div>
  );
}

// ── ChartPanel ────────────────────────────────────────────────────────────────

interface ChartPanelProps {
  symbol: string; timeframe: string; tick: PriceTick | undefined;
}

function ChartPanel({ symbol, timeframe, tick }: ChartPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef       = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRef        = useRef<ISeriesApi<'Line'> | null>(null);

  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const [chartError, setChartError] = useState<string | null>(null);
  const [loading, setLoading]       = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showMA, setShowMA]         = useState(true);
  const [candles, setCandles]       = useState<OHLCVCandle[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#060d18' }, textColor: '#64748b' },
      grid:   { vertLines: { color: '#0d1421' }, horzLines: { color: '#0d1421' } },
      rightPriceScale: { borderColor: '#1e2d3d' },
      timeScale: { borderColor: '#1e2d3d', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 1 },
      width:  containerRef.current.clientWidth,
      height: 340,
    });
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', downColor: '#ff1744',
      borderUpColor: '#00e676', borderDownColor: '#ff1744',
      wickUpColor: '#00e676', wickDownColor: '#ff1744',
    });
    const vol = chart.addSeries(HistogramSeries, {
      color: '#1e2d3d', priceFormat: { type: 'volume' }, priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const ma = chart.addSeries(LineSeries, {
      color: '#3b82f6', lineWidth: 1, priceLineVisible: false,
    });
    chartRef.current = chart; candleRef.current = candle;
    volRef.current = vol; maRef.current = ma;
    const onResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); chart.remove(); };
  }, []);

  useEffect(() => {
    if (!candleRef.current || !hydrated || !isAuth) return;
    const controller = new AbortController();
    setLoading(true); setChartError(null);
    tradingApi.ohlcv(symbol, timeframe, 300)
      .then((r) => {
        if (controller.signal.aborted) return;
        const raw = r.data as OHLCVCandle[] | { data?: OHLCVCandle[] };
        const data: OHLCVCandle[] = Array.isArray(raw) ? raw : (raw.data ?? []);
        if (!data.length) { setChartError('No OHLCV data for this symbol/timeframe'); return; }
        setCandles(data);
        const sorted = [...data].sort((a, b) => toUTC(a.timestamp) - toUTC(b.timestamp));
        candleRef.current!.setData(sorted.map((c) => ({
          time: toUTC(c.timestamp), open: c.open, high: c.high, low: c.low, close: c.close,
        })));
        if (volRef.current) {
          volRef.current.setData(sorted.map((c) => ({
            time: toUTC(c.timestamp), value: c.volume ?? 0,
            color: c.close >= c.open ? '#00e67630' : '#ff174430',
          })));
        }
        if (maRef.current) {
          const maData = sorted.map((_, i, arr) => {
            if (i < 19) return null;
            const avg = arr.slice(i - 19, i + 1).reduce((s, x) => s + x.close, 0) / 20;
            return { time: toUTC(arr[i].timestamp), value: avg };
          }).filter(Boolean) as { time: UTCTimestamp; value: number }[];
          maRef.current.setData(maData);
        }
        chartRef.current?.timeScale().fitContent();
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setChartError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load chart data');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [symbol, timeframe, hydrated, isAuth]);

  useEffect(() => {
    if (!tick || !candleRef.current) return;
    candleRef.current.update({
      time: Math.floor(tick.timestamp / 1000) as UTCTimestamp,
      open: tick.bid, high: Math.max(tick.bid, tick.ask),
      low: Math.min(tick.bid, tick.ask), close: tick.ask,
    });
  }, [tick]);

  useEffect(() => { volRef.current?.applyOptions({ visible: showVolume }); }, [showVolume]);
  useEffect(() => { maRef.current?.applyOptions({ visible: showMA }); }, [showMA]);

  const stats = useMemo(() => {
    if (!candles.length) return null;
    const last = candles[candles.length - 1];
    const prev = candles[candles.length - 2];
    const chg  = prev ? ((last.close - prev.close) / prev.close) * 100 : 0;
    const high = Math.max(...candles.slice(-20).map((c) => c.high));
    const low  = Math.min(...candles.slice(-20).map((c) => c.low));
    return { last, chg, high20: high, low20: low };
  }, [candles]);

  return (
    <div className="bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden shrink-0">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-[#1e2d3d]">
        {stats && (
          <div className="flex items-center gap-4 text-[11px]">
            <span className="text-slate-500">O <span className="text-slate-300 tabular-nums">{fmtPrice(stats.last.open)}</span></span>
            <span className="text-slate-500">H <span className="text-[#00e676] tabular-nums">{fmtPrice(stats.last.high)}</span></span>
            <span className="text-slate-500">L <span className="text-[#ff1744] tabular-nums">{fmtPrice(stats.last.low)}</span></span>
            <span className="text-slate-500">C <span className="text-slate-200 font-bold tabular-nums">{fmtPrice(stats.last.close)}</span></span>
            <span className={cn('font-semibold tabular-nums', stats.chg >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]')}>
              {stats.chg >= 0 ? '+' : ''}{stats.chg.toFixed(2)}%
            </span>
            <span className="text-slate-600">20H: <span className="text-slate-400">{fmtPrice(stats.high20)}</span></span>
            <span className="text-slate-600">20L: <span className="text-slate-400">{fmtPrice(stats.low20)}</span></span>
          </div>
        )}
        <div className="flex-1" />
        <label className="flex items-center gap-1 text-[10px] text-slate-500 cursor-pointer select-none">
          <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} className="accent-[#3b82f6]" /> Vol
        </label>
        <label className="flex items-center gap-1 text-[10px] text-slate-500 cursor-pointer select-none">
          <input type="checkbox" checked={showMA} onChange={(e) => setShowMA(e.target.checked)} className="accent-[#3b82f6]" /> MA20
        </label>
      </div>
      <div className="relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#060d18]/80 z-10">
            <span className="text-[11px] text-slate-500 animate-pulse">Loading chart…</span>
          </div>
        )}
        {chartError && (
          <div className="flex flex-col items-center justify-center h-[340px] gap-2">
            <span className="text-[#ff1744] text-[12px]">⚠ {chartError}</span>
            <span className="text-slate-600 text-[10px]">Connect a broker or load historical data</span>
          </div>
        )}
        <div ref={containerRef} style={{ width: '100%', height: 340, display: chartError ? 'none' : 'block' }} />
      </div>
    </div>
  );
}

// ── TradeHistoryPanel ─────────────────────────────────────────────────────────

function TradeHistoryPanel({ symbol }: { symbol: string }) {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const { data, isLoading, isError } = useQuery<ClosedTrade[]>({
    queryKey: ['trades', symbol],
    queryFn: async () => {
      const r = await tradingApi.trades({ symbol, limit: 50 });
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
    <div className="flex items-center justify-center h-24 text-slate-600 text-[12px]">No closed trades yet</div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[#1e2d3d]">
            {['Symbol','Side','Size','Entry','Exit','P&L','Opened','Closed','Duration'].map((h) => (
              <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((t) => {
            const isLong = t.side === 'long' || t.side === 'buy';
            const pnlPos = t.realized_pnl >= 0;
            return (
              <tr key={t.id} className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/30 transition-colors">
                <td className="px-3 py-2 font-semibold text-slate-200">{t.symbol}</td>
                <td className="px-3 py-2">
                  <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-bold uppercase', isLong ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]')}>
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
                <td className="px-3 py-2 text-slate-500">{t.duration_minutes != null ? `${t.duration_minutes}m` : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── SignalsSummaryPanel ────────────────────────────────────────────────────────

function SignalsSummaryPanel({ symbol }: { symbol: string }) {
  const signals  = useStore((s) => s.signals);
  const filtered = signals.filter(
    (sig) => sig.symbol === symbol || sig.symbol === symbol.replace('/', '_')
  );

  if (!filtered.length) return (
    <div className="flex items-center justify-center h-24 text-slate-600 text-[12px]">No signals for {symbol}</div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-[#1e2d3d]">
            {['Symbol','Direction','Confidence','Entry','SL','TP','R:R','Model','Status','Generated'].map((h) => (
              <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.map((sig) => {
            const isLong = sig.direction === 'long';
            const rr = sig.risk_reward ?? (
              sig.entry_price > 0 && sig.stop_loss > 0 && sig.take_profit > 0
                ? Math.abs(sig.take_profit - sig.entry_price) / Math.abs(sig.entry_price - sig.stop_loss)
                : null
            );
            const confColor = sig.confidence >= 0.75 ? '#00e676' : sig.confidence >= 0.55 ? '#ffb800' : '#ff6b35';
            return (
              <tr key={sig.id} className="border-b border-[#0d1421] hover:bg-[#1e2d3d]/30 transition-colors">
                <td className="px-3 py-2 font-semibold text-slate-200">{sig.symbol.replace('_','/')}</td>
                <td className="px-3 py-2">
                  <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-bold uppercase', isLong ? 'bg-[#00e676]/10 text-[#00e676]' : 'bg-[#ff1744]/10 text-[#ff1744]')}>
                    {isLong ? '▲ Long' : '▼ Short'}
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums font-semibold" style={{ color: confColor }}>{(sig.confidence * 100).toFixed(0)}%</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{fmtPrice(sig.entry_price)}</td>
                <td className="px-3 py-2 tabular-nums text-[#ff1744]">{fmtPrice(sig.stop_loss)}</td>
                <td className="px-3 py-2 tabular-nums text-[#00e676]">{fmtPrice(sig.take_profit)}</td>
                <td className="px-3 py-2 tabular-nums text-slate-400">{rr != null ? `1:${rr.toFixed(1)}` : '—'}</td>
                <td className="px-3 py-2 text-slate-500 font-mono truncate max-w-[100px]">{sig.model}</td>
                <td className="px-3 py-2">
                  <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-semibold',
                    sig.status === 'active' ? 'bg-[#00e676]/10 text-[#00e676]' :
                    sig.status === 'triggered' ? 'bg-[#3b82f6]/10 text-[#60a5fa]' :
                    'bg-[#334155]/30 text-slate-500'
                  )}>{sig.status}</span>
                </td>
                <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtRelative(sig.generated_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── MarketRegimePanel ─────────────────────────────────────────────────────────

function MarketRegimePanel({ symbol }: { symbol: string }) {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const { data, isLoading } = useQuery<MarketRegime>({
    queryKey: ['regime', symbol],
    queryFn: async () => {
      const r = await tradingApi.regime(apiSym(symbol));
      return r.data as MarketRegime;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  const { data: brain } = useQuery<BrainState>({
    queryKey: ['brain-state'],
    queryFn: async () => {
      const r = await tradingApi.brainState();
      return r.data as BrainState;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 15_000,
    staleTime:       7_500,
  });

  const regimeColor = (r?: string) => {
    if (!r) return '#64748b';
    const l = r.toLowerCase();
    if (l.includes('bull') || l.includes('trend_up')) return '#00e676';
    if (l.includes('bear') || l.includes('trend_down')) return '#ff1744';
    if (l.includes('range') || l.includes('chop')) return '#ffb800';
    return '#00d4ff';
  };

  return (
    <Panel title="Market Regime">
      {isLoading ? <PanelSkeleton rows={3} /> : (
        <div className="flex flex-col gap-3">
          {data ? (
            <>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Regime</span>
                <span className="text-[13px] font-bold uppercase tracking-wider" style={{ color: regimeColor(data.regime) }}>
                  {data.regime}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Confidence</span>
                <span className="text-[12px] font-semibold tabular-nums" style={{ color: data.confidence >= 0.7 ? '#00e676' : '#ffb800' }}>
                  {(data.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="h-1.5 bg-[#1e2d3d] rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500" style={{ width: `${data.confidence * 100}%`, backgroundColor: regimeColor(data.regime) }} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Volatility</span>
                <span className="text-[11px] text-slate-300 font-semibold uppercase">{data.volatility}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Trend</span>
                <span className="text-[11px] text-slate-300 font-semibold uppercase">{data.trend}</span>
              </div>
              {data.description && (
                <p className="text-[10px] text-slate-500 leading-relaxed border-t border-[#1e2d3d] pt-2">{data.description}</p>
              )}
            </>
          ) : (
            <span className="text-[11px] text-slate-600">No regime data</span>
          )}

          {brain && (
            <div className="border-t border-[#1e2d3d] pt-3 flex flex-col gap-2">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider">AI Brain</span>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Mode</span>
                <span className="text-[11px] font-semibold text-[#00d4ff] uppercase">{brain.mode}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Status</span>
                <span className={cn('text-[11px] font-semibold uppercase', brain.status === 'active' ? 'text-[#00e676]' : 'text-[#ffb800]')}>{brain.status}</span>
              </div>
              {brain.active_strategies?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {brain.active_strategies.slice(0, 3).map((s) => (
                    <span key={s} className="px-1.5 py-0.5 rounded bg-[#1e2d3d] text-[9px] text-slate-400 font-mono">{s}</span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// ── AIAnalysisPanel ───────────────────────────────────────────────────────────

function AIAnalysisPanel({ symbol }: { symbol: string }) {
  const [result, setResult]     = useState<AIAnalysisResult | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [lastRun, setLastRun]   = useState<string | null>(null);
  const prices = useStore((s) => s.prices);
  const tick   = prices[symbol];

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const runAnalysis = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await tradingApi.aiAnalysis({
        symbol: apiSym(symbol),
        price: tick?.mid ?? tick?.ask ?? 0,
        timeframe: '1h',
      });
      if (!mountedRef.current) return;
      setResult(r.data as AIAnalysisResult);
      setLastRun(new Date().toLocaleTimeString());
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (e as { message?: string })?.message ?? 'Analysis failed';
      setError(msg);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [symbol, tick]);

  const dirColor = result?.direction === 'long' ? '#00e676' : result?.direction === 'short' ? '#ff1744' : '#ffb800';

  return (
    <Panel title="AI Analysis" headerRight={lastRun ? <span className="text-[9px] text-slate-600">{lastRun}</span> : undefined}>
      <div className="flex flex-col gap-3">
        <button
          onClick={runAnalysis}
          disabled={loading}
          className={cn(
            'w-full py-2 rounded text-[12px] font-bold border transition-colors',
            'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa] hover:bg-[#1e3a5f]/80',
            'disabled:opacity-40 disabled:cursor-not-allowed',
          )}
        >
          {loading ? 'Analysing…' : '⚡ Run AI Analysis'}
        </button>

        {error && (
          <div className="px-3 py-2 rounded bg-[#ff1744]/10 border border-[#ff1744]/20 text-[#ff1744] text-[11px]">{error}</div>
        )}

        {result && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-slate-500">Direction</span>
              <span className="text-[13px] font-bold uppercase" style={{ color: dirColor }}>{result.direction}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-slate-500">Confidence</span>
              <span className="text-[12px] font-semibold tabular-nums" style={{ color: result.confidence >= 0.7 ? '#00e676' : '#ffb800' }}>
                {(result.confidence * 100).toFixed(0)}%
              </span>
            </div>
            {result.stop_loss && (
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Stop Loss</span>
                <span className="text-[11px] tabular-nums text-[#ff1744]">{fmtPrice(result.stop_loss)}</span>
              </div>
            )}
            {result.take_profit && (
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Take Profit</span>
                <span className="text-[11px] tabular-nums text-[#00e676]">{fmtPrice(result.take_profit)}</span>
              </div>
            )}
            {result.regime && (
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">Regime</span>
                <span className="text-[11px] text-slate-300 uppercase font-semibold">{result.regime}</span>
              </div>
            )}
            <div className="border-t border-[#1e2d3d] pt-2">
              <p className="text-[10px] text-slate-400 leading-relaxed">{result.reasoning}</p>
            </div>
            {result.key_levels && result.key_levels.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-[9px] text-slate-600 uppercase tracking-wider">Key Levels</span>
                <div className="flex flex-wrap gap-1">
                  {result.key_levels.map((lvl) => (
                    <span key={lvl} className="px-1.5 py-0.5 rounded bg-[#1e2d3d] text-[10px] text-slate-400 tabular-nums font-mono">{fmtPrice(lvl)}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ── EmergencyStopButton ───────────────────────────────────────────────────────

function EmergencyStopButton() {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [done, setDone]             = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const qc = useQueryClient();
  const killSwitch = useStore((s) => s.account?.kill_switch ?? false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const handleClick = useCallback(async () => {
    if (!confirming) { setConfirming(true); return; }
    setLoading(true); setError(null);
    try {
      await tradingApi.emergencyStop();
      if (!mountedRef.current) return;
      setDone(true); setConfirming(false);
      qc.invalidateQueries({ queryKey: ['account'] });
      qc.invalidateQueries({ queryKey: ['positions'] });
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (e as { message?: string })?.message ?? 'Emergency stop failed';
      setError(msg); setConfirming(false);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [confirming, qc]);

  if (killSwitch || done) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded border bg-[#ff1744]/10 border-[#ff1744]/30 animate-pulse">
        <span className="w-2 h-2 rounded-full bg-[#ff1744]" />
        <span className="text-[11px] font-bold text-[#ff1744] uppercase tracking-wider">Kill Switch Active</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={handleClick}
        disabled={loading}
        className={cn(
          'w-full py-2 rounded text-[12px] font-bold border transition-colors',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          confirming
            ? 'bg-[#ff1744] border-[#ff1744] text-white animate-pulse'
            : 'bg-[#ff1744]/10 border-[#ff1744]/40 text-[#ff1744] hover:bg-[#ff1744]/20',
        )}
      >
        {loading ? 'Stopping…' : confirming ? '⚠ CONFIRM EMERGENCY STOP' : '🛑 Emergency Stop'}
      </button>
      {confirming && (
        <button onClick={() => setConfirming(false)} className="text-[10px] text-slate-500 hover:text-slate-300 text-center">
          Cancel
        </button>
      )}
      {error && <div className="text-[10px] text-[#ff1744]">{error}</div>}
    </div>
  );
}

// ── LeftSidebar ───────────────────────────────────────────────────────────────

function LeftSidebar({ symbol }: { symbol: string }) {
  return (
    <div className="w-[280px] shrink-0 flex flex-col gap-2 overflow-y-auto">
      <OrderEntryForm symbol={symbol} />
      <Panel title="Controls">
        <EmergencyStopButton />
      </Panel>
      <MarketRegimePanel symbol={symbol} />
      <AIAnalysisPanel symbol={symbol} />
    </div>
  );
}

// ── RightSidebar ──────────────────────────────────────────────────────────────

type RightTab = 'signals' | 'risk' | 'ml' | 'micro' | 'sentiment';

interface RightSidebarProps {
  rightTab: RightTab;
  setRightTab: (t: RightTab) => void;
}

function RightSidebar({ rightTab, setRightTab }: RightSidebarProps) {
  const tabs: { id: RightTab; label: string }[] = [
    { id: 'signals',   label: 'Signals'   },
    { id: 'risk',      label: 'Risk'      },
    { id: 'ml',        label: 'ML'        },
    { id: 'micro',     label: 'Micro'     },
    { id: 'sentiment', label: 'Sentiment' },
  ];

  return (
    <div className="w-[280px] shrink-0 flex flex-col gap-2 overflow-hidden">
      {/* Tab bar */}
      <div className="flex gap-1 flex-wrap">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setRightTab(id)}
            className={cn(
              'px-2 py-0.5 rounded text-[10px] font-semibold border transition-colors',
              rightTab === id
                ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {rightTab === 'signals'   && <LiveSignalFeed />}
        {rightTab === 'risk'      && <RiskDashboard />}
        {rightTab === 'ml'        && <MLModelPanel />}
        {rightTab === 'micro'     && <MicrostructurePanel />}
        {rightTab === 'sentiment' && <SentimentGauge />}
      </div>
    </div>
  );
}

// ── TradingPage (main layout) ─────────────────────────────────────────────────

function TradingPage() {
  const [symbol,    setSymbol]    = useState('XAU/USD');
  const [timeframe, setTimeframe] = useState('1h');
  const [activeTab, setActiveTab] = useState<'positions' | 'history' | 'signals'>('positions');
  const [rightTab,  setRightTab]  = useState<RightTab>('signals');

  usePositions();
  useAccount();
  useSignals();

  const wsStatus = useStore((s) => s.wsStatus);
  const prices   = useStore((s) => s.prices);
  const tick     = prices[symbol];

  return (
    <div className="flex flex-col h-screen bg-[#060d18] text-slate-200 overflow-hidden">
      <TopBar
        symbol={symbol} setSymbol={setSymbol}
        timeframe={timeframe} setTimeframe={setTimeframe}
        tick={tick} wsStatus={wsStatus}
      />

      <div className="flex flex-1 min-h-0 gap-2 p-2 overflow-hidden">
        {/* Left sidebar */}
        <LeftSidebar symbol={symbol} />

        {/* Centre column */}
        <div className="flex flex-col flex-1 min-w-0 gap-2 overflow-hidden">
          <ChartPanel symbol={symbol} timeframe={timeframe} tick={tick} />

          {/* Bottom tabs */}
          <div className="flex flex-col flex-1 min-h-0 bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden">
            <div className="flex items-center gap-1 px-3 py-2 border-b border-[#1e2d3d] shrink-0">
              {(['positions', 'history', 'signals'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setActiveTab(t)}
                  className={cn(
                    'px-3 py-1 rounded text-[11px] font-semibold border transition-colors capitalize',
                    activeTab === t
                      ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                      : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="flex-1 min-h-0 overflow-auto">
              {activeTab === 'positions' && <PositionsTable symbol={symbol} />}
              {activeTab === 'history'   && <TradeHistoryPanel symbol={symbol} />}
              {activeTab === 'signals'   && <SignalsSummaryPanel symbol={symbol} />}
            </div>
          </div>
        </div>

        {/* Right sidebar */}
        <RightSidebar rightTab={rightTab} setRightTab={setRightTab} />
      </div>
    </div>
  );
}

// ── Default export ────────────────────────────────────────────────────────────

export default function Trading() {
  return <TradingPage />;
}
