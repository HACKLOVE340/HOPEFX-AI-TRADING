// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/trading/TradingScreen.tsx
 * ==================================
 * Live trading screen: symbol selector, live price, positions list,
 * open orders, and quick-access to PlaceOrder.
 */

import React, { useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  TouchableOpacity, RefreshControl, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useTradingStore } from '../../store/tradingStore';
import { useLivePrice } from '../../hooks/useLivePrice';
import { useRefreshOnFocus } from '../../hooks/useRefreshOnFocus';
import { Card } from '../../components/Card';
import { Button } from '../../components/Button';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatDateTime } from '../../utils/formatters';
import { TradingStackParamList, Position, Order } from '../../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

const SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

export function TradingScreen() {
  const navigation = useNavigation<Nav>();
  const [selectedSymbol, setSelectedSymbol] = useState('XAUUSD');
  const [activeTab, setActiveTab] = useState<'positions' | 'orders'>('positions');

  const {
    positions, orders, fetchPositions, fetchOrders,
    cancelOrder, closePosition, isLoading, subscribeToLive,
  } = useTradingStore();

  const quote = useLivePrice(selectedSymbol);

  useEffect(() => {
    fetchPositions();
    fetchOrders();
    const unsub = subscribeToLive();
    return unsub;
  }, []);

  useRefreshOnFocus(() => { fetchPositions(); fetchOrders(); });

  const openOrders = orders.filter((o) => o.status === 'open' || o.status === 'pending');

  return (
    <SafeAreaView style={styles.safe}>
      {/* Symbol selector */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.symbolBar}
        contentContainerStyle={styles.symbolBarContent}
      >
        {SYMBOLS.map((sym) => (
          <TouchableOpacity
            key={sym}
            style={[styles.symbolChip, selectedSymbol === sym && styles.symbolChipActive]}
            onPress={() => setSelectedSymbol(sym)}
          >
            <Text style={[styles.symbolChipText, selectedSymbol === sym && styles.symbolChipTextActive]}>
              {sym}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={() => { fetchPositions(); fetchOrders(); }}
            tintColor={COLORS.accent}
          />
        }
      >
        {/* Live price card */}
        <Card style={styles.priceCard} elevated>
          <View style={styles.priceRow}>
            <View>
              <Text style={styles.symbolLabel}>{selectedSymbol}</Text>
              {quote ? (
                <>
                  <Text style={styles.price}>{quote.mid.toFixed(2)}</Text>
                  <Text style={[
                    styles.change,
                    { color: quote.change_pct >= 0 ? COLORS.profit : COLORS.loss }
                  ]}>
                    {formatPct(quote.change_pct)}
                  </Text>
                </>
              ) : (
                <Text style={styles.noPrice}>Connecting…</Text>
              )}
            </View>
            <View style={styles.bidAsk}>
              <View style={styles.bidAskItem}>
                <Text style={styles.bidAskLabel}>BID</Text>
                <Text style={[styles.bidAskVal, { color: COLORS.sell }]}>
                  {quote?.bid.toFixed(2) ?? '—'}
                </Text>
              </View>
              <View style={styles.bidAskItem}>
                <Text style={styles.bidAskLabel}>ASK</Text>
                <Text style={[styles.bidAskVal, { color: COLORS.buy }]}>
                  {quote?.ask.toFixed(2) ?? '—'}
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.tradeButtons}>
            <TouchableOpacity
              style={[styles.tradeBtn, { backgroundColor: COLORS.sell }]}
              onPress={() => navigation.navigate('PlaceOrder', { symbol: selectedSymbol, side: 'sell' })}
            >
              <Text style={styles.tradeBtnLabel}>SELL</Text>
              <Text style={styles.tradeBtnPrice}>{quote?.bid.toFixed(2) ?? '—'}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tradeBtn, { backgroundColor: COLORS.buy }]}
              onPress={() => navigation.navigate('PlaceOrder', { symbol: selectedSymbol, side: 'buy' })}
            >
              <Text style={styles.tradeBtnLabel}>BUY</Text>
              <Text style={styles.tradeBtnPrice}>{quote?.ask.toFixed(2) ?? '—'}</Text>
            </TouchableOpacity>
          </View>
        </Card>

        {/* Tabs */}
        <View style={styles.tabs}>
          {(['positions', 'orders'] as const).map((tab) => (
            <TouchableOpacity
              key={tab}
              style={[styles.tab, activeTab === tab && styles.tabActive]}
              onPress={() => setActiveTab(tab)}
            >
              <Text style={[styles.tabText, activeTab === tab && styles.tabTextActive]}>
                {tab === 'positions'
                  ? `Positions (${positions.length})`
                  : `Orders (${openOrders.length})`}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Positions list */}
        {activeTab === 'positions' && (
          <View style={styles.list}>
            {positions.length === 0 ? (
              <Text style={styles.emptyText}>No open positions</Text>
            ) : (
              positions.map((pos) => (
                <PositionRow
                  key={pos.id}
                  position={pos}
                  onPress={() => navigation.navigate('PositionDetail', { positionId: pos.id })}
                  onClose={() => closePosition(pos.id)}
                />
              ))
            )}
          </View>
        )}

        {/* Orders list */}
        {activeTab === 'orders' && (
          <View style={styles.list}>
            {openOrders.length === 0 ? (
              <Text style={styles.emptyText}>No open orders</Text>
            ) : (
              openOrders.map((order) => (
                <OrderRow
                  key={order.id}
                  order={order}
                  onPress={() => navigation.navigate('OrderDetail', { orderId: order.id })}
                  onCancel={() => cancelOrder(order.id)}
                />
              ))
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PositionRow({
  position, onPress, onClose,
}: { position: Position; onPress: () => void; onClose: () => void }) {
  const pnlColor = position.unrealized_pnl >= 0 ? COLORS.profit : COLORS.loss;
  return (
    <TouchableOpacity onPress={onPress}>
      <Card style={styles.rowCard}>
        <View style={styles.rowTop}>
          <View>
            <Text style={styles.rowSymbol}>{position.symbol}</Text>
            <Text style={[styles.rowSide, { color: position.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
              {position.side.toUpperCase()} · {position.quantity} lots
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={[styles.rowPnl, { color: pnlColor }]}>
              {formatPnl(position.unrealized_pnl)}
            </Text>
            <Text style={[styles.rowPnlPct, { color: pnlColor }]}>
              {formatPct(position.unrealized_pnl_pct)}
            </Text>
          </View>
        </View>
        <View style={styles.rowBottom}>
          <Text style={styles.rowMeta}>Entry: {position.entry_price.toFixed(2)}</Text>
          <Text style={styles.rowMeta}>Current: {position.current_price.toFixed(2)}</Text>
          <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
            <Text style={styles.closeBtnText}>Close</Text>
          </TouchableOpacity>
        </View>
      </Card>
    </TouchableOpacity>
  );
}

function OrderRow({
  order, onPress, onCancel,
}: { order: Order; onPress: () => void; onCancel: () => void }) {
  return (
    <TouchableOpacity onPress={onPress}>
      <Card style={styles.rowCard}>
        <View style={styles.rowTop}>
          <View>
            <Text style={styles.rowSymbol}>{order.symbol}</Text>
            <Text style={[styles.rowSide, { color: order.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
              {order.side.toUpperCase()} · {order.quantity} lots · {order.type}
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={styles.rowStatus}>{order.status.toUpperCase()}</Text>
            {order.price && (
              <Text style={styles.rowMeta}>@ {order.price.toFixed(2)}</Text>
            )}
          </View>
        </View>
        <View style={styles.rowBottom}>
          <Text style={styles.rowMeta}>{formatDateTime(order.created_at)}</Text>
          <TouchableOpacity style={styles.cancelBtn} onPress={onCancel}>
            <Text style={styles.cancelBtnText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </Card>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  symbolBar: { maxHeight: 52, backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  symbolBarContent: { paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm, gap: SPACING.sm },
  symbolChip: { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.full, borderWidth: 1, borderColor: COLORS.border },
  symbolChipActive: { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  symbolChipText: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  symbolChipTextActive: { color: COLORS.white },
  scroll: { flex: 1 },
  content: { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  priceCard: { gap: SPACING.md },
  priceRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  symbolLabel: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  price: { color: COLORS.text, fontSize: 32, fontWeight: '900', fontFamily: 'Courier' },
  change: { fontSize: 13, fontWeight: '600' },
  noPrice: { color: COLORS.textMuted, fontSize: 16, marginTop: SPACING.sm },
  bidAsk: { gap: SPACING.sm },
  bidAskItem: { alignItems: 'flex-end' },
  bidAskLabel: { color: COLORS.textMuted, fontSize: 11, textTransform: 'uppercase' },
  bidAskVal: { fontSize: 18, fontWeight: '700', fontFamily: 'Courier' },
  tradeButtons: { flexDirection: 'row', gap: SPACING.sm },
  tradeBtn: { flex: 1, paddingVertical: SPACING.md, borderRadius: RADIUS.md, alignItems: 'center' },
  tradeBtnLabel: { color: COLORS.white, fontWeight: '800', fontSize: 14, letterSpacing: 1 },
  tradeBtnPrice: { color: 'rgba(255,255,255,0.8)', fontSize: 16, fontWeight: '700', fontFamily: 'Courier', marginTop: 2 },
  tabs: { flexDirection: 'row', backgroundColor: COLORS.surface, borderRadius: RADIUS.md, padding: 4, borderWidth: 1, borderColor: COLORS.border },
  tab: { flex: 1, paddingVertical: SPACING.sm, alignItems: 'center', borderRadius: RADIUS.sm - 2 },
  tabActive: { backgroundColor: COLORS.accent },
  tabText: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  tabTextActive: { color: COLORS.white },
  list: { gap: SPACING.sm },
  emptyText: { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl, fontSize: 14 },
  rowCard: { padding: SPACING.sm, gap: SPACING.sm },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  rowSymbol: { color: COLORS.text, fontSize: 15, fontWeight: '700' },
  rowSide: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  rowPnl: { fontSize: 16, fontWeight: '700', fontFamily: 'Courier' },
  rowPnlPct: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  rowBottom: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  rowMeta: { color: COLORS.textMuted, fontSize: 12, flex: 1 },
  rowStatus: { color: COLORS.warning, fontSize: 12, fontWeight: '700' },
  closeBtn: { backgroundColor: COLORS.sell, paddingHorizontal: SPACING.md, paddingVertical: 4, borderRadius: RADIUS.sm },
  closeBtnText: { color: COLORS.white, fontSize: 12, fontWeight: '700' },
  cancelBtn: { backgroundColor: COLORS.surfaceAlt, paddingHorizontal: SPACING.md, paddingVertical: 4, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border },
  cancelBtnText: { color: COLORS.textMuted, fontSize: 12, fontWeight: '600' },
});
