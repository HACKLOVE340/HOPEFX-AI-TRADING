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
import { COLORS, CHART_DIMS } from '../utils/design-tokens';
import { formatPrice, formatTime } from '../utils/formatters';
import type { OHLCVBar, MLSignal, SupportResistanceLevel, ChartClickContext } from '../types';

// ─── Constants ────────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];

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
          <span style={s.chLabel}>Spread <span style={{ ...s.chVal, color: COLORS.neon.gold }}>{spread > 0 ? (spread * 100).toFixed(1) + ' pts' : '—'}</span></span>
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

// ─── Main Component ───────────────────────────────────────────────────────────

interface CoreChartProps {
  onChartClick?: (ctx: ChartClickContext) => void;
  onChartReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick'>) => void;
  signals?: MLSignal[];
  levels?: SupportResistanceLevel[];
  height?: number;
}

const CoreChart: React.FC<CoreChartProps> = ({
  onChartClick,
  onChartReady,
  signals = [],
  levels = [],
  height = CHART_DIMS.mainHeight,
}) => {
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
  const setReady   = useChartBotStore((s) => s.setChartReady);
  const setCtx     = useChartBotStore((s) => s.setClickContext);

  const [crosshair, setCrosshair] = useState<CrosshairInfo | null>(null);

  const { data: bars, isLoading } = useOHLCV(symbol, timeframe, 500);

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
        changePct: ((cd.close - cd.open) / cd.open) * 100,
      });
    });

    // Click handler → AI analysis context
    chart.subscribeClick((param: MouseEventParams) => {
      if (!param.time || !param.seriesData) return;
      const cd = param.seriesData.get(candle) as CandlestickData | undefined;
      if (!cd) return;
      const bar = barsRef.current.find((b) => toUTC(b.time) === cd.time) ?? null;
      const ctx: ChartClickContext = {
        price:          cd.close,
        time:           (cd.time as number) * 1000,
        bar:            bar,
        nearestSignal:  null,
        nearestLevel:   null,
        nearestPattern: null,
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
    if (!bars || !candleRef.current || !volRef.current) return;
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
  }, [bars]);

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

  const bid = liveTick?.bid ?? 0;
  const ask = liveTick?.ask ?? 0;

  return (
    <div style={styles.wrapper}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.symbolText}>{symbol}</span>
          <span style={{ ...styles.priceText, color: liveTick ? (liveTick.change_pct >= 0 ? COLORS.profit.base : COLORS.loss.base) : COLORS.text.muted }}>
            {liveTick ? formatPrice(liveTick.mid) : '—'}
          </span>
          {liveTick && (
            <span style={{ ...styles.changeBadge, background: liveTick.change_pct >= 0 ? COLORS.profit.bg : COLORS.loss.bg, color: liveTick.change_pct >= 0 ? COLORS.profit.base : COLORS.loss.base, border: `1px solid ${liveTick.change_pct >= 0 ? COLORS.profit.border : COLORS.loss.border}` }}>
              {liveTick.change_pct >= 0 ? '+' : ''}{liveTick.change_pct.toFixed(2)}%
            </span>
          )}
        </div>
        <TFSelector value={timeframe} onChange={setTF} />
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
  symbolText: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 15,
    fontWeight: 700,
    color: COLORS.text.primary,
    letterSpacing: '0.04em',
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
