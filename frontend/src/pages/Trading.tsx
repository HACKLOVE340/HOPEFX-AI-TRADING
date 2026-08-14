/**
 * Trading.tsx — production trading terminal.
 * Three-column layout: left sidebar | chart+tables | right sidebar
 * All data wired to real backend endpoints — no mocks.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createChart, IChartApi, ISeriesApi,
  CandlestickSeries, LineSeries, HistogramSeries,
} from 'lightweight-charts';
import type { UTCTimestamp } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useStore, useHasHydrated, selectIsAuth, selectFeedLive } from '../store';
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
import { cn, fmtPrice, fmtPnl, fmtDateTime, fmtRelative, extractApiError, sameSymbol, positionSide } from '../lib/utils';
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

/**
 * Price formatting per instrument class.
 *
 * The chart used lightweight-charts' default (2 decimals, minMove 0.01) for
 * every symbol. On EUR/USD that renders 1.08 instead of 1.08512 — the price
 * scale collapses to a handful of distinct labels and the candles look flat,
 * which is a large part of why this did not read like a real chart. JPY pairs
 * need 3, metals 2, crypto 2, and everything else 5.
 */
export function priceFormatFor(symbol: string): { precision: number; minMove: number } {
  const s = symbol.toUpperCase().replace('/', '');
  if (s.includes('JPY')) return { precision: 3, minMove: 0.001 };
  if (s.startsWith('XAU') || s.startsWith('XAG')) return { precision: 2, minMove: 0.01 };
  if (s.startsWith('BTC') || s.startsWith('ETH')) return { precision: 2, minMove: 0.01 };
  return { precision: 5, minMove: 0.00001 };
}

/**
 * True when a live tick is too far from the bar it would update to be the same
 * instrument.
 *
 * The deployed terminal showed XAU/USD with the header reading Bid 3,299.85
 * while the candles sat around 4,390 — and drew a vertical line plunging
 * between the two, because the tick was written straight onto the last bar. A
 * 25% gap is not a price move, it is two sources disagreeing about what the
 * symbol is. Drawing it as a candle presents a data fault as a market event.
 */
export function tickIsOffScale(tickPrice: number, barClose: number): boolean {
  if (!Number.isFinite(tickPrice) || !Number.isFinite(barClose) || barClose === 0) return true;
  return Math.abs(tickPrice - barClose) / Math.abs(barClose) > TICK_MAX_DIVERGENCE;
}

/** Beyond this fractional gap, a tick is treated as a different instrument. */
const TICK_MAX_DIVERGENCE = 0.10;

// ── TopBar ────────────────────────────────────────────────────────────────────

interface TopBarProps {
  symbol: string; setSymbol: (s: string) => void;
  timeframe: string; setTimeframe: (t: string) => void;
  tick: PriceTick | undefined; wsStatus: string; feedLive: boolean;
}

function TopBar({ symbol, setSymbol, timeframe, setTimeframe, tick, wsStatus, feedLive }: TopBarProps) {
  const navigate = useNavigate();
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
          <span className="text-slate-500">Balance <span className="text-slate-300 font-semibold">${fmtPrice(account.balance)}</span></span>
          <span className="text-slate-500">Equity <span className="text-slate-300 font-semibold">${fmtPrice(account.equity)}</span></span>
          <span className="text-slate-500">P&L <span className={cn('font-semibold', (account.daily_pnl ?? 0) >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]')}>{fmtPnl(account.daily_pnl)}</span></span>
        </div>
      )}

      {/* Quick nav */}
      <button onClick={() => navigate('/journal')}
        className="px-2 py-0.5 rounded text-[11px] font-semibold border border-[#1e2d3d] text-slate-500 hover:border-[#334155] hover:text-slate-300 transition-colors">
        📓 Journal
      </button>
      <button onClick={() => navigate('/risk-calculator')}
        className="px-2 py-0.5 rounded text-[11px] font-semibold border border-[#1e2d3d] text-slate-500 hover:border-[#334155] hover:text-slate-300 transition-colors">
        🛡 Risk Calc
      </button>

      {/* WS status */}
      {/* F10-01: keyed to the feed, not the socket. Third copy of this badge. */}
      <span className={cn(
        'text-[10px] px-2 py-0.5 rounded font-bold border',
        feedLive
          ? 'bg-[#00e676]/10 border-[#00e676]/30 text-[#00e676]'
          : 'bg-[#ffb800]/10 border-[#ffb800]/30 text-[#ffb800]',
      )}>
        {feedLive ? '● LIVE' : wsStatus === 'connected' ? '● STALLED' : '○ REST'}
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
  // Newest bar time in the series — guards update() against "Cannot update
  // oldest data" after a timeframe switch.
  const lastBarTimeRef = useRef<number | null>(null);
  // fitContent() belongs to the first load only; re-running it on every
  // refresh discards the user's zoom and pan.
  const didFitRef = useRef(false);
  // One warning per mount when the tick and the OHLCV disagree on instrument.
  const offScaleWarnedRef = useRef(false);
  const rafRef       = useRef<number>(0);

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
      layout: {
        background: { color: '#060d18' },
        textColor: '#9ca3af',
        attributionLogo: false,
      },
      grid: { vertLines: { color: '#0d1421' }, horzLines: { color: '#0d1421' } },
      rightPriceScale: {
        borderColor: '#1e2d3d',
        // Headroom above and below the series so candles never touch the edge —
        // the default 0.2/0.1 crowds the last bar against the axis.
        scaleMargins: { top: 0.12, bottom: 0.12 },
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: '#1e2d3d',
        timeVisible: true,
        secondsVisible: false,
        // Breathing room to the right of the last bar, as TradingView leaves,
        // so the live candle and its price label are not against the scale.
        rightOffset: 6,
        barSpacing: 8,
        minBarSpacing: 2,
        fixLeftEdge: false,
        lockVisibleTimeRangeOnResize: true,
      },
      crosshair: {
        mode: 1, // magnet — snaps to OHLC values like TradingView's default
        vertLine: { color: '#4b5563', width: 1, style: 3, labelBackgroundColor: '#1e3a5f' },
        horzLine: { color: '#4b5563', width: 1, style: 3, labelBackgroundColor: '#1e3a5f' },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 340,
    });
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', downColor: '#ff1744',
      borderUpColor: '#00e676', borderDownColor: '#ff1744',
      wickUpColor: '#00e676', wickDownColor: '#ff1744',
      // Per-instrument precision. The default 2dp rendered EUR/USD as 1.08 and
      // flattened the price scale to a few labels.
      priceFormat: { type: 'price', ...priceFormatFor(symbol) },
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineStyle: 2,
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
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          // Height as well as width. It was fixed at 340px at construction, so
          // the chart never grew with its container and left dead space below
          // on tall viewports while staying cramped in the stacked layout.
          chartRef.current.applyOptions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 340,
          });
        }
      });
    });
    if (containerRef.current) ro.observe(containerRef.current);
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      candleRef.current = null;
      volRef.current    = null;
      maRef.current     = null;
    };
  }, []);

  // Keep per-instrument precision in sync with the selected symbol.
  //
  // The chart is created once (deps `[]`), so priceFormat was frozen to
  // whatever symbol was selected at mount: switching XAU/USD → EUR/USD kept
  // 2dp and rendered 1.08 instead of 1.08512. Also re-fit the viewport, since
  // a new instrument is a new price range and the previous zoom is meaningless.
  useEffect(() => {
    candleRef.current?.applyOptions({
      priceFormat: { type: 'price', ...priceFormatFor(symbol) },
    });
    didFitRef.current = false;
    offScaleWarnedRef.current = false;
  }, [symbol, timeframe]);

  useEffect(() => {
    if (!candleRef.current || !hydrated || !isAuth) return;
    const controller = new AbortController();
    setLoading(true); setChartError(null);
    tradingApi.ohlcv(symbol, timeframe, 300)
      .then((r) => {
        if (controller.signal.aborted) return;
        const raw = r.data as OHLCVCandle[] | { data?: OHLCVCandle[] };
        const data: OHLCVCandle[] = Array.isArray(raw) ? raw : (raw.data ?? []);
        if (!data.length) {
          // Clear the previous symbol's candles — otherwise switching to a
          // symbol with no feed leaves the old instrument's chart on screen
          // under the new symbol's label, so the chart looks stuck.
          candleRef.current?.setData([]);
          volRef.current?.setData([]);
          maRef.current?.setData([]);
          setCandles([]);
          setChartError('No OHLCV data for this symbol/timeframe');
          return;
        }
        // Sort BEFORE storing. This did `setCandles(data)` with the unsorted
        // array while the series received `sorted`, so `candles[length - 1]`
        // was not necessarily the newest bar — and that is the bar the live
        // tick effect below updates.
        const sorted = [...data]
          .filter((c) => Number.isFinite(toUTC(c.timestamp)))
          .sort((a, b) => toUTC(a.timestamp) - toUTC(b.timestamp));
        setCandles(sorted);

        const newest = sorted.length > 0 ? sorted[sorted.length - 1] : undefined;
        lastBarTimeRef.current = newest ? toUTC(newest.timestamp) : null;

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
          const maData = sorted.map((bar, i, arr) => {
            if (i < 19) return null;
            const avg = arr.slice(i - 19, i + 1).reduce((s, x) => s + x.close, 0) / 20;
            return { time: toUTC(bar.timestamp), value: avg };
          }).filter(Boolean) as { time: UTCTimestamp; value: number }[];
          maRef.current.setData(maData);
        }
        // Fit once, then leave the viewport alone. This ran fitContent() on
        // every 30s refresh, which threw away the user's zoom and pan each
        // time — no real chart does that. After the first load, only follow
        // real time.
        if (!didFitRef.current) {
          chartRef.current?.timeScale().fitContent();
          didFitRef.current = true;
        }
        chartRef.current?.timeScale().scrollToRealTime();
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        // Same reason as the empty-data branch: never leave the old symbol's
        // candles on screen when the new symbol's fetch fails.
        candleRef.current?.setData([]);
        volRef.current?.setData([]);
        maRef.current?.setData([]);
        setCandles([]);
        setChartError(extractApiError(err, 'Failed to load chart data'));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [symbol, timeframe, hydrated, isAuth]);

  useEffect(() => {
    // Align the live tick to the current bar's open time so it updates the
    // existing candle rather than creating a phantom future candle.
    const last = candles[candles.length - 1];
    if (!tick || !candleRef.current || !last) return;

    const barTime = toUTC(last.timestamp);
    const mid = (tick.bid + tick.ask) / 2;

    // lightweight-charts throws "Cannot update oldest data" if this is older
    // than the series' newest bar — which happens on a timeframe switch, when
    // setData() has replaced the series but this effect still closes over the
    // previous `candles`.
    if (!Number.isFinite(barTime)) return;
    if (lastBarTimeRef.current !== null && barTime < lastBarTimeRef.current) return;

    // Refuse a tick that cannot belong to this series. The deployed terminal
    // showed XAU/USD with the header at 3,299.85 and the candles at ~4,390, and
    // drew a vertical line plunging between them, because this wrote the tick
    // straight onto the last bar. A 25% gap is not a price move — it is two
    // sources disagreeing about the instrument, and rendering it as a candle
    // presents a data fault as a market event.
    if (tickIsOffScale(mid, last.close)) {
      if (!offScaleWarnedRef.current) {
        console.warn(
          `[Trading] ignoring off-scale tick for ${symbol}: tick mid=${mid} vs last bar close=${last.close}. ` +
          'The live feed and the OHLCV history disagree about this instrument.',
        );
        offScaleWarnedRef.current = true;
      }
      return;
    }

    candleRef.current.update({
      time:  barTime,
      open:  last.open,
      high:  Math.max(last.high, tick.ask),
      low:   Math.min(last.low,  tick.bid),
      close: mid,
    });
  }, [tick, candles]);

  useEffect(() => { volRef.current?.applyOptions({ visible: showVolume }); }, [showVolume]);
  useEffect(() => { maRef.current?.applyOptions({ visible: showMA }); }, [showMA]);

  const stats = useMemo(() => {
    const last = candles[candles.length - 1];
    // Bind then guard: `candles.length` being non-zero does not narrow
    // `candles[n]` for the compiler (audit #38).
    if (!last) return null;
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
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 z-20 bg-[#060d18]">
            <span className="text-[#ff1744] text-[12px]">⚠ {chartError}</span>
            <span className="text-slate-600 text-[10px]">Connect a broker or load historical data</span>
          </div>
        )}
        {/* Container is always rendered so the chart has a real size on init */}
        <div ref={containerRef} style={{ width: '100%', height: 340 }} />
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
            const isLong = positionSide(t) === 'long';  // F5-02
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
  const filtered = signals.filter((sig) => sameSymbol(sig.symbol, symbol));

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
            const _rrRisk = Math.abs(sig.entry_price - sig.stop_loss);
            const rr = sig.risk_reward ?? (
              sig.entry_price > 0 && sig.stop_loss > 0 && sig.take_profit > 0 && _rrRisk > 0
                ? Math.abs(sig.take_profit - sig.entry_price) / _rrRisk
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
      setError(extractApiError(e, 'Analysis failed'));
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
      qc.invalidateQueries({ queryKey: ['trades'] });
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Emergency stop failed'));
      setConfirming(false);
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
    // Full width when stacked, fixed 280px only in the xl three-column layout.
    // `w-[280px] shrink-0` unconditionally is what made the panels overlap.
    <div className="w-full xl:w-[280px] xl:shrink-0 flex flex-col gap-2 xl:overflow-y-auto">
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
    <div className="w-full xl:w-[280px] xl:shrink-0 flex flex-col gap-2 xl:overflow-hidden">
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
  const feedLive = useStore(selectFeedLive);
  const prices   = useStore((s) => s.prices);
  const tick     = prices[symbol];

  return (
    <div className="flex flex-col bg-[#060d18] text-slate-200 overflow-x-hidden overflow-y-auto" style={{ flex: 1, minHeight: 0, height: 0 }}>
      <TopBar
        symbol={symbol} setSymbol={setSymbol}
        timeframe={timeframe} setTimeframe={setTimeframe}
        tick={tick} wsStatus={wsStatus} feedLive={feedLive}
      />

      {/* Responsive terminal row.
          This was `flex flex-1 min-h-0 gap-2 p-2 overflow-hidden` — a fixed
          horizontal row holding two `w-[280px] shrink-0` panels either side of
          a flexible centre. Below roughly 1280px, 280 + centre + 280 + gaps
          exceeds the viewport; `shrink-0` forbids shrinking and
          `overflow-hidden` clips rather than scrolls, so the panels visibly
          overlapped on tablet widths.

          Now: stack vertically and let the page scroll below `xl`, switch to
          the three-column terminal layout at `xl` and above where there is
          genuinely room for it. */}
      <div className="flex flex-col xl:flex-row flex-1 min-h-0 gap-2 p-2 overflow-y-auto xl:overflow-hidden">
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
