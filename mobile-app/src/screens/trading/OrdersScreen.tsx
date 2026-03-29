// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/trading/OrdersScreen.tsx
 * ==================================
 * Open and filled orders list with cancel support.
 */

import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useOrders } from '../../hooks/useOrders';
import { useRefreshOnFocus } from '../../hooks/useRefreshOnFocus';
import { Card } from '../../components/Card';
import { ErrorBanner } from '../../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { formatDateTime, formatCurrency } from '../../utils/formatters';
import { Order, TradingStackParamList } from '../../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

type Tab = 'open' | 'filled';

export function OrdersScreen() {
  const navigation = useNavigation<Nav>();
  const { openOrders, filledOrders, isLoading, error, cancelling, refresh, cancelOrder } =
    useOrders();
  const [tab, setTab] = useState<Tab>('open');

  useRefreshOnFocus(refresh);

  const orders = tab === 'open' ? openOrders : filledOrders;

  return (
    <SafeAreaView style={styles.safe}>
      {/* Tab bar */}
      <View style={styles.tabBar}>
        {(['open', 'filled'] as Tab[]).map((t) => (
          <TouchableOpacity
            key={t}
            style={[styles.tab, tab === t && styles.tabActive]}
            onPress={() => setTab(t)}
          >
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'open' ? `Open (${openOrders.length})` : `Filled (${filledOrders.length})`}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={isLoading} onRefresh={refresh} tintColor={COLORS.accent} />
        }
      >
        {error && <ErrorBanner message={error} />}

        {orders.length === 0 ? (
          <Text style={styles.emptyText}>
            {tab === 'open' ? 'No open orders.' : 'No filled orders.'}
          </Text>
        ) : (
          orders.map((order) => (
            <OrderRow
              key={order.id}
              order={order}
              cancelling={cancelling === order.id}
              onDetail={() => navigation.navigate('OrderDetail', { orderId: order.id })}
              onCancel={tab === 'open' ? () => cancelOrder(order.id) : undefined}
            />
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function OrderRow({
  order,
  cancelling,
  onDetail,
  onCancel,
}: {
  order: Order;
  cancelling: boolean;
  onDetail: () => void;
  onCancel?: () => void;
}) {
  const sideColor = order.side === 'buy' ? COLORS.buy : COLORS.sell;
  const statusColor: Record<string, string> = {
    open:      COLORS.accent,
    pending:   COLORS.warning,
    filled:    COLORS.profit,
    cancelled: COLORS.textMuted,
    rejected:  COLORS.loss,
  };

  return (
    <TouchableOpacity onPress={onDetail}>
      <Card style={styles.orderCard}>
        <View style={styles.orderRow}>
          <View style={styles.orderLeft}>
            <View style={styles.orderTopRow}>
              <Text style={styles.orderSymbol}>{order.symbol}</Text>
              <View style={[styles.statusBadge, { backgroundColor: (statusColor[order.status] ?? COLORS.textMuted) + '22' }]}>
                <Text style={[styles.statusText, { color: statusColor[order.status] ?? COLORS.textMuted }]}>
                  {order.status.toUpperCase()}
                </Text>
              </View>
            </View>
            <Text style={[styles.orderSide, { color: sideColor }]}>
              {order.side.toUpperCase()} · {order.type.toUpperCase()} · {order.quantity} lots
            </Text>
            {order.price != null && (
              <Text style={styles.orderPrice}>
                @ {order.price.toFixed(2)}
                {order.fill_price != null ? ` → filled @ ${order.fill_price.toFixed(2)}` : ''}
              </Text>
            )}
            <Text style={styles.orderMeta}>{formatDateTime(order.created_at)}</Text>
          </View>

          <View style={styles.orderRight}>
            {onCancel && (
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={onCancel}
                disabled={cancelling}
              >
                {cancelling ? (
                  <ActivityIndicator size="small" color={COLORS.loss} />
                ) : (
                  <Ionicons name="close-circle-outline" size={22} color={COLORS.loss} />
                )}
              </TouchableOpacity>
            )}
            <Ionicons name="chevron-forward" size={16} color={COLORS.textMuted} />
          </View>
        </View>

        {/* SL / TP row */}
        {(order.stop_loss != null || order.take_profit != null) && (
          <View style={styles.slTpRow}>
            {order.stop_loss != null && (
              <Text style={styles.slText}>SL {order.stop_loss.toFixed(2)}</Text>
            )}
            {order.take_profit != null && (
              <Text style={styles.tpText}>TP {order.take_profit.toFixed(2)}</Text>
            )}
          </View>
        )}
      </Card>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe:         { flex: 1, backgroundColor: COLORS.background },
  tabBar:       { flexDirection: 'row', backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  tab:          { flex: 1, paddingVertical: SPACING.md, alignItems: 'center' },
  tabActive:    { borderBottomWidth: 2, borderBottomColor: COLORS.accent },
  tabText:      { color: COLORS.textMuted, fontSize: 14, fontWeight: '600' },
  tabTextActive:{ color: COLORS.accent },
  content:      { padding: SPACING.md, gap: SPACING.sm, paddingBottom: SPACING.xl },
  emptyText:    { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl },
  orderCard:    { padding: SPACING.sm, gap: SPACING.xs },
  orderRow:     { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  orderLeft:    { flex: 1, gap: 3 },
  orderTopRow:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  orderSymbol:  { color: COLORS.text, fontSize: 15, fontWeight: '700' },
  statusBadge:  { paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.sm },
  statusText:   { fontSize: 10, fontWeight: '700' },
  orderSide:    { fontSize: 13, fontWeight: '600' },
  orderPrice:   { color: COLORS.textMuted, fontSize: 12 },
  orderMeta:    { color: COLORS.textDim, fontSize: 11 },
  orderRight:   { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  cancelBtn:    { padding: 4 },
  slTpRow:      { flexDirection: 'row', gap: SPACING.md, paddingTop: SPACING.xs, borderTopWidth: 1, borderTopColor: COLORS.border },
  slText:       { color: COLORS.loss, fontSize: 12, fontWeight: '600' },
  tpText:       { color: COLORS.profit, fontSize: 12, fontWeight: '600' },
});
