// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/SignalCard.tsx
 * =========================
 * Elite signal card with confidence bar, factor breakdown,
 * reasoning text, and one-tap trade approval with haptics.
 */

import React, { useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW, signalColor, confidenceColor } from '../utils/theme';
import { Signal } from '../types';
import { formatRelativeTime } from '../utils/formatters';

interface Props {
  signal: Signal;
  onTrade: () => void;
  onApprove?: () => void;
}

export function SignalCard({ signal, onTrade, onApprove }: Props) {
  const scaleAnim = useRef(new Animated.Value(1)).current;
  const isExpired = new Date(signal.expires_at) < new Date();
  const dirColor  = signalColor(signal.direction);
  const confColor = confidenceColor(signal.confidence);

  const handleApprove = () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    Animated.sequence([
      Animated.timing(scaleAnim, { toValue: 0.96, duration: 80, useNativeDriver: true }),
      Animated.timing(scaleAnim, { toValue: 1,    duration: 120, useNativeDriver: true }),
    ]).start();
    onApprove?.();
    onTrade();
  };

  const handlePress = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  };

  return (
    <Animated.View style={[styles.card, isExpired && styles.expired, { transform: [{ scale: scaleAnim }] }]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.symbol}>{signal.symbol}</Text>
          <Text style={styles.time}>{formatRelativeTime(signal.generated_at)}</Text>
        </View>
        <View style={[styles.directionBadge, { borderColor: dirColor + '55', backgroundColor: dirColor + '18' }]}>
          <Ionicons
            name={signal.direction === 'long' ? 'trending-up' : signal.direction === 'short' ? 'trending-down' : 'remove'}
            size={14}
            color={dirColor}
          />
          <Text style={[styles.directionText, { color: dirColor }]}>
            {signal.direction.toUpperCase()}
          </Text>
        </View>
      </View>

      {/* Confidence bar */}
      <View style={styles.confRow}>
        <Text style={styles.confLabel}>CONFIDENCE</Text>
        <View style={styles.confTrack}>
          <View style={[styles.confFill, {
            width: `${signal.confidence * 100}%` as any,
            backgroundColor: confColor,
          }]} />
        </View>
        <Text style={[styles.confValue, { color: confColor }]}>
          {(signal.confidence * 100).toFixed(0)}%
        </Text>
      </View>

      {/* ML probability */}
      <View style={styles.confRow}>
        <Text style={styles.confLabel}>ML PROB</Text>
        <View style={styles.confTrack}>
          <View style={[styles.confFill, {
            width: `${signal.ml_probability * 100}%` as any,
            backgroundColor: COLORS.info,
          }]} />
        </View>
        <Text style={[styles.confValue, { color: COLORS.info }]}>
          {(signal.ml_probability * 100).toFixed(1)}%
        </Text>
      </View>

      {/* Price grid */}
      <View style={styles.grid}>
        {[
          { label: 'ENTRY',  value: signal.entry_price.toFixed(2),  color: COLORS.text },
          { label: 'STOP',   value: signal.stop_loss.toFixed(2),    color: COLORS.loss },
          { label: 'TARGET', value: signal.take_profit.toFixed(2),  color: COLORS.profit },
          { label: 'R:R',    value: signal.risk_reward.toFixed(2) + 'x', color: signal.risk_reward >= 2 ? COLORS.profit : COLORS.warning },
        ].map(({ label, value, color }) => (
          <View key={label} style={styles.gridItem}>
            <Text style={styles.gridLabel}>{label}</Text>
            <Text style={[styles.gridValue, { color }]}>{value}</Text>
          </View>
        ))}
      </View>

      {/* Factor breakdown */}
      {signal.contributing_factors && signal.contributing_factors.length > 0 && (
        <View style={styles.factors}>
          {signal.contributing_factors.slice(0, 4).map((f) => (
            <View key={f.name} style={styles.factorRow}>
              <Text style={styles.factorName}>{f.name}</Text>
              <View style={styles.factorBar}>
                <View style={[styles.factorFill, {
                  width: `${f.weight * 100}%` as any,
                  backgroundColor: f.direction === 'bullish' ? COLORS.buy :
                                   f.direction === 'bearish' ? COLORS.sell : COLORS.textMuted,
                }]} />
              </View>
              <Text style={styles.factorWeight}>{(f.weight * 100).toFixed(0)}%</Text>
            </View>
          ))}
        </View>
      )}

      {/* Reasoning */}
      {signal.reasoning && (
        <View style={styles.reasoning}>
          <Ionicons name="bulb-outline" size={13} color={COLORS.warning} />
          <Text style={styles.reasoningText} numberOfLines={3}>{signal.reasoning}</Text>
        </View>
      )}

      {/* Regime + data quality */}
      <View style={styles.metaRow}>
        <View style={styles.regimeChip}>
          <Text style={styles.regimeText}>{signal.regime}</Text>
        </View>
        {signal.data_quality != null && (
          <Text style={[styles.qualityText, {
            color: signal.data_quality >= 0.8 ? COLORS.profit :
                   signal.data_quality >= 0.6 ? COLORS.warning : COLORS.loss,
          }]}>
            DQ: {(signal.data_quality * 100).toFixed(0)}%
          </Text>
        )}
        {signal.approved && (
          <View style={styles.approvedBadge}>
            <Ionicons name="checkmark-circle" size={12} color={COLORS.profit} />
            <Text style={styles.approvedText}>APPROVED</Text>
          </View>
        )}
      </View>

      {/* Action button */}
      {!isExpired && signal.direction !== 'neutral' && !signal.approved && (
        <TouchableOpacity
          style={[styles.tradeBtn, { backgroundColor: dirColor }]}
          onPress={handleApprove}
          activeOpacity={0.85}
        >
          <Ionicons
            name={signal.direction === 'long' ? 'arrow-up-circle' : 'arrow-down-circle'}
            size={18}
            color={COLORS.white}
          />
          <Text style={styles.tradeBtnText}>
            ONE-TAP {signal.direction === 'long' ? 'BUY' : 'SELL'} {signal.symbol}
          </Text>
        </TouchableOpacity>
      )}

      {isExpired && (
        <Text style={styles.expiredText}>Signal expired</Text>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card:          {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.xl,
    padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border,
    gap: SPACING.sm, ...SHADOW.md,
  },
  expired:       { opacity: 0.45 },
  header:        { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  headerLeft:    { gap: 3 },
  symbol:        { ...TEXT.h3, color: COLORS.text },
  time:          { ...TEXT.caption, color: COLORS.textMuted },
  directionBadge:{ flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.md, borderWidth: 1 },
  directionText: { ...TEXT.label, fontSize: 12 },
  confRow:       { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  confLabel:     { ...TEXT.labelSM, color: COLORS.textDim, width: 64 },
  confTrack:     { flex: 1, height: 5, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden' },
  confFill:      { height: '100%', borderRadius: RADIUS.full },
  confValue:     { ...TEXT.numericXS, width: 38, textAlign: 'right', fontWeight: '700' },
  grid:          { flexDirection: 'row', justifyContent: 'space-between' },
  gridItem:      { alignItems: 'center', flex: 1 },
  gridLabel:     { ...TEXT.labelSM, color: COLORS.textDim },
  gridValue:     { ...TEXT.numericSM, marginTop: 3 },
  factors:       { gap: 5, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  factorRow:     { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  factorName:    { ...TEXT.captionSM, color: COLORS.textMuted, width: 80 },
  factorBar:     { flex: 1, height: 4, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden' },
  factorFill:    { height: '100%', borderRadius: RADIUS.full },
  factorWeight:  { ...TEXT.captionSM, color: COLORS.textDim, width: 28, textAlign: 'right' },
  reasoning:     { flexDirection: 'row', gap: SPACING.xs, alignItems: 'flex-start', backgroundColor: COLORS.warningDim, borderRadius: RADIUS.sm, padding: SPACING.sm },
  reasoningText: { ...TEXT.caption, color: COLORS.textSecondary, flex: 1, lineHeight: 16 },
  metaRow:       { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, flexWrap: 'wrap' },
  regimeChip:    { backgroundColor: COLORS.surfaceAlt, paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border },
  regimeText:    { ...TEXT.captionSM, color: COLORS.textMuted },
  qualityText:   { ...TEXT.captionSM, fontWeight: '700' },
  approvedBadge: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: COLORS.profitDim, paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm },
  approvedText:  { ...TEXT.captionSM, color: COLORS.profit, fontWeight: '700' },
  tradeBtn:      { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACING.sm, height: 48, borderRadius: RADIUS.md },
  tradeBtnText:  { color: COLORS.white, fontWeight: '800', fontSize: 13, letterSpacing: 1 },
  expiredText:   { ...TEXT.caption, color: COLORS.textDim, textAlign: 'center' },
});
