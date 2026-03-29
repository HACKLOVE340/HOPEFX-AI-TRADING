// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useTradingStore } from '../store/tradingStore';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import { Card } from '../components/Card';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatDateTime } from '../utils/formatters';
import { apiClient } from '../services/apiClient';
import { PortfolioStackParamList } from '../types';

type PortfolioNav = NativeStackNavigationProp<PortfolioStackParamList>;

export function PortfolioScreen() {
  const navigation = useNavigation<PortfolioNav>();
  const { account, trades, fetchAccount, fetchTrades, isLoading } = useTradingStore();
  const [performance, setPerformance] = useState<Record<string, unknown> | null>(null);

  const load = async () => {
    fetchAccount();
    fetchTrades(50);
    try {
      const perf = await apiClient.getPerformance('30d');
      setPerformance(perf);
    } catch { /* non-critical */ }
  };

  useEffect(() => { load(); }, []);
  useRefreshOnFocus(load);

  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const winningTrades = trades.filter((t) => t.pnl > 0);
  const winRate = trades.length > 0 ? (winningTrades.length / trades.length) * 100 : 0;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={isLoading} onRefresh={load} tintColor={COLORS.accent} />}
      >
        <View style={styles.headerRow}>
          <Text style={styles.pageTitle}>Portfolio</Text>
          <TouchableOpacity
            style={styles.perfBtn}
            onPress={() => navigation.navigate('Performance')}
          >
            <Ionicons name="analytics-outline" size={16} color={COLORS.accent} />
            <Text style={styles.perfBtnText}>Analytics</Text>
          </TouchableOpacity>
        </View>

        {/* Account summary */}
        <Card style={styles.summaryCard} elevated>
          <View style={styles.summaryRow}>
            <Stat label="Equity" value={account ? formatCurrency(account.equity) : '—'} />
            <Stat label="Balance" value={account ? formatCurrency(account.balance) : '—'} />
          </View>
          <View style={styles.summaryRow}>
            <Stat label="Daily P&L" value={account ? formatPnl(account.daily_pnl) : '—'} color={(account?.daily_pnl ?? 0) >= 0 ? COLORS.profit : COLORS.loss} />
            <Stat label="Unrealized" value={account ? formatPnl(account.unrealized_pnl) : '—'} color={(account?.unrealized_pnl ?? 0) >= 0 ? COLORS.profit : COLORS.loss} />
          </View>
        </Card>

        {/* Stats */}
        <Card style={styles.statsCard}>
          <Text style={styles.sectionTitle}>30-Day Stats</Text>
          <View style={styles.statsGrid}>
            <Stat label="Total P&L" value={formatPnl(totalPnl)} color={totalPnl >= 0 ? COLORS.profit : COLORS.loss} />
            <Stat label="Win Rate" value={`${winRate.toFixed(1)}%`} />
            <Stat label="Total Trades" value={String(trades.length)} />
            <Stat label="Winning" value={String(winningTrades.length)} color={COLORS.profit} />
          </View>
        </Card>

        {/* Trade history */}
        <Text style={styles.sectionTitle}>Recent Trades</Text>
        {trades.length === 0 ? (
          <Text style={styles.emptyText}>No trades yet.</Text>
        ) : (
          trades.slice(0, 20).map((trade) => (
            <Card key={trade.id} style={styles.tradeCard}>
              <View style={styles.tradeRow}>
                <View>
                  <Text style={styles.tradeSymbol}>{trade.symbol}</Text>
                  <Text style={[styles.tradeSide, { color: trade.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
                    {trade.side.toUpperCase()} · {trade.quantity} lots
                  </Text>
                  <Text style={styles.tradeMeta}>{formatDateTime(trade.closed_at)}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={[styles.tradePnl, { color: trade.pnl >= 0 ? COLORS.profit : COLORS.loss }]}>
                    {formatPnl(trade.pnl)}
                  </Text>
                  <Text style={styles.tradeMeta}>
                    {trade.entry_price.toFixed(2)} → {trade.exit_price.toFixed(2)}
                  </Text>
                </View>
              </View>
            </Card>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={statStyles.container}>
      <Text style={statStyles.label}>{label}</Text>
      <Text style={[statStyles.value, color ? { color } : {}]}>{value}</Text>
    </View>
  );
}

const statStyles = StyleSheet.create({
  container: { alignItems: 'center', flex: 1 },
  label: { color: COLORS.textMuted, fontSize: 11, marginBottom: 2 },
  value: { color: COLORS.text, fontSize: 15, fontWeight: '700', fontFamily: 'Courier' },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  pageTitle: { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  perfBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, padding: SPACING.sm, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.accent },
  perfBtnText: { color: COLORS.accent, fontSize: 13, fontWeight: '700' },
  summaryCard: { gap: SPACING.md },
  summaryRow: { flexDirection: 'row', justifyContent: 'space-around' },
  statsCard: { gap: SPACING.md },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACING.md },
  sectionTitle: { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  emptyText: { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl },
  tradeCard: { padding: SPACING.sm },
  tradeRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  tradeSymbol: { color: COLORS.text, fontSize: 14, fontWeight: '700' },
  tradeSide: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  tradeMeta: { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  tradePnl: { fontSize: 15, fontWeight: '700', fontFamily: 'Courier' },
});
