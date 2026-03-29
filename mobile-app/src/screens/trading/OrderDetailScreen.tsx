// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { TradingStackParamList } from '../../types';
import { useTradingStore } from '../../store/tradingStore';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { formatDateTime, formatCurrency } from '../../utils/formatters';

type Props = {
  navigation: NativeStackNavigationProp<TradingStackParamList, 'OrderDetail'>;
  route: RouteProp<TradingStackParamList, 'OrderDetail'>;
};

export function OrderDetailScreen({ navigation, route }: Props) {
  const { orderId } = route.params;
  const { orders, cancelOrder } = useTradingStore();
  const order = orders.find((o) => o.id === orderId);

  if (!order) {
    return (
      <SafeAreaView style={styles.safe}>
        <Text style={styles.notFound}>Order not found.</Text>
      </SafeAreaView>
    );
  }

  const handleCancel = () => {
    Alert.alert('Cancel Order', 'Are you sure you want to cancel this order?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Yes, Cancel',
        style: 'destructive',
        onPress: async () => {
          await cancelOrder(order.id);
          navigation.goBack();
        },
      },
    ]);
  };

  const rows: [string, string][] = [
    ['Order ID', order.id.slice(0, 16) + '…'],
    ['Symbol', order.symbol],
    ['Side', order.side.toUpperCase()],
    ['Type', order.type.toUpperCase()],
    ['Quantity', `${order.quantity} lots`],
    ['Status', order.status.toUpperCase()],
    ['Created', formatDateTime(order.created_at)],
    ...(order.price ? [['Limit Price', order.price.toFixed(2)] as [string, string]] : []),
    ...(order.stop_loss ? [['Stop Loss', order.stop_loss.toFixed(2)] as [string, string]] : []),
    ...(order.take_profit ? [['Take Profit', order.take_profit.toFixed(2)] as [string, string]] : []),
    ...(order.fill_price ? [['Fill Price', order.fill_price.toFixed(2)] as [string, string]] : []),
    ...(order.filled_at ? [['Filled At', formatDateTime(order.filled_at)] as [string, string]] : []),
  ];

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.card}>
          <View style={styles.header}>
            <Text style={styles.symbol}>{order.symbol}</Text>
            <View style={[
              styles.statusBadge,
              { backgroundColor: order.status === 'filled' ? COLORS.buy + '33' : COLORS.warning + '33' }
            ]}>
              <Text style={[
                styles.statusText,
                { color: order.status === 'filled' ? COLORS.buy : COLORS.warning }
              ]}>
                {order.status.toUpperCase()}
              </Text>
            </View>
          </View>

          {rows.map(([label, value]) => (
            <View key={label} style={styles.row}>
              <Text style={styles.rowLabel}>{label}</Text>
              <Text style={styles.rowValue}>{value}</Text>
            </View>
          ))}
        </Card>

        {(order.status === 'open' || order.status === 'pending') && (
          <TouchableOpacity style={styles.cancelBtn} onPress={handleCancel}>
            <Text style={styles.cancelBtnText}>Cancel Order</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: SPACING.md, gap: SPACING.md },
  notFound: { color: COLORS.textMuted, textAlign: 'center', marginTop: SPACING.xl },
  card: { gap: SPACING.sm },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  symbol: { color: COLORS.text, fontSize: 22, fontWeight: '800' },
  statusBadge: { paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.sm },
  statusText: { fontSize: 12, fontWeight: '700' },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: SPACING.xs, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  rowLabel: { color: COLORS.textMuted, fontSize: 13 },
  rowValue: { color: COLORS.text, fontSize: 13, fontWeight: '600' },
  cancelBtn: {
    backgroundColor: COLORS.sell + '22', borderWidth: 1, borderColor: COLORS.sell,
    borderRadius: RADIUS.md, padding: SPACING.md, alignItems: 'center',
  },
  cancelBtnText: { color: COLORS.sell, fontWeight: '700', fontSize: 15 },
});
