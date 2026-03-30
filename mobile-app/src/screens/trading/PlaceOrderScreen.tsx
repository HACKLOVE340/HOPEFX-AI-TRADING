// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/trading/PlaceOrderScreen.tsx
 * ======================================
 * Modal order placement screen with real-time price, SL/TP calculator,
 * risk preview, and haptic confirmation.
 */

import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TextInput,
  TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';

import { useTradingStore } from '../../store/tradingStore';
import { useLivePrice }    from '../../hooks/useLivePrice';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW, sideColor } from '../../utils/theme';
import { TradingStackParamList } from '../../types';

type RouteT = RouteProp<TradingStackParamList, 'PlaceOrder'>;

export function PlaceOrderScreen() {
  const navigation = useNavigation();
  const route      = useRoute<RouteT>();
  const { symbol, side: initialSide = 'buy' } = route.params;

  const { placeOrder, riskMetrics, isLoading } = useTradingStore();
  const quote = useLivePrice(symbol);

  const [side, setSide]         = useState<'buy' | 'sell'>(initialSide);
  const [orderType, setOrderType] = useState<'market' | 'limit' | 'stop'>('market');
  const [quantity, setQuantity] = useState('0.01');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');

  const price = quote ? (side === 'buy' ? quote.ask : quote.bid) : null;
  const qty   = parseFloat(quantity) || 0;
  const sl    = parseFloat(stopLoss) || null;
  const tp    = parseFloat(takeProfit) || null;

  // Auto-suggest SL/TP based on ATR-like spread multiple
  useEffect(() => {
    if (!price || !quote) return;
    const spread = quote.spread;
    const slDist = spread * 20;
    const tpDist = spread * 40;
    if (!stopLoss)   setStopLoss((side === 'buy' ? price - slDist : price + slDist).toFixed(2));
    if (!takeProfit) setTakeProfit((side === 'buy' ? price + tpDist : price - tpDist).toFixed(2));
  }, [price, side]);

  const riskReward = sl && tp && price
    ? Math.abs(tp - price) / Math.abs(price - sl)
    : null;

  const estimatedPnl = sl && price && qty
    ? Math.abs(price - sl) * qty * 100
    : null;

  const handleSubmit = async () => {
    if (!qty || qty <= 0) {
      Alert.alert('Invalid Quantity', 'Enter a valid lot size');
      return;
    }
    if (riskMetrics?.kill_switch_active) {
      Alert.alert('Trading Halted', 'Kill switch is active. Trading is disabled.');
      return;
    }

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);

    try {
      await placeOrder({
        symbol,
        side,
        quantity: qty,
        order_type: orderType,
        price: orderType !== 'market' ? parseFloat(limitPrice) || undefined : undefined,
        stop_loss: sl ?? undefined,
        take_profit: tp ?? undefined,
      });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      navigation.goBack();
    } catch {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  };

  const sideC = sideColor(side);

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.closeBtn}>
            <Ionicons name="close" size={24} color={COLORS.textSecondary} />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Place Order · {symbol}</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {/* Live price */}
          <View style={styles.priceRow}>
            <Text style={styles.priceLabel}>MARKET PRICE</Text>
            <Text style={[styles.priceValue, { color: sideC }]}>
              {price ? price.toFixed(2) : '—'}
            </Text>
            {quote && (
              <Text style={styles.spreadLabel}>Spread: {quote.spread.toFixed(1)}</Text>
            )}
          </View>

          {/* Buy / Sell toggle */}
          <View style={styles.sideToggle}>
            {(['buy', 'sell'] as const).map((s) => (
              <TouchableOpacity
                key={s}
                style={[styles.sideBtn, side === s && {
                  backgroundColor: s === 'buy' ? COLORS.buy : COLORS.sell,
                  ...(s === 'buy' ? SHADOW.buyGlow : SHADOW.sellGlow),
                }]}
                onPress={() => { setSide(s); Haptics.selectionAsync(); }}
              >
                <Text style={[styles.sideBtnText, side === s && styles.sideBtnTextActive]}>
                  {s.toUpperCase()}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Order type */}
          <View style={styles.typeRow}>
            {(['market', 'limit', 'stop'] as const).map((t) => (
              <TouchableOpacity
                key={t}
                style={[styles.typeChip, orderType === t && styles.typeChipActive]}
                onPress={() => setOrderType(t)}
              >
                <Text style={[styles.typeChipText, orderType === t && styles.typeChipTextActive]}>
                  {t.toUpperCase()}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Quantity */}
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>LOT SIZE</Text>
            <View style={styles.inputRow}>
              <TouchableOpacity style={styles.stepBtn} onPress={() => setQuantity((Math.max(0.01, qty - 0.01)).toFixed(2))}>
                <Ionicons name="remove" size={18} color={COLORS.text} />
              </TouchableOpacity>
              <TextInput
                style={styles.input}
                value={quantity}
                onChangeText={setQuantity}
                keyboardType="decimal-pad"
                selectionColor={COLORS.accent}
              />
              <TouchableOpacity style={styles.stepBtn} onPress={() => setQuantity((qty + 0.01).toFixed(2))}>
                <Ionicons name="add" size={18} color={COLORS.text} />
              </TouchableOpacity>
            </View>
          </View>

          {/* Limit price (if not market) */}
          {orderType !== 'market' && (
            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>{orderType === 'limit' ? 'LIMIT PRICE' : 'STOP PRICE'}</Text>
              <TextInput
                style={[styles.input, styles.inputFull]}
                value={limitPrice}
                onChangeText={setLimitPrice}
                placeholder={price?.toFixed(2) ?? '0.00'}
                placeholderTextColor={COLORS.textDim}
                keyboardType="decimal-pad"
                selectionColor={COLORS.accent}
              />
            </View>
          )}

          {/* SL / TP */}
          <View style={styles.slTpRow}>
            <View style={[styles.inputGroup, { flex: 1 }]}>
              <Text style={[styles.inputLabel, { color: COLORS.loss }]}>STOP LOSS</Text>
              <TextInput
                style={[styles.input, styles.inputFull, { borderColor: COLORS.loss + '44' }]}
                value={stopLoss}
                onChangeText={setStopLoss}
                placeholder="0.00"
                placeholderTextColor={COLORS.textDim}
                keyboardType="decimal-pad"
                selectionColor={COLORS.loss}
              />
            </View>
            <View style={[styles.inputGroup, { flex: 1 }]}>
              <Text style={[styles.inputLabel, { color: COLORS.profit }]}>TAKE PROFIT</Text>
              <TextInput
                style={[styles.input, styles.inputFull, { borderColor: COLORS.profit + '44' }]}
                value={takeProfit}
                onChangeText={setTakeProfit}
                placeholder="0.00"
                placeholderTextColor={COLORS.textDim}
                keyboardType="decimal-pad"
                selectionColor={COLORS.profit}
              />
            </View>
          </View>

          {/* Risk preview */}
          {(riskReward || estimatedPnl) && (
            <View style={styles.riskPreview}>
              <Text style={styles.riskPreviewTitle}>RISK PREVIEW</Text>
              <View style={styles.riskPreviewRow}>
                {riskReward && (
                  <View style={styles.riskPreviewItem}>
                    <Text style={styles.riskPreviewLabel}>R:R</Text>
                    <Text style={[styles.riskPreviewValue, { color: riskReward >= 2 ? COLORS.profit : COLORS.warning }]}>
                      {riskReward.toFixed(2)}x
                    </Text>
                  </View>
                )}
                {estimatedPnl && (
                  <View style={styles.riskPreviewItem}>
                    <Text style={styles.riskPreviewLabel}>MAX LOSS</Text>
                    <Text style={[styles.riskPreviewValue, { color: COLORS.loss }]}>
                      ${estimatedPnl.toFixed(2)}
                    </Text>
                  </View>
                )}
              </View>
            </View>
          )}

          {/* Submit */}
          <TouchableOpacity
            style={[styles.submitBtn, { backgroundColor: sideC }, isLoading && styles.submitBtnDisabled]}
            onPress={handleSubmit}
            disabled={isLoading}
            activeOpacity={0.85}
          >
            {isLoading ? (
              <ActivityIndicator color={COLORS.white} />
            ) : (
              <Text style={styles.submitBtnText}>
                {side.toUpperCase()} {qty.toFixed(2)} {symbol}
              </Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:              { flex: 1, backgroundColor: COLORS.background },
  flex:              { flex: 1 },
  header:            { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: SPACING.md, borderBottomWidth: 1, borderBottomColor: COLORS.border, backgroundColor: COLORS.surface },
  closeBtn:          { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  headerTitle:       { ...TEXT.h4, color: COLORS.text },
  content:           { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  priceRow:          { alignItems: 'center', gap: 4 },
  priceLabel:        { ...TEXT.label, color: COLORS.textMuted },
  priceValue:        { ...TEXT.displayMD, fontWeight: '900' },
  spreadLabel:       { ...TEXT.caption, color: COLORS.textMuted },
  sideToggle:        { flexDirection: 'row', gap: SPACING.sm },
  sideBtn:           { flex: 1, height: 52, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.surfaceAlt, borderWidth: 1, borderColor: COLORS.border },
  sideBtnText:       { ...TEXT.label, color: COLORS.textMuted, fontSize: 14 },
  sideBtnTextActive: { color: COLORS.white, fontWeight: '800' },
  typeRow:           { flexDirection: 'row', gap: SPACING.sm },
  typeChip:          { flex: 1, paddingVertical: 8, borderRadius: RADIUS.sm, alignItems: 'center', backgroundColor: COLORS.surfaceAlt, borderWidth: 1, borderColor: COLORS.border },
  typeChipActive:    { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  typeChipText:      { ...TEXT.label, color: COLORS.textMuted, fontSize: 11 },
  typeChipTextActive:{ color: COLORS.black, fontWeight: '800' },
  inputGroup:        { gap: SPACING.xs },
  inputLabel:        { ...TEXT.label, color: COLORS.textMuted },
  inputRow:          { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  stepBtn:           { width: 44, height: 48, alignItems: 'center', justifyContent: 'center' },
  input:             { flex: 1, height: 48, textAlign: 'center', color: COLORS.text, fontSize: 18, fontWeight: '700', fontFamily: 'Courier New' },
  inputFull:         { flex: undefined, width: '100%', paddingHorizontal: SPACING.md, backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  slTpRow:           { flexDirection: 'row', gap: SPACING.sm },
  riskPreview:       { backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border, gap: SPACING.sm },
  riskPreviewTitle:  { ...TEXT.label, color: COLORS.textMuted },
  riskPreviewRow:    { flexDirection: 'row', gap: SPACING.lg },
  riskPreviewItem:   { alignItems: 'center', gap: 3 },
  riskPreviewLabel:  { ...TEXT.labelSM, color: COLORS.textDim },
  riskPreviewValue:  { ...TEXT.numericMD, fontWeight: '800' },
  submitBtn:         { height: 56, borderRadius: RADIUS.lg, alignItems: 'center', justifyContent: 'center', marginTop: SPACING.sm },
  submitBtnDisabled: { opacity: 0.5 },
  submitBtnText:     { color: COLORS.white, fontWeight: '900', fontSize: 16, letterSpacing: 1.5 },
});
