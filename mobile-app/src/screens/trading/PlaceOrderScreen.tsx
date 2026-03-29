// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/trading/PlaceOrderScreen.tsx
 * =====================================
 * Full order ticket: symbol, side toggle, quantity, order type,
 * limit price, stop loss, take profit, risk preview, submit.
 */

import React, { useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, ScrollView,
  TouchableOpacity, KeyboardAvoidingView, Platform, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { TradingStackParamList, OrderSide, OrderType } from '../../types';
import { useTradingStore } from '../../store/tradingStore';
import { useLivePrice } from '../../hooks/useLivePrice';
import { Button } from '../../components/Button';
import { ErrorBanner } from '../../components/ErrorBanner';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { formatCurrency } from '../../utils/formatters';

type Props = {
  navigation: NativeStackNavigationProp<TradingStackParamList, 'PlaceOrder'>;
  route: RouteProp<TradingStackParamList, 'PlaceOrder'>;
};

export function PlaceOrderScreen({ navigation, route }: Props) {
  const { symbol, side: initialSide = 'buy' } = route.params;
  const [side, setSide] = useState<OrderSide>(initialSide);
  const [orderType, setOrderType] = useState<OrderType>('market');
  const [quantity, setQuantity] = useState('0.01');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');

  const { placeOrder, account, isLoading, error, clearError } = useTradingStore();
  const quote = useLivePrice(symbol);

  const qty = parseFloat(quantity) || 0;
  const currentPrice = quote?.mid ?? 0;
  const positionValue = qty * currentPrice;
  const riskPct = account ? (positionValue / account.equity) * 100 : 0;

  const handleSubmit = async () => {
    clearError();
    if (qty <= 0) {
      Alert.alert('Invalid Quantity', 'Enter a valid lot size.');
      return;
    }
    if (orderType === 'limit' && !limitPrice) {
      Alert.alert('Limit Price Required', 'Enter a limit price for limit orders.');
      return;
    }

    Alert.alert(
      'Confirm Order',
      `${side.toUpperCase()} ${qty} lots of ${symbol}\n` +
      `Type: ${orderType}\n` +
      `${orderType !== 'market' ? `Price: ${limitPrice}\n` : ''}` +
      `${stopLoss ? `Stop Loss: ${stopLoss}\n` : ''}` +
      `${takeProfit ? `Take Profit: ${takeProfit}\n` : ''}` +
      `Est. Value: ${formatCurrency(positionValue)}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Place Order',
          style: 'destructive',
          onPress: async () => {
            try {
              await placeOrder({
                symbol,
                side,
                quantity: qty,
                order_type: orderType,
                price: limitPrice ? parseFloat(limitPrice) : undefined,
                stop_loss: stopLoss ? parseFloat(stopLoss) : undefined,
                take_profit: takeProfit ? parseFloat(takeProfit) : undefined,
              });
              navigation.goBack();
            } catch {
              // error shown via store
            }
          },
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.kav}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {/* Symbol + live price */}
          <Card style={styles.priceCard}>
            <Text style={styles.symbolText}>{symbol}</Text>
            <Text style={styles.priceText}>{quote ? quote.mid.toFixed(2) : '—'}</Text>
            <View style={styles.bidAskRow}>
              <Text style={[styles.bidAsk, { color: COLORS.sell }]}>
                BID {quote?.bid.toFixed(2) ?? '—'}
              </Text>
              <Text style={[styles.bidAsk, { color: COLORS.buy }]}>
                ASK {quote?.ask.toFixed(2) ?? '—'}
              </Text>
            </View>
          </Card>

          {error && <ErrorBanner message={error} onDismiss={clearError} />}

          {/* Side toggle */}
          <View style={styles.sideToggle}>
            {(['buy', 'sell'] as OrderSide[]).map((s) => (
              <TouchableOpacity
                key={s}
                style={[
                  styles.sideBtn,
                  side === s && { backgroundColor: s === 'buy' ? COLORS.buy : COLORS.sell },
                ]}
                onPress={() => setSide(s)}
              >
                <Text style={[styles.sideBtnText, side === s && styles.sideBtnTextActive]}>
                  {s === 'buy' ? '▲ BUY' : '▼ SELL'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Order type */}
          <View style={styles.typeRow}>
            {(['market', 'limit', 'stop'] as OrderType[]).map((t) => (
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

          {/* Fields */}
          <View style={styles.fields}>
            <Field label="Lot Size" value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad" placeholder="0.01" />
            {orderType !== 'market' && (
              <Field label={orderType === 'limit' ? 'Limit Price' : 'Stop Price'} value={limitPrice} onChangeText={setLimitPrice} keyboardType="decimal-pad" placeholder={quote?.mid.toFixed(2) ?? '0.00'} />
            )}
            <Field label="Stop Loss (optional)" value={stopLoss} onChangeText={setStopLoss} keyboardType="decimal-pad" placeholder="e.g. 2300.00" />
            <Field label="Take Profit (optional)" value={takeProfit} onChangeText={setTakeProfit} keyboardType="decimal-pad" placeholder="e.g. 2400.00" />
          </View>

          {/* Risk preview */}
          <Card style={styles.riskCard}>
            <Text style={styles.riskTitle}>Order Preview</Text>
            <View style={styles.riskRow}>
              <Text style={styles.riskLabel}>Position Value</Text>
              <Text style={styles.riskValue}>{formatCurrency(positionValue)}</Text>
            </View>
            <View style={styles.riskRow}>
              <Text style={styles.riskLabel}>Account Risk</Text>
              <Text style={[styles.riskValue, { color: riskPct > 5 ? COLORS.sell : COLORS.text }]}>
                {riskPct.toFixed(2)}%
              </Text>
            </View>
            {riskPct > 5 && (
              <Text style={styles.riskWarning}>
                ⚠️ Position exceeds 5% of equity — consider reducing size.
              </Text>
            )}
          </Card>

          <Button
            title={`Place ${side.toUpperCase()} Order`}
            onPress={handleSubmit}
            variant={side === 'buy' ? 'buy' : 'sell'}
            loading={isLoading}
            disabled={qty <= 0}
            fullWidth
            style={styles.submitBtn}
          />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field({
  label, value, onChangeText, keyboardType, placeholder,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  keyboardType?: 'decimal-pad' | 'default';
  placeholder?: string;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        style={styles.fieldInput}
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType ?? 'default'}
        placeholder={placeholder}
        placeholderTextColor={COLORS.textDim}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  kav: { flex: 1 },
  scroll: { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  priceCard: { alignItems: 'center', gap: SPACING.xs },
  symbolText: { color: COLORS.textMuted, fontSize: 14, fontWeight: '600' },
  priceText: { color: COLORS.text, fontSize: 36, fontWeight: '900', fontFamily: 'Courier' },
  bidAskRow: { flexDirection: 'row', gap: SPACING.xl },
  bidAsk: { fontSize: 14, fontWeight: '600' },
  sideToggle: { flexDirection: 'row', gap: SPACING.sm },
  sideBtn: {
    flex: 1, paddingVertical: SPACING.md, borderRadius: RADIUS.md,
    alignItems: 'center', borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  sideBtnText: { color: COLORS.textMuted, fontWeight: '700', fontSize: 16 },
  sideBtnTextActive: { color: COLORS.white },
  typeRow: { flexDirection: 'row', gap: SPACING.sm },
  typeChip: {
    flex: 1, paddingVertical: SPACING.sm, borderRadius: RADIUS.sm,
    alignItems: 'center', borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  typeChipActive: { backgroundColor: COLORS.surfaceAlt, borderColor: COLORS.accent },
  typeChipText: { color: COLORS.textMuted, fontSize: 12, fontWeight: '700' },
  typeChipTextActive: { color: COLORS.accent },
  fields: { gap: SPACING.sm },
  field: { gap: SPACING.xs },
  fieldLabel: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  fieldInput: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: RADIUS.md, padding: SPACING.md, color: COLORS.text, fontSize: 15,
  },
  riskCard: { gap: SPACING.sm },
  riskTitle: { color: COLORS.text, fontSize: 14, fontWeight: '700' },
  riskRow: { flexDirection: 'row', justifyContent: 'space-between' },
  riskLabel: { color: COLORS.textMuted, fontSize: 13 },
  riskValue: { color: COLORS.text, fontSize: 13, fontWeight: '600' },
  riskWarning: { color: COLORS.warning, fontSize: 12, lineHeight: 18 },
  submitBtn: { marginTop: SPACING.sm },
});
