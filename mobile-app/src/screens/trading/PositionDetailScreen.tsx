// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { TradingStackParamList } from '../../types';
import { useTradingStore } from '../../store/tradingStore';
import { useLivePrice } from '../../hooks/useLivePrice';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatDateTime } from '../../utils/formatters';

type Props = {
  navigation: NativeStackNavigationProp<TradingStackParamList, 'PositionDetail'>;
  route: RouteProp<TradingStackParamList, 'PositionDetail'>;
};

export function PositionDetailScreen({ navigation, route }: Props) {
  const { positionId } = route.params;
  const { positions, closePosition } = useTradingStore();
  const position = positions.find((p) => p.id === positionId);
  const quote = useLivePrice(position?.symbol ?? '');

  if (!position) {
    return (
      <SafeAreaView style={styles.safe}>
        <Text style={styles.notFound}>Position not found or already closed.</Text>
      </SafeAreaView>
    );
  }

  const pnlColor = position.unrealized_pnl >= 0 ? COLORS.profit : COLORS.loss;
  const currentPrice = quote?.mid ?? position.current_price;
  const liveUnrealizedPnl = (currentPrice - position.entry_price) *
    position.quantity * (position.side === 'buy' ? 1 : -1);

  const handleClose = () => {
    Alert.alert(
      'Close Position',
      `Close ${position.side.toUpperCase()} ${position.quantity} lots of ${position.symbol}?\n` +
      `Current P&L: ${formatPnl(liveUnrealizedPnl)}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Close Position',
          style: 'destructive',
          onPress: async () => {
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
        {/* P&L Hero */}
        <Card style={styles.heroCard} elevated>
          <Text style={styles.heroSymbol}>{position.symbol}</Text>
          <Text style={[styles.heroPnl, { color: pnlColor }]}>
            {formatPnl(liveUnrealizedPnl)}
          </Text>
          <Text style={[styles.heroPct, { color: pnlColor }]}>
            {formatPct(position.unrealized_pnl_pct)}
          </Text>
          <View style={[styles.sideBadge, { backgroundColor: position.side === 'buy' ? COLORS.buy + '33' : COLORS.sell + '33' }]}>
            <Text style={[styles.sideText, { color: position.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
              {position.side.toUpperCase()} · {position.quantity} lots
            </Text>
          </View>
        </Card>

        {/* Details */}
        <Card style={styles.detailCard}>
          {[
            ['Entry Price', position.entry_price.toFixed(2)],
            ['Current Price', currentPrice.toFixed(2)],
            ['Quantity', `${position.quantity} lots`],
            ['Opened', formatDateTime(position.opened_at)],
          ].map(([label, value]) => (
            <View key={label} style={styles.row}>
              <Text style={styles.rowLabel}>{label}</Text>
              <Text style={styles.rowValue}>{value}</Text>
            </View>
          ))}
        </Card>

        <TouchableOpacity style={styles.closeBtn} onPress={handleClose}>
          <Text style={styles.closeBtnText}>Close Position</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: SPACING.md, gap: SPACING.md },
  notFound: { color: COLORS.textMuted, textAlign: 'center', marginTop: SPACING.xl },
  heroCard: { alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.xl },
  heroSymbol: { color: COLORS.textMuted, fontSize: 14, fontWeight: '600' },
  heroPnl: { fontSize: 40, fontWeight: '900', fontFamily: 'Courier' },
  heroPct: { fontSize: 18, fontWeight: '700' },
  sideBadge: { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.full, marginTop: SPACING.sm },
  sideText: { fontWeight: '700', fontSize: 14 },
  detailCard: { gap: SPACING.sm },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: SPACING.xs, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  rowLabel: { color: COLORS.textMuted, fontSize: 13 },
  rowValue: { color: COLORS.text, fontSize: 13, fontWeight: '600' },
  closeBtn: {
    backgroundColor: COLORS.sell, borderRadius: RADIUS.md,
    padding: SPACING.md, alignItems: 'center',
  },
  closeBtnText: { color: COLORS.white, fontWeight: '800', fontSize: 16 },
});
