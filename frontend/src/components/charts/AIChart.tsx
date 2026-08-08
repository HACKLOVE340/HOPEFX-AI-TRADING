/**
 * components/charts/AIChart.tsx
 * AI-overlaid candlestick chart using lightweight-charts v4.
 *
 * Features:
 *   - Candlestick + volume histogram + MA20 overlay
 *   - AI analysis overlay: entry zone, stop-loss, take-profit, key levels
 *   - Market regime badge + direction/confidence in the header
 *   - Auto-run analysis when OHLCV data loads (optional)
 *   - Manual re-run button with cooldown
 *
 * Wires to:
 *   GET  /api/trading/ohlcv/{symbol}
 *   POST /api/trading/ai-analysis
 *   GET  /api/trading/regime
 */

import React, {
  useEffect, useRef, useState, useCallback, useMemo,
} from 'react';
import {
  createChart, IChartApi, ISeriesApi,
  CandlestickSeries, LineSeries, HistogramSeries, LineStyle,
} from 'lightweight-charts';
import type { UTCTimestamp } from 'lightweight-charts';
import { useStore, selectIsAuth, useHasHydrated, selectPrice } from '../../store';
import { tradingApi } from '../../hooks/useApi';
import { ohlcvLimitFor } from '../../features/chart-bot/services/chart-api';
import { cn, fmtPrice, extractApiError } from '../../lib/utils';
import type { PriceTick } from '../../types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface OHLCVCandle {
  timestamp: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface AIResult {
  direction: string;
  confidence: number;
  reasoning: string;
  entry_zone?: [number, number];
  stop_loss?: number;
  take_profit?: number;
  key_levels?: number[];
  regime?: string;
}

interface AIChartProps {
  symbol:        string;
  timeframe?:    string;
  height?:       number;
  autoAnalyze?:  boolean;
  showBranding?: boolean;
  className?:    string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function apiSym(s: string) { return s.replace('/', '_'); }

function toUTC(ts: number | string): UTCTimestamp {
  if (typeof ts === 'string') return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
  return Math.floor(ts > 1_000_000_000_000 ? ts / 1000 : ts) as UTCTimestamp;
}

function regimeColor(r?: string): string {
  if (!r) return '#64748b';
  const l = r.toLowerCase();
  if (l.includes('bull') || l.includes('trend_up'))   return '#00e676';
  if (l.includes('bear') || l.includes('trend_down')) return '#ff1744';
  if (l.includes('range') || l.includes('chop'))      return '#ffb800';
  return '#00d4ff';
}

function dirColor(d?: string): string {
  if (d === 'long')  return '#00e676';
  if (d === 'short') return '#ff1744';
  return '#64748b';
}

function confColor(c: number): string {
  if (c >= 0.75) return '#00e676';
  if (c >= 0.55) return '#ffb800';
  return '#ff6b35';
}

function computeMA(candles: OHLCVCandle[], period: number): { time: UTCTimestamp; value: number }[] {
  return candles.flatMap((candle, i, arr) => {
    if (i < period - 1) return [];
    const avg = arr.slice(i - period + 1, i + 1).reduce((s, x) => s + x.close, 0) / period;
    return [{ time: toUTC(candle.timestamp), value: avg }];
  });
}

// ── AI overlay badge ──────────────────────────────────────────────────────────

function AIBadge({ result }: { result: AIResult }) {
  const dc = dirColor(result.direction);
  const cc = confColor(result.confidence);
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span
        className="text-[11px] font-bold uppercase px-1.5 py-0.5 rounded border"
        style={{ color: dc, borderColor: `${dc}40`, backgroundColor: `${dc}15` }}
      >
        {result.direction === 'long' ? '▲ LONG' : result.direction === 'short' ? '▼ SHORT' : '◆ NEUTRAL'}
      </span>
      <span className="text-[11px] font-bold tabular-nums" style={{ color: cc }}>
        {(result.confidence * 100).toFixed(0)}%
      </span>
      {result.regime && (
        <span
          className="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded"
          style={{
            color:           regimeColor(result.regime),
            backgroundColor: `${regimeColor(result.regime)}15`,
          }}
        >
          {result.regime}
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AIChart({
  symbol,
  timeframe    = '1h',
  height       = 360,
  autoAnalyze  = true,
  showBranding = false,
  className,
}: AIChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef       = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maRef        = useRef<ISeriesApi<'Line'> | null>(null);
  const rafRef       = useRef<number>(0);

  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  // F9-01: `selectPrice(symbol)` rather than the whole `prices` map. `setPrice`
  // gives the map a new identity on every tick of every instrument, so a
  // whole-map subscriber re-renders for symbols it never shows.
  const tickForSymbol = useStore(selectPrice(symbol));
  const tick     = tickForSymbol as PriceTick | undefined;

  const [aiResult,       setAiResult]       = useState<AIResult | null>(null);
  const [loading,        setLoading]        = useState(true);
  const [analyzing,      setAnalyzing]      = useState(false);
  const [chartError,     setChartError]     = useState<string | null>(null);
  const [aiError,        setAiError]        = useState<string | null>(null);
  const [candles,        setCandles]        = useState<OHLCVCandle[]>([]);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);

  // ── Chart initialisation (mount once) ─────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout:    { background: { color: '#060d18' }, textColor: '#64748b' },
      grid:      { vertLines: { color: '#0d1421' }, horzLines: { color: '#0d1421' } },
      rightPriceScale: { borderColor: '#1e2d3d' },
      timeScale: { borderColor: '#1e2d3d', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 1 },
      width:  containerRef.current.clientWidth,
      height,
    });

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', downColor: '#ff1744',
      borderUpColor: '#00e676', borderDownColor: '#ff1744',
      wickUpColor: '#00e676', wickDownColor: '#ff1744',
    });

    const vol = chart.addSeries(HistogramSeries, {
      color: '#1e2d3d',
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    const ma = chart.addSeries(LineSeries, {
      color: '#3b82f6',
      lineWidth: 1,
      priceLineVisible: false,
    });

    chartRef.current  = chart;
    candleRef.current = candle;
    volRef.current    = vol;
    maRef.current     = ma;

    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Load OHLCV on symbol/timeframe change + periodic refresh ──────────────

  const loadOhlcv = useCallback((initial = false) => {
    if (!candleRef.current || !hydrated || !isAuth) return;
    if (initial) { setLoading(true); setChartError(null); setAiResult(null); }

    // Load a meaningful history window per timeframe (e.g. ~1500 bars on 1h,
    // 8000 on daily) instead of a fixed 300 bars, which only covered ~12 days
    // of 1h candles — the "short history" the user saw on the chart.
    tradingApi.ohlcv(symbol, timeframe, ohlcvLimitFor(timeframe))
      .then((r) => {
        const raw  = r.data as OHLCVCandle[] | { data?: OHLCVCandle[] };
        const data = Array.isArray(raw) ? raw : (raw.data ?? []);
        if (!data.length) { if (initial) setChartError('No OHLCV data'); return; }

        const sorted = [...data].sort((a, b) => toUTC(a.timestamp) - toUTC(b.timestamp));
        setCandles(sorted);

        candleRef.current!.setData(sorted.map((c) => ({
          time: toUTC(c.timestamp),
          open: c.open, high: c.high, low: c.low, close: c.close,
        })));

        volRef.current?.setData(sorted.map((c) => ({
          time:  toUTC(c.timestamp),
          value: c.volume ?? 0,
          color: c.close >= c.open ? '#00e67630' : '#ff174430',
        })));

        maRef.current?.setData(computeMA(sorted, 20));

        if (initial) {
          chartRef.current?.timeScale().fitContent();
          chartRef.current?.timeScale().scrollToRealTime();
        }
      })
      .catch((err) => {
        if (!initial) return; // silent on background refresh
        setChartError(extractApiError(err, 'Failed to load chart'));
      })
      .finally(() => { if (initial) setLoading(false); });
  }, [symbol, timeframe, hydrated, isAuth]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadOhlcv(true);
    // Refresh candles every 30s to pick up new bars without a full reload
    const refreshTimer = setInterval(() => loadOhlcv(false), 30_000);
    return () => clearInterval(refreshTimer);
  }, [loadOhlcv]);

  // ── Live tick update — updates the current candle's close in real time ───

  useEffect(() => {
    // Use the last historical bar's open time so the tick updates the current
    // candle rather than creating a phantom future candle.
    const last = candles[candles.length - 1];
    if (!tick || !candleRef.current || !last) return;
    const barTime = toUTC(last.timestamp);
    const mid = tick.mid ?? ((tick.bid + tick.ask) / 2);
    candleRef.current.update({
      time:  barTime,
      open:  last.open,
      high:  Math.max(last.high, tick.ask),
      low:   Math.min(last.low,  tick.bid),
      close: mid,
    });
  }, [tick, candles]);

  // ── Apply AI overlays as price lines ─────────────────────────────────────

  type PriceLine = ReturnType<NonNullable<typeof candleRef.current>['createPriceLine']>;
  const priceLinesRef = useRef<PriceLine[]>([]);

  useEffect(() => {
    if (!candleRef.current) return;

    // Clear previous overlays
    priceLinesRef.current.forEach((pl) => {
      try { candleRef.current!.removePriceLine(pl); } catch { /* already removed */ }
    });
    priceLinesRef.current = [];

    if (!aiResult) return;

    const addLine = (
      price:   number,
      color:   string,
      title:   string,
      style:   LineStyle = LineStyle.Dashed,
    ) => {
      if (!candleRef.current || !price) return;
      const pl = candleRef.current.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: style,
        axisLabelVisible: true,
        title,
      });
      priceLinesRef.current.push(pl);
    };

    if (aiResult.stop_loss)   addLine(aiResult.stop_loss,   '#ff1744', 'SL');
    if (aiResult.take_profit) addLine(aiResult.take_profit, '#00e676', 'TP');

    if (aiResult.entry_zone) {
      addLine(aiResult.entry_zone[0], '#ffb800', 'Entry Lo', LineStyle.Dotted);
      addLine(aiResult.entry_zone[1], '#ffb800', 'Entry Hi', LineStyle.Dotted);
    }

    aiResult.key_levels?.forEach((lvl, i) => {
      addLine(lvl, '#475569', `L${i + 1}`, LineStyle.Dotted);
    });
  }, [aiResult]);

  // ── Run AI analysis ────────────────────────────────────────────────────────

  const runAnalysis = useCallback(async () => {
    setAnalyzing(true);
    setAiError(null);
    try {
      const r = await tradingApi.aiAnalysis({
        symbol:    apiSym(symbol),
        price:     tick?.mid ?? tick?.ask ?? 0,
        timeframe,
      });
      setAiResult(r.data as AIResult);
      setLastAnalyzedAt(new Date().toLocaleTimeString());
    } catch (e: unknown) {
      setAiError(extractApiError(e, 'AI analysis failed'));
    } finally {
      setAnalyzing(false);
    }
  }, [symbol, tick, timeframe]);

  // Auto-analyze once OHLCV data is loaded
  useEffect(() => {
    if (autoAnalyze && candles.length > 0 && !aiResult && !analyzing) {
      runAnalysis();
    }
  }, [candles.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── OHLC stats from latest candle ─────────────────────────────────────────

  const stats = useMemo(() => {
    const last = candles[candles.length - 1];
    // Bind then guard: a non-zero length does not narrow candles[n] (audit #38).
    if (!last) return null;
    const prev = candles.length > 1 ? candles[candles.length - 2] : null;
    const chg  = prev ? ((last.close - prev.close) / prev.close) * 100 : 0;
    return { last, chg };
  }, [candles]);

  return (
    <div className={cn('flex flex-col bg-[#0d1421] border border-[#1e2d3d] rounded-lg overflow-hidden', className)}>

      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1e2d3d] flex-wrap">

        {showBranding && (
          <>
            <span className="text-[11px] font-bold text-[#00d4ff] tracking-widest">HOPEFX</span>
            <div className="w-px h-3 bg-[#1e2d3d]" />
          </>
        )}

        <span className="text-[12px] font-bold text-slate-200">{symbol}</span>
        <span className="text-[10px] text-slate-600 font-mono bg-[#1e2d3d] px-1.5 py-0.5 rounded">
          {timeframe}
        </span>

        {/* OHLC stats */}
        {stats && (
          <div className="flex items-center gap-3 text-[10px] tabular-nums">
            <span className="text-slate-600">O <span className="text-slate-400">{fmtPrice(stats.last.open)}</span></span>
            <span className="text-slate-600">H <span className="text-[#00e676]">{fmtPrice(stats.last.high)}</span></span>
            <span className="text-slate-600">L <span className="text-[#ff1744]">{fmtPrice(stats.last.low)}</span></span>
            <span className="text-slate-600">C <span className="text-slate-200 font-semibold">{fmtPrice(stats.last.close)}</span></span>
            <span className={cn('font-semibold', stats.chg >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]')}>
              {stats.chg >= 0 ? '+' : ''}{stats.chg.toFixed(2)}%
            </span>
          </div>
        )}

        <div className="flex-1" />

        {/* AI result badge */}
        {aiResult && <AIBadge result={aiResult} />}

        {/* AI run button */}
        <button
          onClick={runAnalysis}
          disabled={analyzing || loading}
          title={lastAnalyzedAt ? `Last: ${lastAnalyzedAt}` : 'Run AI analysis'}
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded text-[10px] font-bold border transition-colors',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            analyzing
              ? 'bg-[#1e3a5f]/60 border-[#3b82f6]/40 text-[#60a5fa] animate-pulse'
              : 'bg-[#1e3a5f]/40 border-[#3b82f6]/30 text-[#60a5fa] hover:bg-[#1e3a5f]/70',
          )}
        >
          {analyzing ? '⚡ …' : '⚡ AI'}
        </button>
      </div>

      {/* ── AI error ───────────────────────────────────────────────── */}
      {aiError && (
        <div className="px-3 py-1.5 text-[10px] text-[#ff1744] bg-[#ff1744]/5 border-b border-[#ff1744]/10">
          {aiError}
        </div>
      )}

      {/* ── Chart ──────────────────────────────────────────────────── */}
      <div className="relative" style={{ height }}>
        {(loading || analyzing) && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#060d18]/70 z-10 pointer-events-none">
            <span className="text-[11px] text-slate-500 animate-pulse">
              {loading ? 'Loading chart…' : 'Analysing…'}
            </span>
          </div>
        )}
        {chartError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 z-20 bg-[#060d18]">
            <span className="text-[#ff1744] text-[11px]">⚠ {chartError}</span>
            <span className="text-slate-600 text-[10px]">Connect a data feed or load historical data</span>
          </div>
        )}
        {/* Container always rendered so the chart canvas has a real size on init */}
        <div ref={containerRef} style={{ width: '100%', height }} />
      </div>

      {/* ── AI analysis text summary ────────────────────────────────── */}
      {aiResult?.reasoning && (
        <div className="px-3 py-2 border-t border-[#1e2d3d] flex flex-col gap-1">
          <div className="flex items-center gap-3 text-[10px] tabular-nums flex-wrap">
            {aiResult.stop_loss && (
              <span className="text-slate-600">
                SL <span className="text-[#ff1744] font-semibold">{fmtPrice(aiResult.stop_loss)}</span>
              </span>
            )}
            {aiResult.take_profit && (
              <span className="text-slate-600">
                TP <span className="text-[#00e676] font-semibold">{fmtPrice(aiResult.take_profit)}</span>
              </span>
            )}
            {aiResult.entry_zone && (
              <span className="text-slate-600">
                Entry{' '}
                <span className="text-[#ffb800] font-semibold">
                  {fmtPrice(aiResult.entry_zone[0])} – {fmtPrice(aiResult.entry_zone[1])}
                </span>
              </span>
            )}
            {aiResult.stop_loss && aiResult.take_profit && (
              (() => {
                const mid  = aiResult.entry_zone
                  ? (aiResult.entry_zone[0] + aiResult.entry_zone[1]) / 2
                  : tick?.mid ?? 0;
                const risk = Math.abs(mid - aiResult.stop_loss);
                const rwd  = Math.abs(aiResult.take_profit - mid);
                const rr   = risk > 0 ? rwd / risk : 0;
                return (
                  <span className="text-slate-600">
                    R:R{' '}
                    <span className={cn('font-semibold', rr >= 2 ? 'text-[#00e676]' : 'text-[#ffb800]')}>
                      1:{rr.toFixed(1)}
                    </span>
                  </span>
                );
              })()
            )}
          </div>
          <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-2">
            {aiResult.reasoning}
          </p>
        </div>
      )}
    </div>
  );
}

export default AIChart;
