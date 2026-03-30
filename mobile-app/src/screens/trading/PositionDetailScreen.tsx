// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useTradingStore } from '../../store/tradingStore';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW, pnlColor, sideColor } from '../../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatDateTime } from '../../utils/formatters';
import { TradingStackParamList } from '../../types';

type RouteT = RouteProp<TradingStackParamList, 'PositionDetail'>;

export function PositionDetailScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteT>();
  const { positions, closePosition } = useTradingStore();
  const position = positions.find((p) => p.id === route.params.positionId);

  if (!position) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.empty}>
          <Text style={styles.emptyText}>Position not found</Text>
        </View>
      </SafeAreaView>
    );
  }

  const pnlC = pnlColor(position.unrealized_pnl);
  const sideC = sideColor(position.side);

  const handleClose = () => {
    Alert.alert(
      'Close Position',
      `Close ${position.side.toUpperCase()} ${position.quantity} ${position.symbol} at market?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Close Position',
          style: 'destructive',
          onPress: async () => {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
            await closePosition(position.id);
            navigation.goBack();
          },
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        {/* P&L hero */}
        <Card elevated style={styles.heroCard}>
          <Text style={styles.heroLabel}>UNREALIZED P&L</Text>
          <Text style={[styles.heroValue, { color: pnlC }]}>{formatPnl(position.unrealized_pnl)}</Text>
          <Text style={[styles.heroPct, { color: pnlC }]}>{formatPct(position.unrealized_pnl_pct)}</Text>
        </Card>

        {/* Details */}
        <Card style={styles.detailCard}>
          {[
            { label: 'Symbol',        value: position.symbol },
            { label: 'Side',          value: position.side.toUpperCase(), color: sideC },
            { label: 'Quantity',      value: `${position.quantity} lots` },
            { label: 'Entry Price',   value: position.entry_price.toFixed(2) },
            { label: 'Current Price', value: position.current_price.toFixed(2) },
            { label: 'Stop Loss',     value: position.stop_loss?.toFixed(2) ?? '—', color: COLORS.loss },
            { label: 'Take Profit',   value: position.take_profit?.toFixed(2) ?? '—', color: COLORS.profit },
            { label: 'Margin Used',   value: position.margin_used ? formatCurrency(position.margin_used) : '—' },
            { label: 'Swap',          value: position.swap ? formatPnl(position.swap) : '—' },
            { label: 'Opened',        value: formatDateTime(position.opened_at) },
          ].map(({ label, value, color }, i, arr) => (
            <React.Fragment key={label}>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>{label}</Text>
                <Text style={[styles.detailValue, color ? { color } : {}]}>{value}</Text>
              </View>
              {i < arr.length - 1 && <View style={styles.divider} />}
            </React.Fragment>
          ))}
        </Card>

        <TouchableOpacity style={styles.closeBtn} onPress={handleClose} activeOpacity={0.85}>
          <Ionicons name="close-circle" size={20} color={COLORS.white} />
          <Text style={styles.closeBtnText}>CLOSE POSITION AT MARKET</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: COLORS.background },
  content:     { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  empty:       { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText:   { ...TEXT.body, color: COLORS.textMuted },
  heroCard:    { alignItems: 'center', gap: SPACING.xs, paddingVertical: SPACING.lg },
  heroLabel:   { ...TEXT.label, color: COLORS.textMuted },
  heroValue:   { ...TEXT.displayLG },
  heroPct:     { ...TEXT.numericMD },
  detailCard:  { gap: 0 },
  detailRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: SPACING.sm },
  detailLabel: { ...TEXT.body, color: COLORS.textMuted },
  detailValue: { ...TEXT.numericSM, color: COLORS.text },
  divider:     { height: 1, backgroundColor: COLORS.border },
  closeBtn:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACING.sm, height: 56, backgroundColor: COLORS.sell, borderRadius: RADIUS.lg, ...SHADOW.sellGlow },
  closeBtnText:{ color: COLORS.white, fontWeight: '800', fontSize: 14, letterSpacing: 1 },
});
