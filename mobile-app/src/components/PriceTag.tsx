// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { Text, StyleSheet, TextStyle } from 'react-native';
import { COLORS } from '../utils/theme';
import { formatPrice } from '../utils/formatters';

interface Props {
  value: number;
  decimals?: number;
  style?: TextStyle;
  showSign?: boolean;
}

export function PriceTag({ value, decimals = 2, style, showSign = false }: Props) {
  const color = value >= 0 ? COLORS.profit : COLORS.loss;
  const sign = showSign && value > 0 ? '+' : '';
  return (
    <Text style={[styles.text, { color }, style]}>
      {sign}{formatPrice(value, decimals)}
    </Text>
  );
}

const styles = StyleSheet.create({
  text: { fontWeight: '700', fontFamily: 'Courier' },
});
