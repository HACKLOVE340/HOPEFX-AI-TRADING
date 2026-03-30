// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { useTradingStore } from '../../store/tradingStore';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS, TEXT, sideColor } from '../../utils/theme';
import { formatDateTime } from '../../utils/formatters';
import { TradingStackParamList } from '../../types';

type RouteT = RouteProp<TradingStackParamList, 'OrderDetail'>;

export function OrderDetailScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteT>();
  const { orders, cancelOrder } = useTradingStore();
  const order = orders.find((o) => o.id === route.params.orderId);

  if (!order) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.empty}><Text style={styles.emptyText}>Order not found</Text></View>
      </SafeAreaView>
    );
  }

  const canCancel = order.status === 'open' || order.status === 'pending';

  const handleCancel = () => {
    Alert.alert('Cancel Order', 'Cancel this order?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Cancel Order', style: 'destructive',
        onPress: async () => {
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
          await cancelOrder(order.id);
          navigation.goBack();
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.card}>
          {[
            { label: 'Symbol',      value: order.symbol },
            { label: 'Side',        value: order.side.toUpperCase(), color: sideColor(order.side) },
            { label: 'Type',        value: order.type.toUpperCase() },
            { label: 'Quantity',    value: `${order.quantity} lots` },
            { label: 'Price',       value: order.price?.toFixed(2) ?? 'Market' },
            { label: 'Stop Loss',   value: order.stop_loss?.toFixed(2) ?? '—', color: COLORS.loss },
            { label: 'Take Profit', value: order.take_profit?.toFixed(2) ?? '—', color: COLORS.profit },
            { label: 'Status',      value: order.status.toUpperCase(), color: order.status === 'filled' ? COLORS.profit : COLORS.accent },
            { label: 'Created',     value: formatDateTime(order.created_at) },
            { label: 'Filled At',   value: order.filled_at ? formatDateTime(order.filled_at) : '—' },
            { label: 'Fill Price',  value: order.fill_price?.toFixed(2) ?? '—' },
          ].map(({ label, value, color }, i, arr) => (
            <React.Fragment key={label}>
              <View style={styles.row}>
                <Text style={styles.label}>{label}</Text>
                <Text style={[styles.value, color ? { color } : {}]}>{value}</Text>
              </View>
              {i < arr.length - 1 && <View style={styles.divider} />}
            </React.Fragment>
          ))}
        </Card>
        {canCancel && (
          <TouchableOpacity style={styles.cancelBtn} onPress={handleCancel}>
            <Text style={styles.cancelBtnText}>CANCEL ORDER</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:         { flex: 1, backgroundColor: COLORS.background },
  content:      { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  empty:        { flex: 1, alignItems: 'center', justifyContent: 'center' },
  emptyText:    { ...TEXT.body, color: COLORS.textMuted },
  card:         { gap: 0 },
  row:          { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: SPACING.sm },
  label:        { ...TEXT.body, color: COLORS.textMuted },
  value:        { ...TEXT.numericSM, color: COLORS.text },
  divider:      { height: 1, backgroundColor: COLORS.border },
  cancelBtn:    { height: 52, backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: COLORS.loss + '55' },
  cancelBtnText:{ color: COLORS.loss, fontWeight: '800', letterSpacing: 1 },
});
