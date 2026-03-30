// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/RiskGauge.tsx
 * ========================
 * Circular arc gauge for risk utilization, CVaR, drawdown.
 * SVG arc with animated fill and color transitions.
 */

import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Path, Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import Animated, {
  useSharedValue, useAnimatedProps, withTiming, Easing,
} from 'react-native-reanimated';
import { COLORS, SPACING, RADIUS, TEXT, riskColor } from '../utils/theme';

const AnimatedPath = Animated.createAnimatedComponent(Path);

const SIZE    = 120;
const STROKE  = 10;
const RADIUS_ARC = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = Math.PI * RADIUS_ARC; // half circle

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end   = polarToCartesian(cx, cy, r, startAngle);
  const large = endAngle - startAngle <= 180 ? '0' : '1';
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 0 ${end.x} ${end.y}`;
}

interface Props {
  value: number;       // 0–1
  label: string;
  sublabel?: string;
  size?: number;
  showKillSwitch?: boolean;
}

export function RiskGauge({ value, label, sublabel, size = SIZE, showKillSwitch = false }: Props) {
  const progress = useSharedValue(0);
  const cx = size / 2;
  const cy = size / 2;
  const r  = (size - STROKE) / 2;

  useEffect(() => {
    progress.value = withTiming(Math.min(Math.max(value, 0), 1), {
      duration: 800,
      easing: Easing.out(Easing.cubic),
    });
  }, [value]);

  const color = riskColor(value);
  const pct   = Math.round(value * 100);

  // Track arc: 180° sweep from 180° to 360° (bottom half)
  const trackPath = arcPath(cx, cy, r, 180, 360);

  const animatedProps = useAnimatedProps(() => {
    const endAngle = 180 + progress.value * 180;
    return { d: arcPath(cx, cy, r, 180, endAngle) };
  });

  return (
    <View style={[styles.container, { width: size }]}>
      <Svg width={size} height={size / 2 + STROKE}>
        {/* Track */}
        <Path
          d={trackPath}
          stroke={COLORS.border}
          strokeWidth={STROKE}
          fill="none"
          strokeLinecap="round"
        />
        {/* Fill */}
        <AnimatedPath
          animatedProps={animatedProps}
          stroke={color}
          strokeWidth={STROKE}
          fill="none"
          strokeLinecap="round"
        />
        {/* Kill switch indicator */}
        {showKillSwitch && value >= 1 && (
          <Circle cx={cx} cy={cy / 2 + STROKE} r={6} fill={COLORS.killSwitch} />
        )}
      </Svg>

      {/* Center value */}
      <View style={styles.center}>
        <Text style={[styles.pct, { color }]}>{pct}%</Text>
        <Text style={styles.label}>{label}</Text>
        {sublabel ? <Text style={styles.sublabel}>{sublabel}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignItems: 'center' },
  center:    { alignItems: 'center', marginTop: -SPACING.sm },
  pct:       { ...TEXT.numericMD, fontWeight: '800' },
  label:     { ...TEXT.label, color: COLORS.textMuted, marginTop: 2 },
  sublabel:  { ...TEXT.captionSM, color: COLORS.textDim, marginTop: 1 },
});
