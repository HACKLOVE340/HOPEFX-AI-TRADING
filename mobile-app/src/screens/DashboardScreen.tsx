// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/DashboardScreen.tsx
 * ===========================
 * Main dashboard: account summary, live XAUUSD price, open positions,
 * latest AI signal, and quick-trade buttons.
 */

import React, { useEffect } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useAuthStore } from '../store/authStore';
import { useTradingStore } from '../store/tradingStore';
import { useLivePrice } from '../hooks/useLivePrice';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import { Card } from '../components/Card';
import { SignalBadge } from '../components/SignalBadge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { formatCurrency, formatPct, formatPnl, formatRelativeTime } from '../utils/formatters';
import { TradingStackParamList } from '../types';

type TradingNav = NativeStackNavigationProp<TradingStackParamList>;

export function DashboardScreen() {
  const user = useAuthStore((s) => s.user);
  const {
    account, positions, signals,
    fetchAccount, fetchPositions, fetchSignals,
    subscribeToLive, isLoading,
  } = useTradingStore();

  const xauPrice = useLivePrice('XAUUSD');
  const navigation = useNavigation<TradingNav>();

  // Initial data load
  useEffect(() => {
    fetchAccount();
    fetchPositions();
    fetchSignals('XAUUSD');
    const unsub = subscribeToLive();
    return unsub;
  }, []);

  // Refresh on tab focus
  useRefreshOnFocus(() => {
    fetchAccount();
    fetchPositions();
  });

  const latestSignal = signals[0] ?? null;
  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);

  if (isLoading && !account) return <LoadingSpinner message="Loading dashboard…" />;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={() => { fetchAccount(); fetchPositions(); fetchSignals('XAUUSD'); }}
            tintColor={COLORS.accent}
          />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <View>
            <Text style={styles.greeting}>Good {getTimeOfDay()},</Text>
            <Text style={styles.username}>{user?.username ?? 'Trader'}</Text>
          </View>
          <View style={styles.headerRight}>
            <View style={[styles.dot, { backgroundColor: COLORS.accent }]} />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
        </View>

        {/* Account Summary */}
        <Card style={styles.accountCard} elevated>
          <Text style={styles.cardLabel}>Account Equity</Text>
          <Text style={styles.equityValue}>
            {account ? formatCurrency(account.equity) : '—'}
          </Text>
          <View style={styles.accountRow}>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>Balance</Text>
              <Text style={styles.statValue}>
                {account ? formatCurrency(account.balance) : '—'}
              </Text>
            </View>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>Daily P&L</Text>
              <Text style={[
                styles.statValue,
                { color: (account?.daily_pnl ?? 0) >= 0 ? COLORS.profit : COLORS.loss }
              ]}>
                {account ? formatPnl(account.daily_pnl) : '—'}
              </Text>
            </View>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>Margin Used</Text>
              <Text style={styles.statValue}>
                {account ? formatCurrency(account.margin_used) : '—'}
              </Text>
            </View>
          </View>
        </Card>

        {/* XAUUSD Live Price */}
        <Card style={styles.priceCard}>
          <View style={styles.priceHeader}>
            <Text style={styles.symbol}>XAU/USD</Text>
            <Text style={styles.goldLabel}>🥇 Gold</Text>
          </View>
          {xauPrice ? (
            <>
              <Text style={styles.midPrice}>{xauPrice.mid.toFixed(2)}</Text>
              <View style={styles.bidAskRow}>
                <View>
                  <Text style={styles.bidAskLabel}>BID</Text>
                  <Text style={[styles.bidAskValue, { color: COLORS.sell }]}>
                    {xauPrice.bid.toFixed(2)}
                  </Text>
                </View>
                <View style={styles.spreadBox}>
                  <Text style={styles.spreadLabel}>SPREAD</Text>
                  <Text style={styles.spreadValue}>{xauPrice.spread.toFixed(1)}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={styles.bidAskLabel}>ASK</Text>
                  <Text style={[styles.bidAskValue, { color: COLORS.buy }]}>
                    {xauPrice.ask.toFixed(2)}
                  </Text>
                </View>
              </View>
              <Text style={[
                styles.changePct,
                { color: xauPrice.change_pct >= 0 ? COLORS.profit : COLORS.loss }
              ]}>
                {formatPct(xauPrice.change_pct)} today
              </Text>
            </>
          ) : (
            <Text style={styles.noData}>Connecting to price feed…</Text>
          )}

          {/* Quick trade buttons */}
          <View style={styles.quickTrade}>
            <TouchableOpacity
              style={[styles.tradeBtn, { backgroundColor: COLORS.buy }]}
              onPress={() => navigation.navigate('PlaceOrder', { symbol: 'XAUUSD', side: 'buy' })}
            >
              <Text style={styles.tradeBtnText}>▲ BUY</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tradeBtn, { backgroundColor: COLORS.sell }]}
              onPress={() => navigation.navigate('PlaceOrder', { symbol: 'XAUUSD', side: 'sell' })}
            >
              <Text style={styles.tradeBtnText}>▼ SELL</Text>
            </TouchableOpacity>
          </View>
        </Card>

        {/* Latest AI Signal */}
        {latestSignal && (
          <Card style={styles.signalCard}>
            <View style={styles.signalHeader}>
              <Text style={styles.sectionTitle}>Latest AI Signal</Text>
              <Text style={styles.signalTime}>{formatRelativeTime(latestSignal.generated_at)}</Text>
            </View>
            <SignalBadge direction={latestSignal.direction} confidence={latestSignal.confidence} />
            <View style={styles.signalDetails}>
              <View style={styles.signalStat}>
                <Text style={styles.statLabel}>Entry</Text>
                <Text style={styles.statValue}>{latestSignal.entry_price.toFixed(2)}</Text>
              </View>
              <View style={styles.signalStat}>
                <Text style={styles.statLabel}>Stop Loss</Text>
                <Text style={[styles.statValue, { color: COLORS.sell }]}>
                  {latestSignal.stop_loss.toFixed(2)}
                </Text>
              </View>
              <View style={styles.signalStat}>
                <Text style={styles.statLabel}>Take Profit</Text>
                <Text style={[styles.statValue, { color: COLORS.buy }]}>
                  {latestSignal.take_profit.toFixed(2)}
                </Text>
              </View>
              <View style={styles.signalStat}>
                <Text style={styles.statLabel}>R:R</Text>
                <Text style={styles.statValue}>{latestSignal.risk_reward.toFixed(1)}</Text>
              </View>
            </View>
          </Card>
        )}

        {/* Open Positions */}
        {positions.length > 0 && (
          <View style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionTitle}>Open Positions ({positions.length})</Text>
              <Text style={[
                styles.totalPnl,
                { color: totalUnrealizedPnl >= 0 ? COLORS.profit : COLORS.loss }
              ]}>
                {formatPnl(totalUnrealizedPnl)}
              </Text>
            </View>
            {positions.map((pos) => (
              <TouchableOpacity
                key={pos.id}
                onPress={() => navigation.navigate('PositionDetail', { positionId: pos.id })}
              >
                <Card style={styles.positionCard}>
                  <View style={styles.positionRow}>
                    <View>
                      <Text style={styles.posSymbol}>{pos.symbol}</Text>
                      <Text style={[
                        styles.posSide,
                        { color: pos.side === 'buy' ? COLORS.buy : COLORS.sell }
                      ]}>
                        {pos.side.toUpperCase()} {pos.quantity} lots
                      </Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={[
                        styles.posPnl,
                        { color: pos.unrealized_pnl >= 0 ? COLORS.profit : COLORS.loss }
                      ]}>
                        {formatPnl(pos.unrealized_pnl)}
                      </Text>
                      <Text style={styles.posPnlPct}>
                        {formatPct(pos.unrealized_pnl_pct)}
                      </Text>
                    </View>
                  </View>
                </Card>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function getTimeOfDay(): string {
  const h = new Date().getHours();
  if (h < 12) return 'morning';
  if (h < 17) return 'afternoon';
  return 'evening';
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  scroll: { flex: 1 },
  content: { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.sm },
  greeting: { color: COLORS.textMuted, fontSize: 13 },
  username: { color: COLORS.text, fontSize: 20, fontWeight: '700' },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  liveText: { color: COLORS.accent, fontSize: 12, fontWeight: '700' },
  accountCard: { gap: SPACING.sm },
  cardLabel: { color: COLORS.textMuted, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  equityValue: { color: COLORS.text, fontSize: 32, fontWeight: '900', fontFamily: 'Courier' },
  accountRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: SPACING.sm },
  accountStat: { alignItems: 'center' },
  statLabel: { color: COLORS.textMuted, fontSize: 11, marginBottom: 2 },
  statValue: { color: COLORS.text, fontSize: 14, fontWeight: '600' },
  priceCard: { gap: SPACING.sm },
  priceHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  symbol: { color: COLORS.text, fontSize: 18, fontWeight: '700' },
  goldLabel: { color: COLORS.gold, fontSize: 13 },
  midPrice: { color: COLORS.text, fontSize: 36, fontWeight: '900', fontFamily: 'Courier' },
  bidAskRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  bidAskLabel: { color: COLORS.textMuted, fontSize: 11, textTransform: 'uppercase' },
  bidAskValue: { fontSize: 18, fontWeight: '700', fontFamily: 'Courier' },
  spreadBox: { alignItems: 'center' },
  spreadLabel: { color: COLORS.textMuted, fontSize: 11 },
  spreadValue: { color: COLORS.textMuted, fontSize: 14, fontWeight: '600' },
  changePct: { fontSize: 13, fontWeight: '600' },
  noData: { color: COLORS.textMuted, fontSize: 14, textAlign: 'center', paddingVertical: SPACING.md },
  quickTrade: { flexDirection: 'row', gap: SPACING.sm, marginTop: SPACING.sm },
  tradeBtn: { flex: 1, paddingVertical: SPACING.md, borderRadius: RADIUS.md, alignItems: 'center' },
  tradeBtnText: { color: COLORS.white, fontWeight: '800', fontSize: 16, letterSpacing: 1 },
  signalCard: { gap: SPACING.sm },
  signalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  signalTime: { color: COLORS.textMuted, fontSize: 12 },
  signalDetails: { flexDirection: 'row', justifyContent: 'space-between', marginTop: SPACING.sm },
  signalStat: { alignItems: 'center' },
  section: { gap: SPACING.sm },
  sectionHeaderRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sectionTitle: { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  totalPnl: { fontSize: 15, fontWeight: '700' },
  positionCard: { padding: SPACING.sm },
  positionRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  posSymbol: { color: COLORS.text, fontSize: 15, fontWeight: '700' },
  posSide: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  posPnl: { fontSize: 16, fontWeight: '700', fontFamily: 'Courier' },
  posPnlPct: { color: COLORS.textMuted, fontSize: 12, marginTop: 2 },
});
