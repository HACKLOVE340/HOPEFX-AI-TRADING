// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/LiveTicker.tsx
 * =========================
 * Real-time price ticker with animated flash on update, spread bar,
 * and directional change indicator. 60fps via Reanimated.
 */

import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Animated, {
  useSharedValue, useAnimatedStyle, withTiming, withSequence,
  interpolateColor, Easing,
} from 'react-native-reanimated';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../utils/theme';
import { Quote } from '../types';

interface Props {
  quote: Quote | null;
  symbol: string;
  onBuy?: () => void;
  onSell?: () => void;
  compact?: boolean;
}

export function LiveTicker({ quote, symbol, onBuy, onSell, compact = false }: Props) {
  const prevMid = useRef<number | null>(null);
  const flashProgress = useSharedValue(0);
  const priceDirection = useRef<'up' | 'down' | 'flat'>('flat');

  useEffect(() => {
    if (!quote) return;
    if (prevMid.current !== null) {
      priceDirection.current = quote.mid > prevMid.current ? 'up' :
                               quote.mid < prevMid.current ? 'down' : 'flat';
      // Flash animation on price change
      flashProgress.value = withSequence(
        withTiming(1, { duration: 80, easing: Easing.out(Easing.quad) }),
        withTiming(0, { duration: 400, easing: Easing.in(Easing.quad) })
      );
    }
    prevMid.current = quote.mid;
  }, [quote?.mid]);

  const flashStyle = useAnimatedStyle(() => {
    const dir = priceDirection.current;
    const flashColor = dir === 'up' ? COLORS.buy : dir === 'down' ? COLORS.sell : COLORS.accent;
    return {
      backgroundColor: interpolateColor(
        flashProgress.value,
        [0, 1],
        ['transparent', flashColor + '22']
      ),
    };
  });

  const priceColor = priceDirection.current === 'up' ? COLORS.profit :
                     priceDirection.current === 'down' ? COLORS.loss : COLORS.text;

  const spreadPct = quote ? (quote.spread / quote.mid) * 100 : 0;

  if (compact) {
    return (
      <Animated.View style={[styles.compact, flashStyle]}>
        <Text style={styles.compactSymbol}>{symbol}</Text>
        <Text style={[styles.compactPrice, { color: priceColor }]}>
          {quote ? quote.mid.toFixed(2) : '—'}
        </Text>
        <Text style={[styles.compactChange, {
          color: (quote?.change_pct ?? 0) >= 0 ? COLORS.profit : COLORS.loss
        }]}>
          {quote ? `${quote.change_pct >= 0 ? '+' : ''}${quote.change_pct.toFixed(2)}%` : ''}
        </Text>
      </Animated.View>
    );
  }

  return (
    <Animated.View style={[styles.container, flashStyle]}>
      {/* Symbol + live indicator */}
      <View style={styles.header}>
        <View style={styles.symbolRow}>
          <Text style={styles.symbol}>{symbol}</Text>
          <View style={[styles.liveDot, { backgroundColor: quote ? COLORS.profit : COLORS.textDim }]} />
          <Text style={[styles.liveLabel, { color: quote ? COLORS.profit : COLORS.textDim }]}>
            {quote ? 'LIVE' : 'OFFLINE'}
          </Text>
        </View>
        {quote && (
          <Text style={[styles.changePct, {
            color: quote.change_pct >= 0 ? COLORS.profit : COLORS.loss
          }]}>
            {quote.change_pct >= 0 ? '▲' : '▼'} {Math.abs(quote.change_pct).toFixed(2)}%
          </Text>
        )}
      </View>

      {/* Mid price — large */}
      <Text style={[styles.midPrice, { color: priceColor }]}>
        {quote ? quote.mid.toFixed(2) : '—.——'}
      </Text>

      {/* Bid / Spread / Ask row */}
      <View style={styles.bidAskRow}>
        <View style={styles.bidBox}>
          <Text style={styles.baLabel}>BID</Text>
          <Text style={[styles.baPrice, { color: COLORS.sell }]}>
            {quote ? quote.bid.toFixed(2) : '—'}
          </Text>
        </View>

        <View style={styles.spreadBox}>
          <Text style={styles.spreadLabel}>SPREAD</Text>
          <Text style={styles.spreadValue}>
            {quote ? quote.spread.toFixed(1) : '—'}
          </Text>
          {/* Spread width bar */}
          <View style={styles.spreadBarTrack}>
            <View style={[styles.spreadBarFill, {
              width: `${Math.min(spreadPct * 200, 100)}%` as any,
              backgroundColor: spreadPct > 0.05 ? COLORS.warning : COLORS.accent,
            }]} />
          </View>
        </View>

        <View style={styles.askBox}>
          <Text style={styles.baLabel}>ASK</Text>
          <Text style={[styles.baPrice, { color: COLORS.buy }]}>
            {quote ? quote.ask.toFixed(2) : '—'}
          </Text>
        </View>
      </View>

      {/* Session range */}
      {quote?.session_high && quote?.session_low && (
        <View style={styles.sessionRow}>
          <Text style={styles.sessionLabel}>
            Session: {quote.session_low.toFixed(2)} — {quote.session_high.toFixed(2)}
          </Text>
        </View>
      )}

      {/* Trade buttons */}
      {(onBuy || onSell) && (
        <View style={styles.tradeRow}>
          <TouchableOpacity
            style={[styles.tradeBtn, styles.sellBtn]}
            onPress={onSell}
            activeOpacity={0.8}
          >
            <Text style={styles.tradeBtnLabel}>SELL</Text>
            <Text style={styles.tradeBtnPrice}>{quote?.bid.toFixed(2) ?? '—'}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tradeBtn, styles.buyBtn]}
            onPress={onBuy}
            activeOpacity={0.8}
          >
            <Text style={styles.tradeBtnLabel}>BUY</Text>
            <Text style={styles.tradeBtnPrice}>{quote?.ask.toFixed(2) ?? '—'}</Text>
          </TouchableOpacity>
        </View>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container:     {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.xl,
    padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border,
    gap: SPACING.sm, ...SHADOW.md,
  },
  header:        { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  symbolRow:     { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  symbol:        { ...TEXT.h3, color: COLORS.text },
  liveDot:       { width: 7, height: 7, borderRadius: 4 },
  liveLabel:     { ...TEXT.labelSM, letterSpacing: 1.5 },
  changePct:     { ...TEXT.numericSM, fontWeight: '700' },
  midPrice:      { ...TEXT.numericXL, letterSpacing: -1 },
  bidAskRow:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  bidBox:        { alignItems: 'flex-start', flex: 1 },
  askBox:        { alignItems: 'flex-end', flex: 1 },
  spreadBox:     { alignItems: 'center', flex: 1 },
  baLabel:       { ...TEXT.label, color: COLORS.textMuted },
  baPrice:       { ...TEXT.numericMD, marginTop: 2 },
  spreadLabel:   { ...TEXT.labelSM, color: COLORS.textMuted },
  spreadValue:   { ...TEXT.numericXS, color: COLORS.textSecondary, marginTop: 2 },
  spreadBarTrack:{ height: 3, width: 60, backgroundColor: COLORS.border, borderRadius: RADIUS.full, marginTop: 4, overflow: 'hidden' },
  spreadBarFill: { height: '100%', borderRadius: RADIUS.full },
  sessionRow:    { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.xs },
  sessionLabel:  { ...TEXT.caption, color: COLORS.textMuted, textAlign: 'center' },
  tradeRow:      { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.xs },
  tradeBtn:      { flex: 1, height: 52, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center' },
  sellBtn:       { backgroundColor: COLORS.sell, ...SHADOW.sellGlow },
  buyBtn:        { backgroundColor: COLORS.buy,  ...SHADOW.buyGlow },
  tradeBtnLabel: { color: COLORS.white, fontWeight: '800', fontSize: 13, letterSpacing: 1.5 },
  tradeBtnPrice: { color: 'rgba(255,255,255,0.85)', fontWeight: '700', fontSize: 15, fontFamily: 'Courier New', marginTop: 1 },
  // Compact
  compact:       { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.xs, paddingHorizontal: SPACING.sm },
  compactSymbol: { ...TEXT.bodySM, color: COLORS.textMuted, width: 60 },
  compactPrice:  { ...TEXT.numericSM, flex: 1 },
  compactChange: { ...TEXT.numericXS },
});
