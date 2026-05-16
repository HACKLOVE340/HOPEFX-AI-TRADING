/**
 * NuclearCandleChart.tsx
 * Nuclear-grade XAUUSD candlestick chart with:
 * - Live OHLCV via Lightweight Charts
 * - AI prediction path + confidence cones (shaded area series)
 * - Signal strength shading (green high-confidence, red abstain)
 * - Nuclear event annotations with exact reasons
 * - Red overlay zone on severity ≥ 7
 * - Timeframe selector (1m / 5m / 1h)
 */

import React, {
  useEffect, useRef, useCallback, useState, memo,
} from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickSeries,
  LineSeries,
  AreaSeries,
  CrosshairMode,
  UTCTimestamp,
  CandlestickData,
  LineData,
  AreaData,
  createSeriesMarkers,
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
} from 'lightweight-charts';
import { useNuclearStore, selectActiveBars } from '../store/nuclear-store';
import { severityColor, actionColor } from '../types/nuclear';
import type { OHLCVBar, PredictionPoint, NuclearEvent } from '../types/nuclear';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toUTC(ts: number): UTCTimestamp {
  return (ts > 1e10 ? Math.floor(ts / 1000) : ts) as UTCTimestamp;
}

function barToCandle(b: OHLCVBar): CandlestickData {
  return { time: toUTC(b.time), open: b.open, high: b.high, low: b.low, close: b.close };
}

// ─── Timeframe selector ───────────────────────────────────────────────────────

const TF_OPTIONS = ['1m', '5m', '1h'] as const;
type TF = typeof TF_OPTIONS[number];

const TimeframeSelector = memo(({
  active, onChange,
}: { active: TF; onChange: (tf: TF) => void }) => (
  <div style={s.tfRow}>
    {TF_OPTIONS.map((tf) => (
      <button
        key={tf}
        style={{
          ...s.tfBtn,
          background: active === tf ? '#1e3a5f' : 'transparent',
          color: active === tf ? '#60a5fa' : '#475569',
          borderColor: active === tf ? '#3b82f6' : '#1a2e4a',
        }}
        onClick={() => onChange(tf)}
      >
        {tf}
      </button>
    ))}
  </div>
));

// ─── Price header ─────────────────────────────────────────────────────────────

const PriceHeader = memo(() => {
  const price   = useNuclearStore((s) => s.price);
  const nuclear = useNuclearStore((s) => s.nuclear);
  const severity = nuclear?.severity ?? 0;
  const color = severityColor(severity);

  if (!price) return null;
  const changePct = price.change_pct ?? 0;
  const changeColor = changePct >= 0 ? '#00ff88' : '#ef4444';

  return (
    <div style={s.priceHeader}>
      <span style={s.symbolLabel}>XAU/USD</span>
      <span style={s.midPrice}>{price.mid.toFixed(2)}</span>
      <span style={{ ...s.changePct, color: changeColor }}>
        {changePct >= 0 ? '+' : ''}{(changePct * 100).toFixed(3)}%
      </span>
      <span style={s.spread}>Spread: {price.spread.toFixed(2)}</span>
      {severity > 0 && (
        <span style={{ ...s.severityTag, background: color, color: '#000' }}>
          SEV {severity}
        </span>
      )}
    </div>
  );
});

// ─── Main chart ───────────────────────────────────────────────────────────────

const NuclearCandleChart = memo(() => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const candleRef    = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const predHighRef  = useRef<ISeriesApi<'Area'> | null>(null);
  const predLowRef   = useRef<ISeriesApi<'Area'> | null>(null);
  const predMidRef   = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef   = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const rafRef       = useRef<number>(0);

  const bars          = useNuclearStore(selectActiveBars);
  const predPath      = useNuclearStore((s) => s.predictionPath);
  const nuclear       = useNuclearStore((s) => s.nuclear);
  const nuclearEvents = useNuclearStore((s) => s.nuclearEvents);
  const activeTimeframe = useNuclearStore((s) => s.activeTimeframe);
  const setActiveTimeframe = useNuclearStore((s) => s.setActiveTimeframe);

  const severity = nuclear?.severity ?? 0;
  const isAlert  = severity >= 7;

  // ── Chart init ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#020408' },
        textColor: '#64748b',
        fontFamily: 'monospace, system-ui',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#0a1628' },
        horzLines: { color: '#0a1628' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#334155', labelBackgroundColor: '#0f1f35' },
        horzLine: { color: '#334155', labelBackgroundColor: '#0f1f35' },
      },
      rightPriceScale: {
        borderColor: '#1a2e4a',
        textColor: '#64748b',
      },
      timeScale: {
        borderColor: '#1a2e4a',
        timeVisible: true,
        secondsVisible: activeTimeframe === '1m',
      },
      handleScroll: true,
      handleScale: true,
    });

    chartRef.current = chart;

    // Candlestick series
    const candle = chart.addSeries(CandlestickSeries, {
      upColor:          '#00ff88',
      downColor:        '#ef4444',
      borderUpColor:    '#00ff88',
      borderDownColor:  '#ef4444',
      wickUpColor:      '#00ff88',
      wickDownColor:    '#ef4444',
    });
    candleRef.current = candle;

    // Prediction cone — upper bound
    const predHigh = chart.addSeries(AreaSeries, {
      lineColor:    'rgba(59,130,246,0.4)',
      topColor:     'rgba(59,130,246,0.08)',
      bottomColor:  'rgba(59,130,246,0.0)',
      lineWidth:    1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    predHighRef.current = predHigh;

    // Prediction cone — lower bound
    const predLow = chart.addSeries(AreaSeries, {
      lineColor:    'rgba(59,130,246,0.4)',
      topColor:     'rgba(59,130,246,0.0)',
      bottomColor:  'rgba(59,130,246,0.08)',
      lineWidth:    1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    predLowRef.current = predLow;

    // Prediction midline
    const predMid = chart.addSeries(LineSeries, {
      color:     '#3b82f6',
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    predMidRef.current = predMid;

    // Signal markers
    markersRef.current = createSeriesMarkers(candle, []);

    // rAF-throttled ResizeObserver prevents layout thrashing
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width:  containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || undefined,
          });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      candleRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Update candles ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!candleRef.current || !bars.length) return;
    const sorted = [...bars].sort((a, b) => a.time - b.time);
    candleRef.current.setData(sorted.map(barToCandle));
    // Always scroll to the most recent candle after loading historical data
    chartRef.current?.timeScale().fitContent();
    chartRef.current?.timeScale().scrollToRealTime();
  }, [bars]);

  // ── Update prediction path ──────────────────────────────────────────────────

  useEffect(() => {
    if (!predPath.length) return;
    const highData: AreaData[] = predPath.map((p) => ({
      time: toUTC(p.time), value: p.high,
    }));
    const lowData: AreaData[] = predPath.map((p) => ({
      time: toUTC(p.time), value: p.low,
    }));
    const midData: LineData[] = predPath.map((p) => ({
      time: toUTC(p.time), value: p.price,
    }));

    // Widen cone color under nuclear conditions
    const coneColor = isAlert ? 'rgba(255,0,51,0.3)' : 'rgba(59,130,246,0.08)';
    const lineColor = isAlert ? 'rgba(255,0,51,0.6)' : 'rgba(59,130,246,0.4)';
    const midColor  = isAlert ? '#ff0033' : '#3b82f6';

    predHighRef.current?.applyOptions({ lineColor, topColor: coneColor, bottomColor: 'rgba(0,0,0,0)' });
    predLowRef.current?.applyOptions({ lineColor, topColor: 'rgba(0,0,0,0)', bottomColor: coneColor });
    predMidRef.current?.applyOptions({ color: midColor });

    predHighRef.current?.setData(highData);
    predLowRef.current?.setData(lowData);
    predMidRef.current?.setData(midData);
  }, [predPath, isAlert]);

  // ── Update event markers ────────────────────────────────────────────────────

  useEffect(() => {
    if (!markersRef.current || !nuclearEvents.length) return;
    const markers: SeriesMarker<Time>[] = nuclearEvents
      .filter((ev) => ev.severity >= 5)
      .map((ev) => ({
        time: toUTC(Math.floor(ev.ts / 1000)) as Time,
        position: 'aboveBar' as const,
        color: severityColor(ev.severity),
        shape: ev.severity >= 9 ? 'arrowDown' as const : 'circle' as const,
        text: `SEV${ev.severity}: ${ev.action.replace(/_/g, ' ').toUpperCase()}`,
        size: ev.severity >= 7 ? 2 : 1,
      }));
    markersRef.current.setMarkers(markers);
  }, [nuclearEvents]);

  // ── Nuclear overlay color ───────────────────────────────────────────────────

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.applyOptions({
      layout: {
        background: {
          color: isAlert ? '#0a0205' : '#020408',
        },
      },
    });
  }, [isAlert]);

  return (
    <div style={s.wrapper}>
      {/* Header row */}
      <div style={s.headerRow}>
        <PriceHeader />
        <TimeframeSelector
          active={activeTimeframe}
          onChange={setActiveTimeframe}
        />
      </div>

      {/* Chart canvas */}
      <div ref={containerRef} style={s.canvas} />

      {/* Nuclear zone overlay (red tint on alert) */}
      {isAlert && (
        <div style={{
          ...s.nuclearZone,
          background: `rgba(255,0,51,${Math.min(0.12, severity * 0.012)})`,
          borderColor: severityColor(severity),
        }} />
      )}

      {/* Prediction cone legend */}
      <div style={s.legend}>
        <span style={s.legendItem}>
          <span style={{ ...s.legendDot, background: isAlert ? '#ff0033' : '#3b82f6' }} />
          AI Prediction Path
        </span>
        {isAlert && (
          <span style={{ ...s.legendItem, color: '#ff0033' }}>
            ⚠ Nuclear Cone Active
          </span>
        )}
      </div>
    </div>
  );
});

export default NuclearCandleChart;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  wrapper: {
    flex: 1, display: 'flex', flexDirection: 'column',
    background: '#020408', position: 'relative', minWidth: 0,
  },
  headerRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '8px 12px',
    borderBottom: '1px solid #1a2e4a',
    flexShrink: 0,
  },
  priceHeader: {
    display: 'flex', alignItems: 'center', gap: 12,
  },
  symbolLabel: {
    fontSize: 13, fontWeight: 800, color: '#f59e0b', letterSpacing: 1,
  },
  midPrice: {
    fontSize: 20, fontWeight: 900, color: '#f1f5f9', fontFamily: 'monospace',
  },
  changePct: {
    fontSize: 12, fontWeight: 700, fontFamily: 'monospace',
  },
  spread: {
    fontSize: 10, color: '#475569', fontFamily: 'monospace',
  },
  severityTag: {
    fontSize: 10, fontWeight: 800, padding: '2px 8px',
    borderRadius: 4, fontFamily: 'monospace',
  },
  tfRow: {
    display: 'flex', gap: 4,
  },
  tfBtn: {
    padding: '4px 10px', border: '1px solid',
    borderRadius: 4, fontSize: 11, fontWeight: 700,
    cursor: 'pointer', fontFamily: 'monospace',
    transition: 'all 0.15s ease',
  },
  canvas: {
    flex: 1, minHeight: 0,
  },
  nuclearZone: {
    position: 'absolute', inset: 0,
    border: '1px solid',
    pointerEvents: 'none',
    transition: 'background 0.4s ease, border-color 0.4s ease',
  },
  legend: {
    position: 'absolute', bottom: 8, left: 12,
    display: 'flex', gap: 12, alignItems: 'center',
    pointerEvents: 'none',
  },
  legendItem: {
    display: 'flex', alignItems: 'center', gap: 4,
    fontSize: 10, color: '#475569',
  },
  legendDot: {
    width: 8, height: 8, borderRadius: '50%',
  },
};
