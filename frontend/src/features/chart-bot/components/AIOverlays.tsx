/**
 * AIOverlays.tsx
 * AI-powered trendlines, support/resistance levels, and pattern detection
 * rendered as SVG overlays on top of the TradingView chart canvas.
 * Uses the chart's coordinate conversion API for pixel-perfect placement.
 */

import React, { useEffect, useRef, useState, memo, useCallback } from 'react';
import { IChartApi, ISeriesApi, SeriesType, UTCTimestamp } from 'lightweight-charts';
import { COLORS } from '../utils/design-tokens';
import { formatPrice } from '../utils/formatters';
import type { SupportResistanceLevel, TrendLine, ChartPattern } from '../types';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Coords { x: number; y: number }

interface RenderedLevel {
  level: SupportResistanceLevel;
  y: number;
}

interface RenderedTrendline {
  line: TrendLine;
  start: Coords;
  end: Coords;
}

interface RenderedPattern {
  pattern: ChartPattern;
  x: number;
  y: number;
  width: number;
}

// ─── Level Label ──────────────────────────────────────────────────────────────

const LevelLabel = memo(({ level, y, width }: { level: SupportResistanceLevel; y: number; width: number }) => {
  const color = level.type === 'support'    ? COLORS.chart.support
              : level.type === 'resistance' ? COLORS.chart.resistance
              : COLORS.chart.pivot;
  const opacity = 0.4 + level.strength * 0.6;

  return (
    <g>
      {/* Dashed horizontal line */}
      <line
        x1={0} y1={y} x2={width} y2={y}
        stroke={color}
        strokeWidth={level.aiGenerated ? 1.5 : 1}
        strokeDasharray={level.aiGenerated ? '0' : '4 3'}
        opacity={opacity}
      />
      {/* Label pill */}
      <rect
        x={width - 110} y={y - 9}
        width={108} height={18}
        rx={3}
        fill={COLORS.bg.elevated}
        stroke={color}
        strokeWidth={0.5}
        opacity={0.9}
      />
      <text
        x={width - 56} y={y + 4}
        textAnchor="middle"
        fill={color}
        fontSize={9}
        fontFamily='"JetBrains Mono", monospace'
        fontWeight={600}
        letterSpacing="0.06em"
      >
        {level.type.toUpperCase()} {formatPrice(level.price)} ({(level.strength * 100).toFixed(0)}%)
      </text>
      {/* AI badge */}
      {level.aiGenerated && (
        <text x={width - 112} y={y + 4} textAnchor="end" fill={COLORS.neon.purple} fontSize={8} fontFamily='"JetBrains Mono", monospace'>
          AI
        </text>
      )}
    </g>
  );
});
LevelLabel.displayName = 'LevelLabel';

// ─── Trendline ────────────────────────────────────────────────────────────────

const TrendlineEl = memo(({ line, start, end }: { line: TrendLine; start: Coords; end: Coords }) => {
  const color = line.type === 'uptrend'   ? COLORS.chart.trendlineUp
              : line.type === 'downtrend' ? COLORS.chart.trendlineDown
              : COLORS.text.muted;
  const opacity = 0.5 + line.strength * 0.5;

  return (
    <g>
      <line
        x1={start.x} y1={start.y}
        x2={end.x}   y2={end.y}
        stroke={color}
        strokeWidth={line.aiGenerated ? 2 : 1}
        strokeDasharray={line.aiGenerated ? '0' : '6 3'}
        opacity={opacity}
      />
      {/* Direction arrow at end */}
      <circle cx={end.x} cy={end.y} r={3} fill={color} opacity={opacity} />
      {line.aiGenerated && (
        <text
          x={end.x + 6} y={end.y - 4}
          fill={color}
          fontSize={8}
          fontFamily='"JetBrains Mono", monospace'
          opacity={0.8}
        >
          AI {line.type.replace('_', ' ').toUpperCase()}
        </text>
      )}
    </g>
  );
});
TrendlineEl.displayName = 'TrendlineEl';

// ─── Pattern Box ──────────────────────────────────────────────────────────────

const PatternBox = memo(({ pattern, x, y, width }: { pattern: ChartPattern; x: number; y: number; width: number }) => {
  const color = pattern.direction === 'bullish' ? COLORS.profit.base
              : pattern.direction === 'bearish' ? COLORS.loss.base
              : COLORS.neon.gold;
  const bgColor = pattern.direction === 'bullish' ? 'rgba(0,255,136,0.04)'
                : pattern.direction === 'bearish' ? 'rgba(255,51,102,0.04)'
                : 'rgba(245,158,11,0.04)';

  return (
    <g>
      <rect
        x={x} y={y - 40}
        width={width} height={80}
        fill={bgColor}
        stroke={color}
        strokeWidth={0.5}
        strokeDasharray="4 2"
        rx={2}
        opacity={0.7}
      />
      <rect
        x={x} y={y - 40}
        width={Math.min(160, width)} height={20}
        fill={COLORS.bg.elevated}
        rx={2}
        opacity={0.9}
      />
      <text
        x={x + 6} y={y - 26}
        fill={color}
        fontSize={9}
        fontFamily='"JetBrains Mono", monospace'
        fontWeight={700}
        letterSpacing="0.06em"
      >
        {pattern.type.replace(/_/g, ' ').toUpperCase()} {(pattern.confidence * 100).toFixed(0)}%
      </text>
    </g>
  );
});
PatternBox.displayName = 'PatternBox';

// ─── Main Component ───────────────────────────────────────────────────────────

interface AIOverlaysProps {
  chart: IChartApi | null;
  // A reference series is needed for priceToCoordinate (v5 API)
  series?: ISeriesApi<SeriesType> | null;
  levels: SupportResistanceLevel[];
  trendlines: TrendLine[];
  patterns: ChartPattern[];
  containerWidth: number;
  containerHeight: number;
}

const AIOverlays: React.FC<AIOverlaysProps> = ({
  chart,
  series,
  levels,
  trendlines,
  patterns,
  containerWidth,
  containerHeight,
}) => {
  const [renderedLevels,    setRenderedLevels]    = useState<RenderedLevel[]>([]);
  const [renderedTrendlines,setRenderedTrendlines]= useState<RenderedTrendline[]>([]);
  const [renderedPatterns,  setRenderedPatterns]  = useState<RenderedPattern[]>([]);
  const rafRef = useRef<number>(0);

  const recompute = useCallback(() => {
    if (!chart) return;
    // priceToCoordinate lives on ISeriesApi in v5; fall back gracefully if no series
    const priceToY = (price: number): number | null => {
      if (series) return series.priceToCoordinate(price);
      return null;
    };

    // Levels → y coordinates
    const newLevels: RenderedLevel[] = [];
    for (const lvl of levels) {
      try {
        const y = priceToY(lvl.price);
        if (y !== null && y > 0 && y < containerHeight) {
          newLevels.push({ level: lvl, y });
        }
      } catch { /* price out of range */ }
    }
    setRenderedLevels(newLevels);

    // Trendlines → pixel coords
    const newTrendlines: RenderedTrendline[] = [];
    for (const line of trendlines) {
      try {
        const ts = chart.timeScale();
        const x1 = ts.timeToCoordinate(line.startTime as UTCTimestamp);
        const x2 = ts.timeToCoordinate(line.endTime   as UTCTimestamp);
        const y1 = priceToY(line.startPrice);
        const y2 = priceToY(line.endPrice);
        if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) {
          newTrendlines.push({ line, start: { x: x1, y: y1 }, end: { x: x2, y: y2 } });
        }
      } catch { /* out of range */ }
    }
    setRenderedTrendlines(newTrendlines);

    // Patterns → bounding box
    const newPatterns: RenderedPattern[] = [];
    for (const pat of patterns) {
      try {
        const ts = chart.timeScale();
        const x1 = ts.timeToCoordinate(pat.startTime as UTCTimestamp);
        const x2 = ts.timeToCoordinate(pat.endTime   as UTCTimestamp);
        const y  = priceToY((pat.targetPrice + pat.stopPrice) / 2);
        if (x1 !== null && x2 !== null && y !== null) {
          const px = Math.min(x1, x2);
          const pw = Math.abs(x2 - x1);
          if (pw > 10) newPatterns.push({ pattern: pat, x: px, y, width: pw });
        }
      } catch { /* out of range */ }
    }
    setRenderedPatterns(newPatterns);
  }, [chart, series, levels, trendlines, patterns, containerHeight]);

  // Recompute on data change or chart scroll/zoom
  useEffect(() => {
    if (!chart) return;
    recompute();
    const handler = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(recompute);
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(handler);
    return () => {
      cancelAnimationFrame(rafRef.current);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(handler);
    };
  }, [chart, recompute]);

  if (!containerWidth || !containerHeight) return null;

  return (
    <svg
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: containerWidth,
        height: containerHeight,
        pointerEvents: 'none',
        zIndex: 5,
        overflow: 'visible',
      }}
      width={containerWidth}
      height={containerHeight}
    >
      {/* Trendlines */}
      {renderedTrendlines.map((rt) => (
        <TrendlineEl key={rt.line.id} line={rt.line} start={rt.start} end={rt.end} />
      ))}

      {/* Pattern boxes */}
      {renderedPatterns.map((rp) => (
        <PatternBox
          key={rp.pattern.id}
          pattern={rp.pattern}
          x={rp.x} y={rp.y}
          width={rp.width}
        />
      ))}

      {/* S/R levels */}
      {renderedLevels.map((rl) => (
        <LevelLabel
          key={rl.level.id}
          level={rl.level}
          y={rl.y}
          width={containerWidth}
        />
      ))}
    </svg>
  );
};

export default memo(AIOverlays);
