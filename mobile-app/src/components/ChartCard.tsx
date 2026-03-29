// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/ChartCard.tsx
 * ========================
 * Lightweight SVG equity-curve sparkline rendered without a heavy charting
 * library dependency.  Uses React Native's built-in View/Text primitives
 * and a simple polyline drawn via absolute-positioned Views.
 *
 * For production, swap the inner <Sparkline> with a react-native-svg
 * <Polyline> once the dependency is available in the build.
 */

import React, { useMemo } from 'react';
import { View, Text, StyleSheet, Dimensions } from 'react-native';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { formatCurrency, formatPct } from '../utils/formatters';

const SCREEN_W = Dimensions.get('window').width;
const CHART_H = 80;
const CHART_W = SCREEN_W - SPACING.md * 2 - SPACING.md * 2; // card padding × 2

interface ChartCardProps {
  title: string;
  value: number;
  changePct: number;
  dataPoints: number[];   // equity curve values
  currency?: string;
  style?: object;
}

export function ChartCard({
  title,
  value,
  changePct,
  dataPoints,
  currency = 'USD',
  style,
}: ChartCardProps) {
  const isPositive = changePct >= 0;
  const lineColor = isPositive ? COLORS.profit : COLORS.loss;

  // Normalise data points to [0, CHART_H]
  const segments = useMemo(() => {
    if (dataPoints.length < 2) return [];
    const min = Math.min(...dataPoints);
    const max = Math.max(...dataPoints);
    const range = max - min || 1;
    const step = CHART_W / (dataPoints.length - 1);

    return dataPoints.map((v, i) => ({
      x: i * step,
      y: CHART_H - ((v - min) / range) * CHART_H,
    }));
  }, [dataPoints]);

  return (
    <View style={[styles.card, style]}>
      <View style={styles.header}>
        <Text style={styles.title}>{title}</Text>
        <Text style={[styles.change, { color: lineColor }]}>
          {formatPct(changePct)}
        </Text>
      </View>
      <Text style={styles.value}>{formatCurrency(value, currency)}</Text>

      {/* Sparkline — rendered as connected line segments */}
      {segments.length >= 2 && (
        <View style={styles.chartArea}>
          {segments.slice(0, -1).map((pt, i) => {
            const next = segments[i + 1];
            const dx = next.x - pt.x;
            const dy = next.y - pt.y;
            const length = Math.sqrt(dx * dx + dy * dy);
            const angle = Math.atan2(dy, dx) * (180 / Math.PI);
            return (
              <View
                key={i}
                style={[
                  styles.segment,
                  {
                    left: pt.x,
                    top: pt.y,
                    width: length,
                    backgroundColor: lineColor,
                    transform: [{ rotate: `${angle}deg` }],
                  },
                ]}
              />
            );
          })}
          {/* Last data point dot */}
          {segments.length > 0 && (
            <View
              style={[
                styles.dot,
                {
                  left: segments[segments.length - 1].x - 4,
                  top: segments[segments.length - 1].y - 4,
                  backgroundColor: lineColor,
                },
              ]}
            />
          )}
        </View>
      )}

      {dataPoints.length < 2 && (
        <Text style={styles.noData}>No chart data yet</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: SPACING.xs,
  },
  title: {
    color: COLORS.textMuted,
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  change: {
    fontSize: 13,
    fontWeight: '700',
  },
  value: {
    color: COLORS.text,
    fontSize: 24,
    fontWeight: '800',
    fontFamily: 'Courier',
    marginBottom: SPACING.sm,
  },
  chartArea: {
    height: CHART_H,
    position: 'relative',
    overflow: 'hidden',
  },
  segment: {
    position: 'absolute',
    height: 2,
    borderRadius: 1,
    transformOrigin: 'left center',
  },
  dot: {
    position: 'absolute',
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  noData: {
    color: COLORS.textMuted,
    fontSize: 12,
    textAlign: 'center',
    paddingVertical: SPACING.md,
  },
});
