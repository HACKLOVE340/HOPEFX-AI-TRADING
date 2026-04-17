// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, StyleSheet, ViewStyle, StyleProp } from 'react-native';
import { COLORS, RADIUS, SPACING, SHADOW } from '../utils/theme';

interface Props {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  elevated?: boolean;
  accent?: boolean;
  danger?: boolean;
}

export function Card({ children, style, elevated = false, accent = false, danger = false }: Props) {
  return (
    <View style={[
      styles.card,
      elevated && SHADOW.md,
      accent && styles.accentBorder,
      danger && styles.dangerBorder,
      style,
    ]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.xl,
    padding: SPACING.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  accentBorder: { borderColor: COLORS.borderAccent },
  dangerBorder: { borderColor: COLORS.danger + '55', backgroundColor: COLORS.killSwitchDim },
});
