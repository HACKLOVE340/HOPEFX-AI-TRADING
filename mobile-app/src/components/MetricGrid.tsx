// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/MetricGrid.tsx
 * =========================
 * Reusable 2-column metric grid used across Portfolio, Performance,
 * and Dashboard screens.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS, SPACING } from '../utils/theme';

export interface Metric {
  label: string;
  value: string;
  color?: string;
  subValue?: string;
}

interface MetricGridProps {
  metrics: Metric[];
  columns?: 2 | 3 | 4;
}

export function MetricGrid({ metrics, columns = 2 }: MetricGridProps) {
  const colWidth = `${Math.floor(100 / columns)}%` as `${number}%`;

  return (
    <View style={styles.grid}>
      {metrics.map((m, i) => (
        <View key={i} style={[styles.cell, { width: colWidth }]}>
          <Text style={styles.label}>{m.label}</Text>
          <Text style={[styles.value, m.color ? { color: m.color } : {}]}>
            {m.value}
          </Text>
          {m.subValue ? (
            <Text style={styles.subValue}>{m.subValue}</Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: SPACING.sm,
  },
  cell: {
    alignItems: 'center',
    paddingVertical: SPACING.sm,
  },
  label: {
    color: COLORS.textMuted,
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
    marginBottom: 4,
    textAlign: 'center',
  },
  value: {
    color: COLORS.text,
    fontSize: 16,
    fontWeight: '700',
    fontFamily: 'Courier',
    textAlign: 'center',
  },
  subValue: {
    color: COLORS.textMuted,
    fontSize: 11,
    marginTop: 2,
    textAlign: 'center',
  },
});
