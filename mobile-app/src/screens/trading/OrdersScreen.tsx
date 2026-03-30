// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useEffect } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useTradingStore } from '../../store/tradingStore';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS, TEXT, pnlColor, sideColor } from '../../utils/theme';
import { formatDateTime, formatPnl } from '../../utils/formatters';
import { TradingStackParamList, Trade } from '../../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

export function OrdersScreen() {
  const navigation = useNavigation<Nav>();
  const { trades, fetchTrades, isLoading } = useTradingStore();

  useEffect(() => { fetchTrades(100); }, []);

  const renderTrade = ({ item }: { item: Trade }) => (
    <Card style={styles.tradeCard}>
      <View style={styles.tradeRow}>
        <View>
          <Text style={styles.symbol}>{item.symbol}</Text>
          <Text style={[styles.side, { color: sideColor(item.side) }]}>
            {item.side.toUpperCase()} · {item.quantity} lots
          </Text>
          <Text style={styles.meta}>{formatDateTime(item.closed_at)}</Text>
        </View>
        <View style={styles.right}>
          <Text style={[styles.pnl, { color: pnlColor(item.pnl) }]}>{formatPnl(item.pnl)}</Text>
          <Text style={styles.exitReason}>{item.exit_reason?.toUpperCase() ?? '—'}</Text>
        </View>
      </View>
    </Card>
  );

  return (
    <SafeAreaView style={styles.safe}>
      <FlatList
        data={trades}
        keyExtractor={(t) => t.id}
        renderItem={renderTrade}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>{isLoading ? 'Loading…' : 'No trade history'}</Text>
          </View>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:       { flex: 1, backgroundColor: COLORS.background },
  content:    { padding: SPACING.md, gap: SPACING.sm, paddingBottom: SPACING.xxl },
  tradeCard:  { padding: SPACING.sm },
  tradeRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  symbol:     { ...TEXT.h4, color: COLORS.text },
  side:       { ...TEXT.bodySM, fontWeight: '600', marginTop: 2 },
  meta:       { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  right:      { alignItems: 'flex-end', gap: 4 },
  pnl:        { ...TEXT.numericMD },
  exitReason: { ...TEXT.captionSM, color: COLORS.textDim },
  empty:      { alignItems: 'center', paddingVertical: SPACING.xxl },
  emptyText:  { ...TEXT.body, color: COLORS.textMuted },
});
