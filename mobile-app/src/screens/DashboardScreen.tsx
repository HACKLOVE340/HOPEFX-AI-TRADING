// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/DashboardScreen.tsx
 * ============================
 * Institutional-grade main dashboard.
 * Live XAUUSD ticker → equity curve → risk summary → microstructure → sentiment → positions.
 */

import React, { useEffect, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';

import { useAuthStore }    from '../store/authStore';
import { useTradingStore } from '../store/tradingStore';
import { useLivePrice }    from '../hooks/useLivePrice';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import { usePerformance }  from '../hooks/usePerformance';

import { LiveTicker }        from '../components/LiveTicker';
import { EquityCurve }       from '../components/EquityCurve';
import { MicrostructureBar } from '../components/MicrostructureBar';
import { SentimentMeter }    from '../components/SentimentMeter';
import { KillSwitchBanner }  from '../components/KillSwitchBanner';
import { ConnectionStatus }  from '../components/ConnectionStatus';
import { Card }              from '../components/Card';
import { LoadingSpinner }    from '../components/LoadingSpinner';

import { COLORS, SPACING, RADIUS, TEXT, SHADOW, pnlColor } from '../utils/theme';
import { formatCurrency, formatPnl, formatPct, formatRelativeTime } from '../utils/formatters';
import { TradingStackParamList } from '../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

export function DashboardScreen() {
  const user       = useAuthStore((s) => s.user);
  const {
    account, positions, signals, riskMetrics, sentiment,
    microstructure, wsStatus,
    fetchAccount, fetchPositions, fetchSignals,
    fetchRiskMetrics, fetchSentiment,
    subscribeToLive, isLoading,
  } = useTradingStore();

  const xauQuote = useLivePrice('XAUUSD');
  const navigation = useNavigation<Nav>();
  const { summary, trades } = usePerformance('30d');

  // Initial load
  useEffect(() => {
    fetchAccount();
    fetchPositions();
    fetchSignals('XAUUSD');
    fetchRiskMetrics();
    fetchSentiment('XAUUSD');
    const unsub = subscribeToLive();
    return unsub;
  }, []);

  useRefreshOnFocus(() => {
    fetchAccount();
    fetchPositions();
    fetchRiskMetrics();
  });

  const handleRefresh = useCallback(() => {
    fetchAccount();
    fetchPositions();
    fetchSignals('XAUUSD');
    fetchRiskMetrics();
    fetchSentiment('XAUUSD');
  }, []);

  const handleBuy  = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    navigation.navigate('PlaceOrder', { symbol: 'XAUUSD', side: 'buy' });
  };
  const handleSell = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    navigation.navigate('PlaceOrder', { symbol: 'XAUUSD', side: 'sell' });
  };

  const latestSignal = signals[0] ?? null;
  const totalUnrealizedPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const xauMicro = microstructure['XAUUSD'] ?? null;

  // Build equity curve from trade history
  const equityCurveData = trades.reduce<{ value: number }[]>((acc, t) => {
    const prev = acc.length > 0 ? acc[acc.length - 1].value : account?.balance ?? 10_000;
    acc.push({ value: prev + t.pnl });
    return acc;
  }, account ? [{ value: account.balance }] : []);

  if (isLoading && !account && !xauQuote) {
    return <LoadingSpinner message="Connecting to markets…" />;
  }

  return (
    <SafeAreaView style={styles.safe}>
      {/* ── Top bar ── */}
      <View style={styles.topBar}>
        <View>
          <Text style={styles.greeting}>
            {getTimeOfDay()}, {user?.username ?? 'Trader'}
          </Text>
          <Text style={styles.date}>{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</Text>
        </View>
        <View style={styles.topRight}>
          <ConnectionStatus status={wsStatus} />
          <TouchableOpacity
            style={styles.notifBtn}
            onPress={() => (navigation as any).navigate('Notifications')}
          >
            <Ionicons name="notifications-outline" size={22} color={COLORS.textSecondary} />
          </TouchableOpacity>
        </View>
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
        {/* Kill switch banner */}
        {riskMetrics?.kill_switch_active && (
          <KillSwitchBanner
            reason={riskMetrics.kill_switch_reason}
            triggeredAt={riskMetrics.kill_switch_triggered_at}
          />
        )}

        {/* ── Account equity card ── */}
        <Card elevated style={styles.accountCard}>
          <Text style={styles.cardLabel}>ACCOUNT EQUITY</Text>
          <Text style={styles.equityValue}>
            {account ? formatCurrency(account.equity) : '—'}
          </Text>
          <View style={styles.accountStats}>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>BALANCE</Text>
              <Text style={styles.statValue}>{account ? formatCurrency(account.balance) : '—'}</Text>
            </View>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>DAILY P&L</Text>
              <Text style={[styles.statValue, { color: pnlColor(account?.daily_pnl ?? 0) }]}>
                {account ? formatPnl(account.daily_pnl) : '—'}
              </Text>
            </View>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>MARGIN</Text>
              <Text style={styles.statValue}>
                {account ? formatPct((account.margin_used / account.equity) * 100) : '—'}
              </Text>
            </View>
            <View style={styles.accountStat}>
              <Text style={styles.statLabel}>OPEN P&L</Text>
              <Text style={[styles.statValue, { color: pnlColor(totalUnrealizedPnl) }]}>
                {formatPnl(totalUnrealizedPnl)}
              </Text>
            </View>
          </View>
        </Card>

        {/* ── Live XAUUSD ticker ── */}
        <LiveTicker
          quote={xauQuote}
          symbol="XAU/USD"
          onBuy={handleBuy}
          onSell={handleSell}
        />

        {/* ── Equity curve ── */}
        {equityCurveData.length >= 2 && (
          <EquityCurve
            data={equityCurveData}
            sharpeRatio={summary.sharpe_ratio}
            sortinoRatio={summary.sortino_ratio}
            maxDrawdown={summary.max_drawdown_pct}
            showDrawdown
          />
        )}

        {/* ── Risk summary strip ── */}
        {riskMetrics && (
          <Card style={styles.riskStrip}>
            <View style={styles.riskStripHeader}>
              <Text style={styles.cardLabel}>RISK SNAPSHOT</Text>
              <TouchableOpacity onPress={() => (navigation as any).navigate('Risk')}>
                <Text style={styles.viewAll}>Full Report →</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.riskStats}>
              <RiskStat
                label="CVaR 95"
                value={formatCurrency(riskMetrics.cvar_95)}
                color={COLORS.loss}
              />
              <RiskStat
                label="DRAWDOWN"
                value={`${riskMetrics.current_drawdown.toFixed(1)}%`}
                color={riskMetrics.current_drawdown < -5 ? COLORS.loss : COLORS.warning}
              />
              <RiskStat
                label="RISK UTIL"
                value={`${(riskMetrics.risk_utilization * 100).toFixed(0)}%`}
                color={riskMetrics.risk_utilization > 0.8 ? COLORS.danger : COLORS.accent}
              />
              <RiskStat
                label="DATA QUAL"
                value={`${(riskMetrics.data_quality_score * 100).toFixed(0)}%`}
                color={riskMetrics.data_quality_score >= 0.8 ? COLORS.profit : COLORS.warning}
              />
            </View>
          </Card>
        )}

        {/* ── Microstructure ── */}
        <MicrostructureBar micro={xauMicro} symbol="XAUUSD" />

        {/* ── Latest signal ── */}
        {latestSignal && (
          <Card style={styles.signalPreview} accent>
            <View style={styles.signalPreviewHeader}>
              <Text style={styles.cardLabel}>LATEST AI SIGNAL</Text>
              <Text style={styles.signalTime}>{formatRelativeTime(latestSignal.generated_at)}</Text>
            </View>
            <View style={styles.signalPreviewRow}>
              <View style={[styles.signalDir, {
                backgroundColor: latestSignal.direction === 'long' ? COLORS.buyDim : COLORS.sellDim,
                borderColor: latestSignal.direction === 'long' ? COLORS.buy + '55' : COLORS.sell + '55',
              }]}>
                <Ionicons
                  name={latestSignal.direction === 'long' ? 'trending-up' : 'trending-down'}
                  size={18}
                  color={latestSignal.direction === 'long' ? COLORS.buy : COLORS.sell}
                />
                <Text style={[styles.signalDirText, {
                  color: latestSignal.direction === 'long' ? COLORS.buy : COLORS.sell
                }]}>
                  {latestSignal.direction.toUpperCase()}
                </Text>
              </View>
              <View style={styles.signalPreviewStats}>
                <Text style={styles.signalStatLine}>
                  <Text style={styles.signalStatLabel}>Confidence  </Text>
                  <Text style={{ color: COLORS.accent }}>{(latestSignal.confidence * 100).toFixed(0)}%</Text>
                </Text>
                <Text style={styles.signalStatLine}>
                  <Text style={styles.signalStatLabel}>Entry       </Text>
                  <Text style={styles.signalStatVal}>{latestSignal.entry_price.toFixed(2)}</Text>
                </Text>
                <Text style={styles.signalStatLine}>
                  <Text style={styles.signalStatLabel}>R:R         </Text>
                  <Text style={{ color: COLORS.profit }}>{latestSignal.risk_reward.toFixed(1)}x</Text>
                </Text>
              </View>
              <TouchableOpacity
                style={styles.signalViewBtn}
                onPress={() => (navigation as any).navigate('Signals')}
              >
                <Text style={styles.signalViewText}>VIEW</Text>
                <Ionicons name="chevron-forward" size={14} color={COLORS.accent} />
              </TouchableOpacity>
            </View>
          </Card>
        )}

        {/* ── Sentiment ── */}
        <SentimentMeter sentiment={sentiment} maxHeadlines={2} />

        {/* ── Open positions ── */}
        {positions.length > 0 && (
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>OPEN POSITIONS ({positions.length})</Text>
              <Text style={[styles.totalPnl, { color: pnlColor(totalUnrealizedPnl) }]}>
                {formatPnl(totalUnrealizedPnl)}
              </Text>
            </View>
            {positions.map((pos) => (
              <TouchableOpacity
                key={pos.id}
                onPress={() => navigation.navigate('PositionDetail', { positionId: pos.id })}
                activeOpacity={0.8}
              >
                <Card style={styles.posCard}>
                  <View style={styles.posRow}>
                    <View>
                      <Text style={styles.posSymbol}>{pos.symbol}</Text>
                      <Text style={[styles.posSide, { color: pos.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
                        {pos.side.toUpperCase()} · {pos.quantity} lots
                      </Text>
                      <Text style={styles.posEntry}>Entry {pos.entry_price.toFixed(2)}</Text>
                    </View>
                    <View style={styles.posRight}>
                      <Text style={[styles.posPnl, { color: pnlColor(pos.unrealized_pnl) }]}>
                        {formatPnl(pos.unrealized_pnl)}
                      </Text>
                      <Text style={[styles.posPnlPct, { color: pnlColor(pos.unrealized_pnl_pct) }]}>
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

function RiskStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={riskStatStyles.item}>
      <Text style={riskStatStyles.label}>{label}</Text>
      <Text style={[riskStatStyles.value, { color }]}>{value}</Text>
    </View>
  );
}

const riskStatStyles = StyleSheet.create({
  item:  { alignItems: 'center', flex: 1 },
  label: { ...TEXT.labelSM, color: COLORS.textDim },
  value: { ...TEXT.numericXS, fontWeight: '700', marginTop: 3 },
});

function getTimeOfDay(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Morning';
  if (h < 17) return 'Afternoon';
  return 'Evening';
}

const styles = StyleSheet.create({
  safe:               { flex: 1, backgroundColor: COLORS.background },
  topBar:             {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm,
    borderBottomWidth: 1, borderBottomColor: COLORS.border,
    backgroundColor: COLORS.surface,
  },
  greeting:           { ...TEXT.h4, color: COLORS.text },
  date:               { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  topRight:           { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  notifBtn:           { padding: 4 },
  scroll:             { flex: 1 },
  content:            { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  accountCard:        { gap: SPACING.sm },
  cardLabel:          { ...TEXT.label, color: COLORS.textMuted },
  equityValue:        { ...TEXT.displayLG, color: COLORS.text },
  accountStats:       { flexDirection: 'row', justifyContent: 'space-between', marginTop: SPACING.xs },
  accountStat:        { alignItems: 'center' },
  statLabel:          { ...TEXT.labelSM, color: COLORS.textDim },
  statValue:          { ...TEXT.numericSM, marginTop: 3 },
  riskStrip:          { gap: SPACING.sm },
  riskStripHeader:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  viewAll:            { ...TEXT.bodySM, color: COLORS.accent },
  riskStats:          { flexDirection: 'row', justifyContent: 'space-between' },
  signalPreview:      { gap: SPACING.sm },
  signalPreviewHeader:{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  signalTime:         { ...TEXT.caption, color: COLORS.textMuted },
  signalPreviewRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  signalDir:          {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: SPACING.sm, paddingVertical: SPACING.sm,
    borderRadius: RADIUS.md, borderWidth: 1,
  },
  signalDirText:      { ...TEXT.label, fontSize: 12 },
  signalPreviewStats: { flex: 1, gap: 4 },
  signalStatLine:     { flexDirection: 'row' },
  signalStatLabel:    { ...TEXT.caption, color: COLORS.textMuted, width: 72 },
  signalStatVal:      { ...TEXT.numericXS, color: COLORS.text },
  signalViewBtn:      { flexDirection: 'row', alignItems: 'center', gap: 2 },
  signalViewText:     { ...TEXT.label, color: COLORS.accent },
  section:            { gap: SPACING.sm },
  sectionHeader:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sectionTitle:       { ...TEXT.label, color: COLORS.textMuted },
  totalPnl:           { ...TEXT.numericSM, fontWeight: '700' },
  posCard:            { padding: SPACING.sm },
  posRow:             { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  posSymbol:          { ...TEXT.h4, color: COLORS.text },
  posSide:            { ...TEXT.bodySM, fontWeight: '600', marginTop: 2 },
  posEntry:           { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  posRight:           { alignItems: 'flex-end' },
  posPnl:             { ...TEXT.numericMD },
  posPnlPct:          { ...TEXT.numericXS, marginTop: 3 },
});
