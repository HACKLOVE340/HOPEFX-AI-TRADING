// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/MicrostructureBar.tsx
 * =================================
 * Real-time microstructure indicators: volume delta, order flow imbalance,
 * depth imbalance, buy/sell pressure, spread z-score.
 * All bars animate smoothly via Reanimated.
 */

import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue, useAnimatedStyle, withTiming, Easing,
} from 'react-native-reanimated';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';
import { Microstructure } from '../types';

interface BarProps {
  label: string;
  value: number;   // -1 to +1 (signed) or 0 to 1 (unsigned)
  signed?: boolean;
  color?: string;
  unit?: string;
}

function MicroBar({ label, value, signed = false, color, unit }: BarProps) {
  const progress = useSharedValue(signed ? 0.5 : 0);

  useEffect(() => {
    const target = signed ? (value + 1) / 2 : Math.min(Math.max(value, 0), 1);
    progress.value = withTiming(target, { duration: 400, easing: Easing.out(Easing.quad) });
  }, [value]);

  const fillStyle = useAnimatedStyle(() => {
    if (signed) {
      const half = 0.5;
      const isPositive = progress.value >= half;
      const width = Math.abs(progress.value - half) * 2 * 100;
      return {
        position: 'absolute',
        left: isPositive ? '50%' : `${progress.value * 100}%` as any,
        width: `${width}%` as any,
        height: '100%',
        backgroundColor: color ?? (isPositive ? COLORS.buy : COLORS.sell),
        borderRadius: RADIUS.full,
      };
    }
    return {
      width: `${progress.value * 100}%` as any,
      height: '100%',
      backgroundColor: color ?? COLORS.accent,
      borderRadius: RADIUS.full,
    };
  });

  const displayVal = signed
    ? (value >= 0 ? '+' : '') + value.toFixed(3)
    : (value * 100).toFixed(1) + (unit ?? '%');

  const valColor = signed
    ? (value > 0.05 ? COLORS.buy : value < -0.05 ? COLORS.sell : COLORS.textMuted)
    : (color ?? COLORS.accent);

  return (
    <View style={barStyles.row}>
      <Text style={barStyles.label}>{label}</Text>
      <View style={barStyles.track}>
        {signed && <View style={barStyles.centerLine} />}
        <Animated.View style={fillStyle} />
      </View>
      <Text style={[barStyles.value, { color: valColor }]}>{displayVal}</Text>
    </View>
  );
}

const barStyles = StyleSheet.create({
  row:        { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  label:      { ...TEXT.labelSM, color: COLORS.textMuted, width: 72 },
  track:      { flex: 1, height: 6, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden', position: 'relative' },
  centerLine: { position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, backgroundColor: COLORS.borderBright, zIndex: 1 },
  value:      { ...TEXT.numericXS, width: 52, textAlign: 'right' },
});

interface Props {
  micro: Microstructure | null;
  symbol: string;
}

export function MicrostructureBar({ micro, symbol }: Props) {
  const spreadZColor =
    !micro ? COLORS.textMuted :
    micro.spread_z > 2  ? COLORS.danger :
    micro.spread_z > 1  ? COLORS.warning : COLORS.accent;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>MICROSTRUCTURE</Text>
        <Text style={styles.symbol}>{symbol}</Text>
      </View>

      {micro ? (
        <View style={styles.bars}>
          <MicroBar
            label="VOL DELTA"
            value={micro.volume_delta}
            signed
          />
          <MicroBar
            label="OFI"
            value={micro.ofi}
            signed
          />
          <MicroBar
            label="BUY PRESS"
            value={micro.buy_pressure}
            color={COLORS.buy}
            unit="%"
          />
          <MicroBar
            label="SELL PRESS"
            value={micro.sell_pressure}
            color={COLORS.sell}
            unit="%"
          />
          <MicroBar
            label="DEPTH IMB"
            value={micro.depth_imbalance}
            signed
          />
          <MicroBar
            label="ABSORPTION"
            value={micro.absorption}
            color={COLORS.info}
            unit="%"
          />

          {/* Spread z-score chip */}
          <View style={styles.spreadRow}>
            <Text style={styles.spreadLabel}>SPREAD Z-SCORE</Text>
            <View style={[styles.spreadChip, { borderColor: spreadZColor + '55', backgroundColor: spreadZColor + '15' }]}>
              <Text style={[styles.spreadZ, { color: spreadZColor }]}>
                {micro.spread_z >= 0 ? '+' : ''}{micro.spread_z.toFixed(2)}σ
              </Text>
            </View>
            <Text style={styles.spreadRaw}>{micro.spread.toFixed(2)} pts</Text>
          </View>

          {/* VWAP deviation */}
          <View style={styles.vwapRow}>
            <Text style={styles.spreadLabel}>VWAP DEV</Text>
            <Text style={[styles.vwapVal, {
              color: micro.vwap_deviation > 0 ? COLORS.profit : COLORS.loss
            }]}>
              {micro.vwap_deviation >= 0 ? '+' : ''}{micro.vwap_deviation.toFixed(2)}
            </Text>
          </View>
        </View>
      ) : (
        <Text style={styles.noData}>Awaiting microstructure data…</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container:   {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.xl,
    padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border,
    gap: SPACING.sm,
  },
  header:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title:       { ...TEXT.label, color: COLORS.textMuted },
  symbol:      { ...TEXT.numericXS, color: COLORS.accent },
  bars:        { gap: SPACING.xs },
  spreadRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginTop: SPACING.xs },
  spreadLabel: { ...TEXT.labelSM, color: COLORS.textMuted, width: 72 },
  spreadChip:  { paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm, borderWidth: 1 },
  spreadZ:     { ...TEXT.numericXS, fontWeight: '700' },
  spreadRaw:   { ...TEXT.numericXS, color: COLORS.textMuted, marginLeft: 'auto' },
  vwapRow:     { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  vwapVal:     { ...TEXT.numericXS, fontWeight: '700', marginLeft: 'auto' },
  noData:      { ...TEXT.caption, color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.md },
});
