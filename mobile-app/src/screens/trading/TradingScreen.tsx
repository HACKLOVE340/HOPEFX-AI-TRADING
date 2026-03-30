// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/trading/TradingScreen.tsx
 * ==================================
 * Elite trading screen: live ticker with spread depth visualization,
 * microstructure indicators, order flow, positions and orders.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  TouchableOpacity, RefreshControl, Animated,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';

import { useTradingStore }   from '../../store/tradingStore';
import { useLivePrice }      from '../../hooks/useLivePrice';
import { useRefreshOnFocus } from '../../hooks/useRefreshOnFocus';
import { LiveTicker }        from '../../components/LiveTicker';
import { MicrostructureBar } from '../../components/MicrostructureBar';
import { KillSwitchBanner }  from '../../components/KillSwitchBanner';
import { Card }              from '../../components/Card';

import { COLORS, SPACING, RADIUS, TEXT, SHADOW, pnlColor, sideColor } from '../../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatDateTime } from '../../utils/formatters';
import { TradingStackParamList, Position, Order } from '../../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

const SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

export function TradingScreen() {
  const navigation = useNavigation<Nav>();
  const [selectedSymbol, setSelectedSymbol] = useState('XAUUSD');
  const [activeTab, setActiveTab] = useState<'positions' | 'orders'>('positions');

  const {
    positions, orders, riskMetrics, microstructure,
    fetchPositions, fetchOrders,
    cancelOrder, closePosition, isLoading, subscribeToLive,
  } = useTradingStore();

  const quote = useLivePrice(selectedSymbol);
  const micro = microstructure[selectedSymbol] ?? null;

  useEffect(() => {
    fetchPositions();
    fetchOrders();
    const unsub = subscribeToLive();
    return unsub;
  }, []);

  useRefreshOnFocus(() => { fetchPositions(); fetchOrders(); });

  const handleRefresh = useCallback(() => { fetchPositions(); fetchOrders(); }, []);

  const handleBuy = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    navigation.navigate('PlaceOrder', { symbol: selectedSymbol, side: 'buy' });
  };
  const handleSell = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    navigation.navigate('PlaceOrder', { symbol: selectedSymbol, side: 'sell' });
  };

  const openOrders = orders.filter((o) => o.status === 'open' || o.status === 'pending');
  const symbolPositions = positions.filter((p) => p.symbol === selectedSymbol);
  const totalPnl = symbolPositions.reduce((s, p) => s + p.unrealized_pnl, 0);

  return (
    <SafeAreaView style={styles.safe}>
      {/* ── Symbol selector bar ── */}
      <View style={styles.symbolBar}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.symbolBarContent}
        >
          {SYMBOLS.map((sym) => {
            const symQuote = useTradingStore.getState().quotes[sym];
            const isActive = selectedSymbol === sym;
            return (
              <TouchableOpacity
                key={sym}
                style={[styles.symbolChip, isActive && styles.symbolChipActive]}
                onPress={() => {
                  setSelectedSymbol(sym);
                  Haptics.selectionAsync();
                }}
              >
                <Text style={[styles.symbolChipText, isActive && styles.symbolChipTextActive]}>
                  {sym}
                </Text>
                {symQuote && (
                  <Text style={[
                    styles.symbolChipChange,
                    { color: symQuote.change_pct >= 0 ? COLORS.profit : COLORS.loss }
                  ]}>
                    {symQuote.change_pct >= 0 ? '+' : ''}{symQuote.change_pct.toFixed(2)}%
                  </Text>
                )}
              </TouchableOpacity>
            );
          })}
        </ScrollView>
        <TouchableOpacity
          style={styles.watchlistBtn}
          onPress={() => navigation.navigate('Watchlist')}
        >
          <Ionicons name="star-outline" size={18} color={COLORS.accent} />
        </TouchableOpacity>
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={handleRefresh}
            tintColor={COLORS.accent}
            colors={[COLORS.accent]}
          />
        }
      >
        {/* Kill switch */}
        {riskMetrics?.kill_switch_active && (
          <KillSwitchBanner
            reason={riskMetrics.kill_switch_reason}
            triggeredAt={riskMetrics.kill_switch_triggered_at}
          />
        )}

        {/* ── Live ticker with trade buttons ── */}
        <LiveTicker
          quote={quote}
          symbol={selectedSymbol}
          onBuy={!riskMetrics?.kill_switch_active ? handleBuy : undefined}
          onSell={!riskMetrics?.kill_switch_active ? handleSell : undefined}
        />

        {/* ── Spread depth visualization ── */}
        {quote && (
          <Card style={styles.spreadCard}>
            <Text style={styles.cardLabel}>SPREAD DEPTH</Text>
            <SpreadDepthBar
              bid={quote.bid}
              ask={quote.ask}
              spread={quote.spread}
              spreadPct={quote.spread_pct ?? (quote.spread / quote.mid) * 100}
            />
          </Card>
        )}

        {/* ── Microstructure ── */}
        <MicrostructureBar micro={micro} symbol={selectedSymbol} />

        {/* ── Symbol position summary ── */}
        {symbolPositions.length > 0 && (
          <Card style={styles.posSummary}>
            <View style={styles.posSummaryHeader}>
              <Text style={styles.cardLabel}>{selectedSymbol} EXPOSURE</Text>
              <Text style={[styles.posSummaryPnl, { color: pnlColor(totalPnl) }]}>
                {formatPnl(totalPnl)}
              </Text>
            </View>
            <View style={styles.posSummaryStats}>
              <View style={styles.posSummaryStat}>
                <Text style={styles.statLabel}>POSITIONS</Text>
                <Text style={styles.statValue}>{symbolPositions.length}</Text>
              </View>
              <View style={styles.posSummaryStat}>
                <Text style={styles.statLabel}>NET LOTS</Text>
                <Text style={styles.statValue}>
                  {symbolPositions.reduce((s, p) =>
                    s + (p.side === 'buy' ? p.quantity : -p.quantity), 0
                  ).toFixed(2)}
                </Text>
              </View>
              <View style={styles.posSummaryStat}>
                <Text style={styles.statLabel}>AVG ENTRY</Text>
                <Text style={styles.statValue}>
                  {symbolPositions.length > 0
                    ? (symbolPositions.reduce((s, p) => s + p.entry_price, 0) / symbolPositions.length).toFixed(2)
                    : '—'}
                </Text>
              </View>
            </View>
          </Card>
        )}

        {/* ── Tabs: Positions / Orders ── */}
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

        {/* ── Positions list ── */}
        {activeTab === 'positions' && (
          <View style={styles.list}>
            {positions.length === 0 ? (
              <EmptyState message="No open positions" icon="layers-outline" />
            ) : (
              positions.map((pos) => (
                <PositionRow
                  key={pos.id}
                  position={pos}
                  onPress={() => navigation.navigate('PositionDetail', { positionId: pos.id })}
                  onClose={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                    closePosition(pos.id);
                  }}
                />
              ))
            )}
          </View>
        )}

        {/* ── Orders list ── */}
        {activeTab === 'orders' && (
          <View style={styles.list}>
            {openOrders.length === 0 ? (
              <EmptyState message="No open orders" icon="receipt-outline" />
            ) : (
              openOrders.map((order) => (
                <OrderRow
                  key={order.id}
                  order={order}
                  onPress={() => navigation.navigate('OrderDetail', { orderId: order.id })}
                  onCancel={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    cancelOrder(order.id);
                  }}
                />
              ))
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Spread depth bar ──────────────────────────────────────────────────────────

function SpreadDepthBar({
  bid, ask, spread, spreadPct,
}: { bid: number; ask: number; spread: number; spreadPct: number }) {
  const isWide = spreadPct > 0.05;
  const spreadColor = isWide ? COLORS.warning : COLORS.accent;

  return (
    <View style={spreadStyles.container}>
      {/* Bid side */}
      <View style={spreadStyles.side}>
        <Text style={[spreadStyles.price, { color: COLORS.sell }]}>{bid.toFixed(2)}</Text>
        <Text style={spreadStyles.sideLabel}>BID</Text>
      </View>

      {/* Spread bar */}
      <View style={spreadStyles.barWrap}>
        <View style={spreadStyles.barTrack}>
          <View style={[spreadStyles.bidFill, { flex: 1 }]} />
          <View style={[spreadStyles.spreadGap, { width: Math.max(spreadPct * 800, 4) }]} />
          <View style={[spreadStyles.askFill, { flex: 1 }]} />
        </View>
        <View style={spreadStyles.spreadInfo}>
          <Text style={[spreadStyles.spreadVal, { color: spreadColor }]}>
            {spread.toFixed(1)} pts
          </Text>
          <Text style={[spreadStyles.spreadPct, { color: spreadColor }]}>
            ({spreadPct.toFixed(3)}%)
          </Text>
          {isWide && (
            <View style={spreadStyles.wideBadge}>
              <Text style={spreadStyles.wideText}>WIDE</Text>
            </View>
          )}
        </View>
      </View>

      {/* Ask side */}
      <View style={[spreadStyles.side, { alignItems: 'flex-end' }]}>
        <Text style={[spreadStyles.price, { color: COLORS.buy }]}>{ask.toFixed(2)}</Text>
        <Text style={spreadStyles.sideLabel}>ASK</Text>
      </View>
    </View>
  );
}

const spreadStyles = StyleSheet.create({
  container:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginTop: SPACING.xs },
  side:       { width: 72 },
  price:      { ...TEXT.numericSM },
  sideLabel:  { ...TEXT.labelSM, color: COLORS.textDim, marginTop: 2 },
  barWrap:    { flex: 1, gap: 4 },
  barTrack:   { flexDirection: 'row', height: 8, borderRadius: RADIUS.full, overflow: 'hidden' },
  bidFill:    { backgroundColor: COLORS.sell + '66' },
  spreadGap:  { backgroundColor: COLORS.background },
  askFill:    { backgroundColor: COLORS.buy + '66' },
  spreadInfo: { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  spreadVal:  { ...TEXT.numericXS, fontWeight: '700' },
  spreadPct:  { ...TEXT.captionSM },
  wideBadge:  { backgroundColor: COLORS.warningDim, paddingHorizontal: 5, paddingVertical: 1, borderRadius: RADIUS.xs, borderWidth: 1, borderColor: COLORS.warning + '44' },
  wideText:   { ...TEXT.captionSM, color: COLORS.warning, fontSize: 9 },
});

// ── Position row ──────────────────────────────────────────────────────────────

function PositionRow({ position, onPress, onClose }: {
  position: Position; onPress: () => void; onClose: () => void;
}) {
  const pnlC = pnlColor(position.unrealized_pnl);
  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.8}>
      <Card style={rowStyles.card}>
        <View style={rowStyles.top}>
          <View>
            <Text style={rowStyles.symbol}>{position.symbol}</Text>
            <Text style={[rowStyles.side, { color: sideColor(position.side) }]}>
              {position.side.toUpperCase()} · {position.quantity} lots
            </Text>
          </View>
          <View style={rowStyles.right}>
            <Text style={[rowStyles.pnl, { color: pnlC }]}>{formatPnl(position.unrealized_pnl)}</Text>
            <Text style={[rowStyles.pnlPct, { color: pnlC }]}>{formatPct(position.unrealized_pnl_pct)}</Text>
          </View>
        </View>
        <View style={rowStyles.bottom}>
          <Text style={rowStyles.meta}>Entry {position.entry_price.toFixed(2)}</Text>
          <Text style={rowStyles.meta}>Current {position.current_price.toFixed(2)}</Text>
          {position.stop_loss && (
            <Text style={[rowStyles.meta, { color: COLORS.loss }]}>SL {position.stop_loss.toFixed(2)}</Text>
          )}
          {position.take_profit && (
            <Text style={[rowStyles.meta, { color: COLORS.profit }]}>TP {position.take_profit.toFixed(2)}</Text>
          )}
          <TouchableOpacity style={rowStyles.closeBtn} onPress={onClose}>
            <Text style={rowStyles.closeBtnText}>CLOSE</Text>
          </TouchableOpacity>
        </View>
      </Card>
    </TouchableOpacity>
  );
}

// ── Order row ─────────────────────────────────────────────────────────────────

function OrderRow({ order, onPress, onCancel }: {
  order: Order; onPress: () => void; onCancel: () => void;
}) {
  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.8}>
      <Card style={rowStyles.card}>
        <View style={rowStyles.top}>
          <View>
            <Text style={rowStyles.symbol}>{order.symbol}</Text>
            <Text style={[rowStyles.side, { color: sideColor(order.side) }]}>
              {order.side.toUpperCase()} · {order.quantity} lots · {order.type.toUpperCase()}
            </Text>
          </View>
          <View style={rowStyles.right}>
            <View style={[rowStyles.statusBadge, {
              backgroundColor: order.status === 'open' ? COLORS.accentGlow : COLORS.surfaceAlt,
              borderColor: order.status === 'open' ? COLORS.accent + '55' : COLORS.border,
            }]}>
              <Text style={[rowStyles.statusText, {
                color: order.status === 'open' ? COLORS.accent : COLORS.textMuted,
              }]}>
                {order.status.toUpperCase()}
              </Text>
            </View>
            {order.price && <Text style={rowStyles.orderPrice}>@ {order.price.toFixed(2)}</Text>}
          </View>
        </View>
        <View style={rowStyles.bottom}>
          <Text style={rowStyles.meta}>{formatDateTime(order.created_at)}</Text>
          <TouchableOpacity style={rowStyles.cancelBtn} onPress={onCancel}>
            <Text style={rowStyles.cancelBtnText}>CANCEL</Text>
          </TouchableOpacity>
        </View>
      </Card>
    </TouchableOpacity>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ message, icon }: { message: string; icon: string }) {
  return (
    <View style={emptyStyles.container}>
      <Ionicons name={icon as any} size={32} color={COLORS.textDim} />
      <Text style={emptyStyles.text}>{message}</Text>
    </View>
  );
}

const emptyStyles = StyleSheet.create({
  container: { alignItems: 'center', paddingVertical: SPACING.xl, gap: SPACING.sm },
  text:      { ...TEXT.body, color: COLORS.textMuted },
});

const rowStyles = StyleSheet.create({
  card:         { padding: SPACING.sm, gap: SPACING.sm },
  top:          { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  symbol:       { ...TEXT.h4, color: COLORS.text },
  side:         { ...TEXT.bodySM, fontWeight: '600', marginTop: 2 },
  right:        { alignItems: 'flex-end', gap: 3 },
  pnl:          { ...TEXT.numericMD },
  pnlPct:       { ...TEXT.numericXS },
  bottom:       { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, flexWrap: 'wrap' },
  meta:         { ...TEXT.caption, color: COLORS.textMuted },
  statusBadge:  { paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm, borderWidth: 1 },
  statusText:   { ...TEXT.labelSM, fontSize: 10 },
  orderPrice:   { ...TEXT.numericXS, color: COLORS.textSecondary },
  closeBtn:     { marginLeft: 'auto', backgroundColor: COLORS.sell, paddingHorizontal: SPACING.md, paddingVertical: 4, borderRadius: RADIUS.sm },
  closeBtnText: { color: COLORS.white, fontWeight: '800', fontSize: 11, letterSpacing: 1 },
  cancelBtn:    { marginLeft: 'auto', backgroundColor: COLORS.surfaceAlt, paddingHorizontal: SPACING.md, paddingVertical: 4, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border },
  cancelBtnText:{ color: COLORS.textMuted, fontWeight: '700', fontSize: 11, letterSpacing: 1 },
});

const styles = StyleSheet.create({
  safe:               { flex: 1, backgroundColor: COLORS.background },
  symbolBar:          {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: COLORS.surface,
    borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  symbolBarContent:   { paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm, gap: SPACING.sm },
  symbolChip:         {
    paddingHorizontal: SPACING.md, paddingVertical: 6,
    borderRadius: RADIUS.full, borderWidth: 1, borderColor: COLORS.border,
    alignItems: 'center',
  },
  symbolChipActive:   { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  symbolChipText:     { ...TEXT.bodySM, color: COLORS.textMuted, fontWeight: '600' },
  symbolChipTextActive: { color: COLORS.black, fontWeight: '800' },
  symbolChipChange:   { ...TEXT.captionSM, marginTop: 1 },
  watchlistBtn:       {
    paddingHorizontal: SPACING.md, height: 52,
    alignItems: 'center', justifyContent: 'center',
    borderLeftWidth: 1, borderLeftColor: COLORS.border,
  },
  scroll:             { flex: 1 },
  content:            { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  spreadCard:         { gap: SPACING.sm },
  cardLabel:          { ...TEXT.label, color: COLORS.textMuted },
  posSummary:         { gap: SPACING.sm },
  posSummaryHeader:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  posSummaryPnl:      { ...TEXT.numericMD, fontWeight: '700' },
  posSummaryStats:    { flexDirection: 'row', justifyContent: 'space-around' },
  posSummaryStat:     { alignItems: 'center' },
  statLabel:          { ...TEXT.labelSM, color: COLORS.textDim },
  statValue:          { ...TEXT.numericSM, marginTop: 3 },
  tabs:               {
    flexDirection: 'row', backgroundColor: COLORS.surface,
    borderRadius: RADIUS.md, padding: 4,
    borderWidth: 1, borderColor: COLORS.border,
  },
  tab:                { flex: 1, paddingVertical: SPACING.sm, alignItems: 'center', borderRadius: RADIUS.sm - 2 },
  tabActive:          { backgroundColor: COLORS.accent },
  tabText:            { ...TEXT.bodySM, color: COLORS.textMuted, fontWeight: '600' },
  tabTextActive:      { color: COLORS.black, fontWeight: '800' },
  list:               { gap: SPACING.sm },
});
