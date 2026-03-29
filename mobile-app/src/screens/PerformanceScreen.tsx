// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/PerformanceScreen.tsx
 * =============================
 * Detailed performance analytics: equity curve, risk metrics, trade history.
 * Accessible from the Portfolio tab via a "View Performance" button.
 */

import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import { usePerformance, PerformancePeriod } from '../hooks/usePerformance';
import { Card } from '../components/Card';
import { ChartCard } from '../components/ChartCard';
import { MetricGrid, Metric } from '../components/MetricGrid';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { ErrorBanner } from '../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import {
  formatCurrency, formatPct, formatPnl,
  formatDateTime, confidenceLabel,
} from '../utils/formatters';

const PERIODS: { label: string; value: PerformancePeriod }[] = [
  { label: '7D',  value: '7d' },
  { label: '30D', value: '30d' },
  { label: '90D', value: '90d' },
  { label: '1Y',  value: '1y' },
  { label: 'All', value: 'all' },
];

const DATA_SOURCE_LABELS: Record<string, string> = {
  paper_oanda:      'Paper · OANDA',
  paper_simulation: 'Paper · Simulation',
  live:             'Live',
  seeded:           'Test Data',
};

export function PerformanceScreen() {
  const [period, setPeriod] = useState<PerformancePeriod>('30d');
  const { summary, trades, isLoading, error, refresh } = usePerformance(period);

  useRefreshOnFocus(refresh);

  // Build equity curve from trade history
  const equityCurve = trades.reduce<number[]>((acc, t) => {
    const prev = acc.length > 0 ? acc[acc.length - 1] : 10_000;
    acc.push(prev + t.pnl);
    return acc;
  }, [10_000]);

  const riskMetrics: Metric[] = [
    {
      label: 'Sharpe Ratio',
      value: summary.sharpe_ratio != null ? summary.sharpe_ratio.toFixed(2) : '—',
      color: (summary.sharpe_ratio ?? 0) > 1 ? COLORS.profit : COLORS.textMuted,
    },
    {
      label: 'Max Drawdown',
      value: `${summary.max_drawdown_pct.toFixed(1)}%`,
      color: summary.max_drawdown_pct < -10 ? COLORS.loss : COLORS.text,
    },
    {
      label: 'Profit Factor',
      value: summary.profit_factor != null ? summary.profit_factor.toFixed(2) : '—',
      color: (summary.profit_factor ?? 0) > 1 ? COLORS.profit : COLORS.loss,
    },
    {
      label: 'Avg Hold',
      value: `${summary.avg_hold_hours.toFixed(1)}h`,
    },
    {
      label: 'Best Trade',
      value: formatPnl(summary.best_trade),
      color: COLORS.profit,
    },
    {
      label: 'Worst Trade',
      value: formatPnl(summary.worst_trade),
      color: COLORS.loss,
    },
  ];

  const tradeMetrics: Metric[] = [
    { label: 'Total Trades', value: String(summary.total_trades) },
    { label: 'Win Rate',     value: `${summary.win_rate.toFixed(1)}%`, color: summary.win_rate >= 50 ? COLORS.profit : COLORS.loss },
    { label: 'Avg Win',      value: formatPnl(summary.avg_win),  color: COLORS.profit },
    { label: 'Avg Loss',     value: formatPnl(summary.avg_loss), color: COLORS.loss },
  ];

  if (isLoading && trades.length === 0) {
    return <LoadingSpinner message="Loading performance…" />;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={isLoading} onRefresh={refresh} tintColor={COLORS.accent} />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.pageTitle}>Performance</Text>
          <View style={styles.sourceBadge}>
            <Text style={styles.sourceText}>
              {DATA_SOURCE_LABELS[summary.data_source] ?? summary.data_source}
            </Text>
          </View>
        </View>

        {error && <ErrorBanner message={error} />}

        {/* Period selector */}
        <View style={styles.periodRow}>
          {PERIODS.map((p) => (
            <TouchableOpacity
              key={p.value}
              style={[styles.periodBtn, period === p.value && styles.periodBtnActive]}
              onPress={() => setPeriod(p.value)}
            >
              <Text style={[styles.periodText, period === p.value && styles.periodTextActive]}>
                {p.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Equity curve */}
        <ChartCard
          title="Equity Curve"
          value={equityCurve[equityCurve.length - 1] ?? 10_000}
          changePct={summary.total_pnl_pct}
          dataPoints={equityCurve}
        />

        {/* P&L summary */}
        <Card style={styles.pnlCard} elevated>
          <Text style={styles.sectionTitle}>P&L Summary</Text>
          <View style={styles.pnlRow}>
            <View style={styles.pnlStat}>
              <Text style={styles.pnlLabel}>Total P&L</Text>
              <Text style={[styles.pnlValue, { color: summary.total_pnl >= 0 ? COLORS.profit : COLORS.loss }]}>
                {formatPnl(summary.total_pnl)}
              </Text>
            </View>
            <View style={styles.pnlStat}>
              <Text style={styles.pnlLabel}>Return</Text>
              <Text style={[styles.pnlValue, { color: summary.total_pnl_pct >= 0 ? COLORS.profit : COLORS.loss }]}>
                {formatPct(summary.total_pnl_pct)}
              </Text>
            </View>
          </View>
        </Card>

        {/* Trade metrics */}
        <Card>
          <Text style={styles.sectionTitle}>Trade Statistics</Text>
          <MetricGrid metrics={tradeMetrics} columns={2} />
        </Card>

        {/* Risk metrics */}
        <Card>
          <Text style={styles.sectionTitle}>Risk Metrics</Text>
          <MetricGrid metrics={riskMetrics} columns={3} />
        </Card>

        {/* Trade history */}
        <Text style={styles.sectionTitle}>Trade History</Text>
        {trades.length === 0 ? (
          <Text style={styles.emptyText}>No trades in this period.</Text>
        ) : (
          trades.slice(0, 30).map((trade) => (
            <Card key={trade.id} style={styles.tradeCard}>
              <View style={styles.tradeRow}>
                <View style={styles.tradeLeft}>
                  <Text style={styles.tradeSymbol}>{trade.symbol}</Text>
                  <Text style={[styles.tradeSide, { color: trade.side === 'buy' ? COLORS.buy : COLORS.sell }]}>
                    {trade.side.toUpperCase()} · {trade.quantity} lots
                  </Text>
                  <Text style={styles.tradeMeta}>{formatDateTime(trade.closed_at)}</Text>
                </View>
                <View style={styles.tradeRight}>
                  <Text style={[styles.tradePnl, { color: trade.pnl >= 0 ? COLORS.profit : COLORS.loss }]}>
                    {formatPnl(trade.pnl)}
                  </Text>
                  <Text style={styles.tradePrices}>
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

const styles = StyleSheet.create({
  safe:            { flex: 1, backgroundColor: COLORS.background },
  content:         { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  header:          { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  pageTitle:       { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  sourceBadge:     { backgroundColor: COLORS.accent + '22', paddingHorizontal: SPACING.sm, paddingVertical: 3, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.accent + '55' },
  sourceText:      { color: COLORS.accent, fontSize: 11, fontWeight: '700' },
  periodRow:       { flexDirection: 'row', gap: SPACING.xs },
  periodBtn:       { flex: 1, paddingVertical: SPACING.sm, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, alignItems: 'center' },
  periodBtnActive: { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  periodText:      { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  periodTextActive:{ color: COLORS.white },
  pnlCard:         { gap: SPACING.sm },
  pnlRow:          { flexDirection: 'row', justifyContent: 'space-around' },
  pnlStat:         { alignItems: 'center' },
  pnlLabel:        { color: COLORS.textMuted, fontSize: 12, marginBottom: 4 },
  pnlValue:        { fontSize: 22, fontWeight: '800', fontFamily: 'Courier' },
  sectionTitle:    { color: COLORS.text, fontSize: 16, fontWeight: '700', marginBottom: SPACING.sm },
  emptyText:       { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl },
  tradeCard:       { padding: SPACING.sm },
  tradeRow:        { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  tradeLeft:       { flex: 1 },
  tradeRight:      { alignItems: 'flex-end' },
  tradeSymbol:     { color: COLORS.text, fontSize: 14, fontWeight: '700' },
  tradeSide:       { fontSize: 12, fontWeight: '600', marginTop: 2 },
  tradeMeta:       { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
  tradePnl:        { fontSize: 15, fontWeight: '700', fontFamily: 'Courier' },
  tradePrices:     { color: COLORS.textMuted, fontSize: 11, marginTop: 2 },
});
