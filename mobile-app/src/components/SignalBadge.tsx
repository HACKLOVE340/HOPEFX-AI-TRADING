// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS, RADIUS, SPACING } from '../utils/theme';

interface Props {
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  size?: 'sm' | 'md';
}

export function SignalBadge({ direction, confidence, size = 'md' }: Props) {
  const color =
    direction === 'long' ? COLORS.buy :
    direction === 'short' ? COLORS.sell :
    COLORS.neutral;

  const label =
    direction === 'long' ? '▲ LONG' :
    direction === 'short' ? '▼ SHORT' :
    '— NEUTRAL';

  const isSmall = size === 'sm';

  return (
    <View style={[styles.container, { borderColor: color }, isSmall && styles.small]}>
      <Text style={[styles.label, { color }, isSmall && styles.labelSmall]}>{label}</Text>
      <Text style={[styles.conf, isSmall && styles.confSmall]}>
        {(confidence * 100).toFixed(0)}%
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: RADIUS.sm,
    paddingHorizontal: SPACING.sm,
    paddingVertical: 4,
    gap: SPACING.xs,
    alignSelf: 'flex-start',
  },
  small: { paddingHorizontal: 6, paddingVertical: 2 },
  label: { fontWeight: '700', fontSize: 13 },
  labelSmall: { fontSize: 11 },
  conf: { color: COLORS.textMuted, fontSize: 12 },
  confSmall: { fontSize: 10 },
});
