/**
 * CoreChart.tsx
 * Ultra-high-performance TradingView Lightweight Charts candlestick engine.
 * Features: real-time OHLCV, bid/ask spread overlay, volume delta bars,
 * AI signal markers, click-to-analyze, 60fps resize handling.
 */

import React, {
  useEffect, useRef, useCallback, useState, memo,
} from 'react';
import {
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  PriceScaleMode,
  UTCTimestamp,
  CandlestickData,
  HistogramData,
  LineData,
  MouseEventParams,
  SeriesMarker,
  Time,
} from 'lightweight-charts';
import { useChartBotStore } from '../store/chart-bot-store';
import { useOHLCV } from '../hooks/useChartData';
import { ohlcvLimitFor } from '../services/chart-api';
import { ema, bollinger, rsi } from '../utils/indicators';
import { COLORS, CHART_DIMS } from '../utils/design-tokens';
import { fmtSpread } from '../../../lib/utils';
import { formatPrice, formatTime } from '../utils/formatters';
import type { OHLCVBar, MLSignal, SupportResistanceLevel, ChartPattern, ChartClickContext } from '../types';

// ─── Constants ────────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];

// Symbols the user can switch between (slash form — the backend normalises).
const SYMBOLS = ['XAU/USD', 'XAG/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];

// Indicator toggles available in the toolbar.
type IndicatorKey = 'ema20' | 'ema50' | 'bb' | 'rsi';
const INDICATORS: { key: IndicatorKey; label: string }[] = [
  { key: 'ema20', label: 'EMA 20' },
  { key: 'ema50', label: 'EMA 50' },
  { key: 'bb',    label: 'BB' },
  { key: 'rsi',   label: 'RSI' },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toUTC(ts: number): UTCTimestamp {
  return (ts > 1e10 ? Math.floor(ts / 1000) : ts) as UTCTimestamp;
}

function barToCandle(b: OHLCVBar): CandlestickData {
  return { time: toUTC(b.time), open: b.open, high: b.high, low: b.low, close: b.close };
}

// ─── Crosshair Info Bar ───────────────────────────────────────────────────────

interface CrosshairInfo {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  changePct: number;
}

const CrosshairBar = memo(({ info, bid, ask }: { info: CrosshairInfo | null; bid: number; ask: number }) => {
  const spread = ask - bid;
  const s = styles;
  return (
    <div style={s.crosshairBar}>
      {info ? (
        <>
          <span style={s.chTime}>{info.time}</span>
          <span style={s.chLabel}>O <span style={s.chVal}>{formatPrice(info.open)}</span></span>
          <span style={s.chLabel}>H <span style={{ ...s.chVal, color: COLORS.profit.base }}>{formatPrice(info.high)}</span></span>
          <span style={s.chLabel}>L <span style={{ ...s.chVal, color: COLORS.loss.base }}>{formatPrice(info.low)}</span></span>
          <span style={s.chLabel}>C <span style={s.chVal}>{formatPrice(info.close)}</span></span>
          <span style={s.chLabel}>Vol <span style={s.chVal}>{info.volume.toFixed(0)}</span></span>
          <span style={{ ...s.chLabel, color: info.change >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
            {info.change >= 0 ? '+' : ''}{formatPrice(info.change)} ({info.changePct >= 0 ? '+' : ''}{info.changePct.toFixed(2)}%)
          </span>
        </>
      ) : (
        <>
          <span style={s.chLabel}>Bid <span style={{ ...s.chVal, color: COLORS.profit.base }}>{formatPrice(bid)}</span></span>
          <span style={s.chLabel}>Ask <span style={{ ...s.chVal, color: COLORS.loss.base }}>{formatPrice(ask)}</span></span>
          <span style={s.chLabel}>Spread <span style={{ ...s.chVal, color: COLORS.neon.gold }}>{spread > 0 ? fmtSpread(spread) : '—'}</span></span>
        </>
      )}
    </div>
  );
});
CrosshairBar.displayName = 'CrosshairBar';

// ─── Timeframe Selector ───────────────────────────────────────────────────────

const TFSelector = memo(({ value, onChange }: { value: string; onChange: (tf: string) => void }) => (
  <div style={styles.tfRow}>
    {TIMEFRAMES.map((tf) => (
      <button
        key={tf}
        onClick={() => onChange(tf)}
        style={{ ...styles.tfBtn, ...(value === tf ? styles.tfBtnActive : {}) }}
      >
        {tf}
      </button>
    ))}
  </div>
));
TFSelector.displayName = 'TFSelector';

// ─── Indicator Selector ─────────────────────────────────────────────────────

const IndicatorSelector = memo(
  ({ active, onToggle }: { active: Record<IndicatorKey, boolean>; onToggle: (k: IndicatorKey) => void }) => (
    <div style={styles.tfRow}>
      {INDICATORS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onToggle(key)}
          style={{ ...styles.tfBtn, ...(active[key] ? styles.tfBtnActive : {}) }}
          title={`Toggle ${label}`}
        >
          {label}
        </button>
      ))}
    </div>
  ),
);
IndicatorSelector.displayName = 'IndicatorSelector';

// ─── Main Component ───────────────────────────────────────────────────────────

interface CoreChartProps {
  onChartClick?: (ctx: ChartClickContext) => void;
  onChartReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void;
  signals?: MLSignal[];
  levels?: SupportResistanceLevel[];
  /** Detected chart patterns, used to tell the bot what the click landed inside. */
  patterns?: ChartPattern[];
  height?: number;
}

const CoreChart: React.FC<CoreChartProps> = ({
  onChartClick,
  onChartReady,
  signals = [],
  levels = [],
  patterns = [],
  height = CHART_DIMS.mainHeight,
}) => {
  const wrapperRef       = useRef<HTMLDivElement>(null);
  const containerRef     = useRef<HTMLDivElement>(null);
  const chartRef         = useRef<IChartApi | null>(null);
  const candleRef        = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef           = useRef<ISeriesApi<'Histogram'> | null>(null);
  const bidRef           = useRef<ISeriesApi<'Line'> | null>(null);
  const askRef           = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef       = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const barsRef          = useRef<OHLCVBar[]>([]);
  const rafRef           = useRef<number>(0);
  // Stable ref so the chart-init effect doesn't re-run when the callback identity changes
  const onChartReadyRef  = useRef(onChartReady);
  useEffect(() => { onChartReadyRef.current = onChartReady; }, [onChartReady]);

  const symbol     = useChartBotStore((s) => s.symbol);
  const timeframe  = useChartBotStore((s) => s.timeframe);
  const liveTick   = useChartBotStore((s) => s.liveTick);
  const setTF      = useChartBotStore((s) => s.setTimeframe);
  const setSymbol  = useChartBotStore((s) => s.setSymbol);
  const setReady   = useChartBotStore((s) => s.setChartReady);
  const setCtx     = useChartBotStore((s) => s.setClickContext);

  const [crosshair, setCrosshair] = useState<CrosshairInfo | null>(null);
  const [indicators, setIndicators] = useState<Record<IndicatorKey, boolean>>({
    ema20: false, ema50: false, bb: false, rsi: false,
  });
  const [isFullscreen, setIsFullscreen] = useState(false);

  const toggleIndicator = useCallback((k: IndicatorKey) => {
    setIndicators((prev) => ({ ...prev, [k]: !prev[k] }));
  }, []);

  const { data: bars, isLoading, isError } = useOHLCV(symbol, timeframe, ohlcvLimitFor(timeframe));

  // The click handler is registered once, inside the chart-init effect. Anything
  // it reads from the closure is frozen at mount — which is how the analysis
  // ended up pinned to a single instrument. These refs keep it current.
  const symbolRef    = useRef(symbol);
  const timeframeRef = useRef(timeframe);
  const signalsRef   = useRef<MLSignal[]>(signals);
  const levelsRef    = useRef<SupportResistanceLevel[]>(levels);
  const patternsRef  = useRef<ChartPattern[]>(patterns);
  useEffect(() => { symbolRef.current = symbol; }, [symbol]);
  useEffect(() => { timeframeRef.current = timeframe; }, [timeframe]);
  useEffect(() => { signalsRef.current = signals; }, [signals]);
  useEffect(() => { levelsRef.current = levels; }, [levels]);
  useEffect(() => { patternsRef.current = patterns; }, [patterns]);

  // Nearest support/resistance to the clicked price, within 1% of it. Beyond
  // that the "nearest" level is not near anything and saying so is better than
  // attaching an irrelevant one.
  const nearestLevelRef = useRef((clickPrice: number): SupportResistanceLevel | null => {
    let best: SupportResistanceLevel | null = null;
    let bestGap = Number.POSITIVE_INFINITY;
    for (const l of levelsRef.current) {
      const gap = Math.abs(l.price - clickPrice);
      if (gap < bestGap) { bestGap = gap; best = l; }
    }
    return clickPrice > 0 && bestGap / clickPrice <= 0.01 ? best : null;
  });

  // A pattern whose span contains the clicked bar. No "nearest" fallback: a
  // pattern the click is not inside is not the pattern the user asked about.
  const nearestPatternRef = useRef((clickMs: number): ChartPattern | null => {
    let best: ChartPattern | null = null;
    for (const p of patternsRef.current) {
      if (clickMs >= p.startTime && clickMs <= p.endTime) {
        if (!best || p.confidence > best.confidence) best = p;
      }
    }
    return best;
  });

  // Nearest ML signal to a clicked bar, within one hour. Populating this is what
  // makes the bot's "ML FEATURE IMPORTANCE" panel render: it read
  // `context.nearestSignal.features`, and this was hard-coded `null`.
  const nearestSignalRef = useRef((clickMs: number): MLSignal | null => {
    let best: MLSignal | null = null;
    let bestGap = Number.POSITIVE_INFINITY;
    for (const s of signalsRef.current) {
      const gap = Math.abs(new Date(s.generated_at).getTime() - clickMs);
      if (gap < bestGap) { bestGap = gap; best = s; }
    }
    return bestGap <= 3_600_000 ? best : null;
  });

  // ── Chart initialisation ──────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: COLORS.bg.void },
        textColor:  COLORS.text.secondary,
        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
        fontSize:   11,
      },
      grid: {
        vertLines: { color: COLORS.bg.surface, style: 1 },
        horzLines: { color: COLORS.bg.surface, style: 1 },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.bg.divider, width: 1, style: 1, labelBackgroundColor: COLORS.bg.elevated },
        horzLine: { color: COLORS.bg.divider, width: 1, style: 1, labelBackgroundColor: COLORS.bg.elevated },
      },
      rightPriceScale: {
        borderColor:  COLORS.bg.border,
        textColor:    COLORS.text.secondary,
        mode:         PriceScaleMode.Normal,
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor:       COLORS.bg.border,
        timeVisible:       true,
        secondsVisible:    false,
        rightOffset:       8,
        barSpacing:        8,
        fixLeftEdge:       false,
        lockVisibleTimeRangeOnResize: true,
      },
      width:  containerRef.current.clientWidth,
      height: height - CHART_DIMS.volumeHeight,
    });

    // Candlestick series
    const candle = chart.addSeries(CandlestickSeries, {
      upColor:        COLORS.chart.candleUp,
      downColor:      COLORS.chart.candleDown,
      borderUpColor:  COLORS.chart.candleUp,
      borderDownColor:COLORS.chart.candleDown,
      wickUpColor:    COLORS.chart.wickUp,
      wickDownColor:  COLORS.chart.wickDown,
    });

    // Volume histogram (overlaid on separate price scale)
    const vol = chart.addSeries(HistogramSeries, {
      color:      COLORS.chart.volume,
      priceFormat:{ type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
    });

    // Bid line
    const bid = chart.addSeries(LineSeries, {
      color:     COLORS.chart.bidLine,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    // Ask line
    const ask = chart.addSeries(LineSeries, {
      color:     COLORS.chart.askLine,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    chartRef.current   = chart;
    candleRef.current  = candle;
    volRef.current     = vol;
    bidRef.current     = bid;
    askRef.current     = ask;
    // v5: markers are a plugin, not a series method
    markersRef.current = createSeriesMarkers(candle);

    // Notify parent so AIOverlays can get coordinate-conversion refs
    onChartReadyRef.current?.(chart, candle);

    // Crosshair move handler
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param.time || !param.seriesData) {
        setCrosshair(null);
        return;
      }
      const cd = param.seriesData.get(candle) as CandlestickData | undefined;
      if (!cd) { setCrosshair(null); return; }
      const bar = barsRef.current.find((b) => toUTC(b.time) === cd.time);
      setCrosshair({
        time:      formatTime((cd.time as number) * 1000),
        open:      cd.open,
        high:      cd.high,
        low:       cd.low,
        close:     cd.close,
        volume:    bar?.volume ?? 0,
        change:    cd.close - cd.open,
        changePct: cd.open ? ((cd.close - cd.open) / cd.open) * 100 : 0,
      });
    });

    // Click handler → AI analysis context
    chart.subscribeClick((param: MouseEventParams) => {
      if (!param.time || !param.seriesData) return;
      const cd = param.seriesData.get(candle) as CandlestickData | undefined;
      if (!cd) return;
      const bar = barsRef.current.find((b) => toUTC(b.time) === cd.time) ?? null;
      const clickTime = (cd.time as number) * 1000;
      const ctx: ChartClickContext = {
        // Read from refs, not the closure: this callback is registered once when
        // the chart is created, so closing over `symbol`/`timeframe` would pin
        // the analysis to whatever was selected at mount.
        symbol:         symbolRef.current,
        timeframe:      timeframeRef.current,
        price:          cd.close,
        time:           clickTime,
        bar:            bar,
        nearestSignal:  nearestSignalRef.current(clickTime),
        nearestLevel:   nearestLevelRef.current(cd.close),
        nearestPattern: nearestPatternRef.current(clickTime),
      };
      setCtx(ctx);
      onChartClick?.(ctx);
    });

    setReady(true);

    // rAF-throttled ResizeObserver — prevents layout thrashing at 60fps
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      setReady(false);
      chart.remove();
      chartRef.current   = null;
      candleRef.current  = null;
      volRef.current     = null;
      bidRef.current     = null;
      askRef.current     = null;
      markersRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // ── Load historical bars ──────────────────────────────────────────────────

  useEffect(() => {
    if (!candleRef.current || !volRef.current) return;

    // Depend on `symbol` too: on a symbol switch, useOHLCV's data goes undefined
    // while the new key loads. Without this branch the effect early-returned and
    // the PREVIOUS symbol's candles stayed painted under the new symbol's label —
    // so the picker changed but the chart looked frozen, and worse, showed one
    // instrument's price action as another's. Clear the series so the chart is
    // honestly empty until the selected symbol's bars arrive.
    if (!bars || bars.length === 0) {
      barsRef.current = [];
      candleRef.current.setData([]);
      volRef.current.setData([]);
      return;
    }
    barsRef.current = bars;

    const candles: CandlestickData[] = bars.map(barToCandle);
    const volumes: HistogramData[]   = bars.map((b) => ({
      time:  toUTC(b.time),
      value: b.volume,
      color: b.close >= b.open ? COLORS.chart.volumeBuy : COLORS.chart.volumeSell,
    }));

    candleRef.current.setData(candles);
    volRef.current.setData(volumes);
    chartRef.current?.timeScale().fitContent();
    chartRef.current?.timeScale().scrollToRealTime();
  }, [bars, symbol]);

  // ── Live tick updates ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!liveTick || !candleRef.current) return;

    // Align to the current bar's open time — prevents phantom future candles.
    const lastBar = barsRef.current[barsRef.current.length - 1];
    if (!lastBar) return;
    const barTime = toUTC(lastBar.time);

    const updatedCandle: CandlestickData = {
      time:  barTime,
      open:  lastBar.open,
      high:  Math.max(lastBar.high, liveTick.ask),
      low:   Math.min(lastBar.low,  liveTick.bid),
      close: liveTick.mid,
    };
    candleRef.current.update(updatedCandle);

    // Bid/ask lines — use update() not setData() to avoid series reset flicker.
    // Both lines share the same bar time so they render as horizontal price levels.
    if (bidRef.current && askRef.current) {
      const bidPoint: LineData = { time: barTime, value: liveTick.bid };
      const askPoint: LineData = { time: barTime, value: liveTick.ask };
      bidRef.current.update(bidPoint);
      askRef.current.update(askPoint);
    }
  }, [liveTick]);

  // ── Signal markers (v5: createSeriesMarkers plugin) ──────────────────────

  useEffect(() => {
    if (!markersRef.current) return;
    const markers: SeriesMarker<Time>[] = signals
      .filter((s) => s.status === 'active')
      .map((s) => ({
        time:     toUTC(new Date(s.generated_at).getTime() / 1000),
        position: s.direction === 'long' ? 'belowBar' as const : 'aboveBar' as const,
        color:    s.direction === 'long' ? COLORS.profit.base : COLORS.loss.base,
        shape:    s.direction === 'long' ? 'arrowUp' as const : 'arrowDown' as const,
        text:     `${s.direction.toUpperCase()} ${(s.confidence * 100).toFixed(0)}%`,
        size:     2,
      }));
    markersRef.current.setMarkers(markers);
  }, [signals]);

  // ── S/R level price lines ─────────────────────────────────────────────────

  useEffect(() => {
    if (!candleRef.current) return;
    // Remove old price lines by recreating series options isn't possible directly;
    // we use the priceLine API instead
    levels.forEach((lvl) => {
      candleRef.current?.createPriceLine({
        price:       lvl.price,
        color:       lvl.type === 'support' ? COLORS.chart.support
                   : lvl.type === 'resistance' ? COLORS.chart.resistance
                   : COLORS.chart.pivot,
        lineWidth:   1,
        lineStyle:   lvl.aiGenerated ? 0 : 2,
        axisLabelVisible: true,
        title:       `${lvl.type.toUpperCase()} (${(lvl.strength * 100).toFixed(0)}%)`,
      });
    });
  }, [levels]);

  // ── Technical indicators (EMA / Bollinger / RSI) ──────────────────────────
  // Recreate active overlay series whenever toggles or bars change; the cleanup
  // removes them so toggling off (or switching symbol/timeframe) leaves no
  // orphan series or empty RSI pane.

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !bars || bars.length === 0) return;

    const created: ISeriesApi<'Line'>[] = [];
    const addLine = (color: string, data: LineData[], opts?: { lineWidth?: 1 | 2; pane?: number }) => {
      const series = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: opts?.lineWidth ?? 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        opts?.pane,
      );
      series.setData(data);
      created.push(series);
      return series;
    };

    if (indicators.ema20) addLine(COLORS.neon.cyan, ema(bars, 20));
    if (indicators.ema50) addLine(COLORS.neon.gold, ema(bars, 50));
    if (indicators.bb) {
      const bb = bollinger(bars, 20, 2);
      addLine(COLORS.chart.bidLine, bb.upper, { lineWidth: 1 });
      addLine(COLORS.text.muted, bb.middle, { lineWidth: 1 });
      addLine(COLORS.chart.askLine, bb.lower, { lineWidth: 1 });
    }
    if (indicators.rsi) {
      // RSI lives in its own pane (index 1) on a 0–100 scale.
      const rsiSeries = addLine(COLORS.neon.purple, rsi(bars, 14), { lineWidth: 1, pane: 1 });
      rsiSeries.createPriceLine({ price: 70, color: COLORS.loss.base, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '70' });
      rsiSeries.createPriceLine({ price: 30, color: COLORS.profit.base, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '30' });
    }

    return () => {
      created.forEach((s) => {
        try { chart.removeSeries(s); } catch { /* chart already disposed */ }
      });
    };
  }, [indicators, bars]);

  // ── Fullscreen ────────────────────────────────────────────────────────────

  const toggleFullscreen = useCallback(() => {
    const el = wrapperRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen?.().catch(() => { /* ignore */ });
    } else {
      document.exitFullscreen?.().catch(() => { /* ignore */ });
    }
  }, []);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const bid = liveTick?.bid ?? 0;
  const ask = liveTick?.ask ?? 0;
  const noData = !isLoading && (isError || !bars || bars.length === 0);

  return (
    <div ref={wrapperRef} style={styles.wrapper}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            style={styles.symbolSelect}
            title="Select instrument"
          >
            {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={{ ...styles.priceText, color: liveTick ? (liveTick.change_pct >= 0 ? COLORS.profit.base : COLORS.loss.base) : COLORS.text.muted }}>
            {liveTick ? formatPrice(liveTick.mid) : '—'}
          </span>
          {liveTick && (
            <span style={{ ...styles.changeBadge, background: liveTick.change_pct >= 0 ? COLORS.profit.bg : COLORS.loss.bg, color: liveTick.change_pct >= 0 ? COLORS.profit.base : COLORS.loss.base, border: `1px solid ${liveTick.change_pct >= 0 ? COLORS.profit.border : COLORS.loss.border}` }}>
              {liveTick.change_pct >= 0 ? '+' : ''}{liveTick.change_pct.toFixed(2)}%
            </span>
          )}
        </div>
        <div style={styles.headerRight}>
          <IndicatorSelector active={indicators} onToggle={toggleIndicator} />
          <TFSelector value={timeframe} onChange={setTF} />
          <button onClick={toggleFullscreen} style={styles.tfBtn} title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
            {isFullscreen ? '⤢' : '⤡'}
          </button>
        </div>
      </div>

      {/* Crosshair info */}
      <CrosshairBar info={crosshair} bid={bid} ask={ask} />

      {/* Chart canvas */}
      <div style={{ position: 'relative' }}>
        {isLoading && (
          <div style={styles.loadingOverlay}>
            <div style={styles.loadingDot} />
            <span style={styles.loadingText}>Loading market data…</span>
          </div>
        )}
        {noData && (
          <div style={styles.loadingOverlay}>
            <span style={styles.loadingText}>
              No market data for {symbol} {timeframe} yet — fetching from the
              live price layer. If this persists, check your internet connection.
            </span>
          </div>
        )}
        <div ref={containerRef} style={{ width: '100%', height }} />
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    background: COLORS.bg.void,
    borderRadius: 8,
    overflow: 'hidden',
    border: `1px solid ${COLORS.bg.border}`,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px 8px',
    borderBottom: `1px solid ${COLORS.bg.surface}`,
    flexWrap: 'wrap',
    gap: 8,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  symbolText: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 15,
    fontWeight: 700,
    color: COLORS.text.primary,
    letterSpacing: '0.04em',
  },
  symbolSelect: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 14,
    fontWeight: 700,
    color: COLORS.text.primary,
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 4,
    padding: '4px 8px',
    letterSpacing: '0.04em',
    cursor: 'pointer',
  },
  priceText: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 22,
    fontWeight: 700,
    letterSpacing: '-0.02em',
  },
  changeBadge: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    fontWeight: 600,
    padding: '2px 7px',
    borderRadius: 4,
    letterSpacing: '0.04em',
  },
  tfRow: {
    display: 'flex',
    gap: 3,
  },
  tfBtn: {
    background: 'transparent',
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 4,
    color: COLORS.text.muted,
    cursor: 'pointer',
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    fontWeight: 600,
    padding: '4px 8px',
    letterSpacing: '0.04em',
    transition: 'all 100ms ease',
  },
  tfBtnActive: {
    background: COLORS.bg.elevated,
    borderColor: COLORS.neon.cyan,
    color: COLORS.neon.cyan,
  },
  crosshairBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    padding: '5px 14px',
    background: COLORS.bg.surface,
    borderBottom: `1px solid ${COLORS.bg.border}`,
    flexWrap: 'wrap',
    minHeight: 28,
  },
  chTime: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    color: COLORS.text.muted,
    letterSpacing: '0.04em',
  },
  chLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    color: COLORS.text.muted,
    letterSpacing: '0.04em',
  },
  chVal: {
    color: COLORS.text.primary,
    fontWeight: 600,
    marginLeft: 3,
  },
  loadingOverlay: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    background: 'rgba(2,4,8,0.7)',
    zIndex: 10,
  },
  loadingDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: COLORS.neon.cyan,
    animation: 'pulse 1s infinite',
  },
  loadingText: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 12,
    color: COLORS.text.secondary,
    letterSpacing: '0.08em',
  },
};

export default memo(CoreChart);
