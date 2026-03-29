// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import {
  TouchableOpacity,
  Text,
  StyleSheet,
  ActivityIndicator,
  ViewStyle,
  TextStyle,
} from 'react-native';
import { COLORS, RADIUS, SPACING } from '../utils/theme';

type Variant = 'primary' | 'buy' | 'sell' | 'ghost' | 'danger';

interface Props {
  title: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  textStyle?: TextStyle;
  fullWidth?: boolean;
}

const BG: Record<Variant, string> = {
  primary: COLORS.accent,
  buy:     COLORS.buy,
  sell:    COLORS.sell,
  ghost:   'transparent',
  danger:  COLORS.sell,
};

export function Button({
  title,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  style,
  textStyle,
  fullWidth = false,
}: Props) {
  const isDisabled = disabled || loading;
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.8}
      style={[
        styles.base,
        { backgroundColor: BG[variant] },
        variant === 'ghost' && styles.ghost,
        fullWidth && styles.fullWidth,
        isDisabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={COLORS.white} size="small" />
      ) : (
        <Text style={[styles.text, textStyle]}>{title}</Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    paddingVertical: SPACING.sm + 4,
    paddingHorizontal: SPACING.lg,
    borderRadius: RADIUS.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  ghost: {
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  fullWidth: { width: '100%' },
  disabled: { opacity: 0.5 },
  text: {
    color: COLORS.white,
    fontWeight: '700',
    fontSize: 15,
    letterSpacing: 0.3,
  },
});
