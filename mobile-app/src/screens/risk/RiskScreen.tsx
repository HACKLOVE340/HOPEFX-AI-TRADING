// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/risk/RiskScreen.tsx
 * ============================
 * Full risk management dashboard: CVaR, drawdown, kill switch,
 * position sizing, data quality, macro blackout status.
 */

import React, { useEffect, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { useTradingStore }   from '../../store/tradingStore';
import { useRefreshOnFocus } from '../../hooks/useRefreshOnFocus';
import { RiskGauge }         from '../../components/RiskGauge';
import { KillSwitchBanner }  from '../../components/KillSwitchBanner';
import { Card }              from '../../components/Card';
import { LoadingSpinner }    from '../../components/LoadingSpinner';

import { COLORS, SPACING, RADIUS, TEXT, SHADOW, riskColor } from '../../utils/theme';
import { formatCurrency, formatPct } from '../../utils/formatters';

export function RiskScreen() {
  const { riskMetrics, account, fetchRiskMetrics, fetchAccount, isLoading } = useTradingStore();

  useEffect(() => {
    fetchRiskMetrics();
    fetchAccount();
  }, []);

  useRefreshOnFocus(() => { fetchRiskMetrics(); fetchAccount(); });

  const handleRefresh = useCallback(() => {
    fetchRiskMetrics();
    fetchAccount();
  }, []);

  if (isLoading && !riskMetrics) {
    return <LoadingSpinner message="Loading risk metrics…" />;
  }

  const rm = riskMetrics;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
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
        {/* Page header */}
        <View style={styles.pageHeader}>
          <Text style={styles.pageTitle}>Risk Management</Text>
          {rm && (
            <View style={[styles.statusBadge, {
              backgroundColor: rm.kill_switch_active ? COLORS.killSwitchDim : COLORS.profitDim,
              borderColor: rm.kill_switch_active ? COLORS.danger + '55' : COLORS.profit + '44',
            }]}>
              <View style={[styles.statusDot, {
                backgroundColor: rm.kill_switch_active ? COLORS.danger : COLORS.profit,
              }]} />
              <Text style={[styles.statusText, {
                color: rm.kill_switch_active ? COLORS.danger : COLORS.profit,
              }]}>
                {rm.kill_switch_active ? 'HALTED' : 'ACTIVE'}
              </Text>
            </View>
          )}
        </View>

        {/* Kill switch banner */}
        {rm?.kill_switch_active && (
          <KillSwitchBanner
            reason={rm.kill_switch_reason}
            triggeredAt={rm.kill_switch_triggered_at}
          />
        )}

        {/* ── Gauge row ── */}
        {rm && (
          <Card elevated style={styles.gaugeCard}>
            <Text style={styles.cardLabel}>RISK UTILIZATION</Text>
            <View style={styles.gaugeRow}>
              <RiskGauge
                value={rm.risk_utilization}
                label="RISK"
                sublabel="utilization"
                showKillSwitch={rm.kill_switch_active}
              />
              <RiskGauge
                value={rm.margin_utilization}
                label="MARGIN"
                sublabel="utilization"
              />
              <RiskGauge
                value={Math.abs(rm.current_drawdown) / Math.max(Math.abs(rm.max_drawdown), 1)}
                label="DRAWDOWN"
                sublabel="vs max"
              />
            </View>
          </Card>
        )}

        {/* ── CVaR / VaR ── */}
        {rm && (
          <Card style={styles.varCard}>
            <Text style={styles.cardLabel}>VALUE AT RISK</Text>
            <View style={styles.varGrid}>
              <VarItem label="VaR 95%" value={formatCurrency(rm.var_95)} color={COLORS.warning} />
              <VarItem label="VaR 99%" value={formatCurrency(rm.var_99)} color={COLORS.loss} />
              <VarItem label="CVaR 95%" value={formatCurrency(rm.cvar_95)} color={COLORS.danger} sublabel="Expected Shortfall" />
              <VarItem label="CVaR 99%" value={formatCurrency(rm.cvar_99)} color={COLORS.danger} />
            </View>
            <View style={styles.varNote}>
              <Ionicons name="information-circle-outline" size={13} color={COLORS.textDim} />
              <Text style={styles.varNoteText}>
                CVaR = expected loss beyond VaR threshold. 1-day horizon.
              </Text>
            </View>
          </Card>
        )}

        {/* ── Drawdown analysis ── */}
        {rm && (
          <Card style={styles.drawdownCard}>
            <Text style={styles.cardLabel}>DRAWDOWN ANALYSIS</Text>
            <View style={styles.drawdownGrid}>
              <DrawdownItem
                label="Current DD"
                value={`${rm.current_drawdown.toFixed(2)}%`}
                color={rm.current_drawdown < -5 ? COLORS.loss : COLORS.warning}
              />
              <DrawdownItem
                label="Max DD"
                value={`${rm.max_drawdown.toFixed(2)}%`}
                color={COLORS.loss}
              />
              <DrawdownItem
                label="DD Duration"
                value={`${rm.drawdown_duration_days.toFixed(0)}d`}
                color={COLORS.textSecondary}
              />
            </View>
            {/* Drawdown bar */}
            <View style={styles.ddBarSection}>
              <Text style={styles.ddBarLabel}>Recovery needed</Text>
              <View style={styles.ddBarTrack}>
                <View style={[styles.ddBarFill, {
                  width: `${Math.min(Math.abs(rm.current_drawdown) / Math.max(Math.abs(rm.max_drawdown), 0.01) * 100, 100)}%` as any,
                  backgroundColor: riskColor(Math.abs(rm.current_drawdown) / 20),
                }]} />
              </View>
              <Text style={styles.ddBarPct}>
                {(Math.abs(rm.current_drawdown) / Math.max(Math.abs(rm.max_drawdown), 0.01) * 100).toFixed(0)}%
              </Text>
            </View>
          </Card>
        )}

        {/* ── Performance ratios ── */}
        {rm && (
          <Card style={styles.ratioCard}>
            <Text style={styles.cardLabel}>PERFORMANCE RATIOS</Text>
            <View style={styles.ratioGrid}>
              <RatioItem
                label="Sharpe"
                value={rm.sharpe_ratio.toFixed(2)}
                color={rm.sharpe_ratio >= 1 ? COLORS.profit : rm.sharpe_ratio >= 0 ? COLORS.warning : COLORS.loss}
                benchmark="≥ 1.0 good"
              />
              <RatioItem
                label="Sortino"
                value={rm.sortino_ratio.toFixed(2)}
                color={rm.sortino_ratio >= 1.5 ? COLORS.profit : rm.sortino_ratio >= 0 ? COLORS.warning : COLORS.loss}
                benchmark="≥ 1.5 good"
              />
              <RatioItem
                label="Calmar"
                value={rm.calmar_ratio.toFixed(2)}
                color={rm.calmar_ratio >= 0.5 ? COLORS.profit : COLORS.warning}
                benchmark="≥ 0.5 good"
              />
            </View>
          </Card>
        )}

        {/* ── Position sizing ── */}
        {rm && (
          <Card style={styles.sizingCard}>
            <Text style={styles.cardLabel}>POSITION SIZING</Text>
            <View style={styles.sizingGrid}>
              <SizingItem label="Current Size" value={`${rm.position_size_pct.toFixed(1)}%`} />
              <SizingItem label="Max Allowed" value={`${rm.max_position_pct.toFixed(1)}%`} />
              <SizingItem
                label="Kelly Fraction"
                value={`${(rm.kelly_fraction * 100).toFixed(1)}%`}
                color={COLORS.accent}
              />
            </View>
            {/* Size utilization bar */}
            <View style={styles.sizeBarRow}>
              <Text style={styles.sizeBarLabel}>Size vs Max</Text>
              <View style={styles.sizeBarTrack}>
                <View style={[styles.sizeBarFill, {
                  width: `${Math.min((rm.position_size_pct / rm.max_position_pct) * 100, 100)}%` as any,
                  backgroundColor: riskColor(rm.position_size_pct / rm.max_position_pct),
                }]} />
              </View>
              <Text style={styles.sizeBarPct}>
                {((rm.position_size_pct / rm.max_position_pct) * 100).toFixed(0)}%
              </Text>
            </View>
          </Card>
        )}

        {/* ── Data quality ── */}
        {rm && (
          <Card style={styles.qualityCard}>
            <Text style={styles.cardLabel}>DATA QUALITY</Text>
            <View style={styles.qualityGrid}>
              <QualityItem
                label="Overall Score"
                value={`${(rm.data_quality_score * 100).toFixed(0)}%`}
                color={rm.data_quality_score >= 0.8 ? COLORS.profit : rm.data_quality_score >= 0.6 ? COLORS.warning : COLORS.loss}
              />
              <QualityItem
                label="Tick Confidence"
                value={`${(rm.tick_confidence * 100).toFixed(0)}%`}
                color={rm.tick_confidence >= 0.8 ? COLORS.profit : COLORS.warning}
              />
              <QualityItem
                label="Source Count"
                value={`${rm.source_count}`}
                color={rm.source_count >= 3 ? COLORS.profit : COLORS.warning}
              />
            </View>
            {/* Quality bar */}
            <View style={styles.qualityBarRow}>
              <View style={styles.qualityBarTrack}>
                <View style={[styles.qualityBarFill, {
                  width: `${rm.data_quality_score * 100}%` as any,
                  backgroundColor: rm.data_quality_score >= 0.8 ? COLORS.profit :
                                   rm.data_quality_score >= 0.6 ? COLORS.warning : COLORS.loss,
                }]} />
              </View>
            </View>
          </Card>
        )}

        {/* ── Macro status ── */}
        {rm && (
          <Card style={[styles.macroCard, rm.is_blackout_window && styles.macroCardBlackout]}>
            <View style={styles.macroHeader}>
              <Text style={styles.cardLabel}>MACRO STATUS</Text>
              {rm.is_blackout_window && (
                <View style={styles.blackoutBadge}>
                  <Ionicons name="time-outline" size={12} color={COLORS.warning} />
                  <Text style={styles.blackoutText}>BLACKOUT WINDOW</Text>
                </View>
              )}
            </View>
            <View style={styles.macroGrid}>
              <MacroItem
                label="Impact Score"
                value={`${(rm.macro_impact_score * 100).toFixed(0)}%`}
                color={rm.macro_impact_score > 0.7 ? COLORS.danger : rm.macro_impact_score > 0.4 ? COLORS.warning : COLORS.profit}
              />
              {rm.hours_to_next_event != null && (
                <MacroItem
                  label="Next Event"
                  value={rm.hours_to_next_event < 1
                    ? `${Math.round(rm.hours_to_next_event * 60)}m`
                    : `${rm.hours_to_next_event.toFixed(1)}h`}
                  color={rm.hours_to_next_event < 2 ? COLORS.warning : COLORS.textSecondary}
                />
              )}
              <MacroItem
                label="Blackout"
                value={rm.is_blackout_window ? 'ACTIVE' : 'CLEAR'}
                color={rm.is_blackout_window ? COLORS.warning : COLORS.profit}
              />
            </View>
          </Card>
        )}

        {!rm && (
          <Card style={styles.noDataCard}>
            <Ionicons name="analytics-outline" size={40} color={COLORS.textDim} />
            <Text style={styles.noDataText}>Risk metrics unavailable</Text>
            <Text style={styles.noDataSub}>Pull to refresh or check connection</Text>
          </Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VarItem({ label, value, color, sublabel }: { label: string; value: string; color: string; sublabel?: string }) {
  return (
    <View style={subStyles.varItem}>
      <Text style={subStyles.varLabel}>{label}</Text>
      <Text style={[subStyles.varValue, { color }]}>{value}</Text>
      {sublabel && <Text style={subStyles.varSublabel}>{sublabel}</Text>}
    </View>
  );
}

function DrawdownItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={subStyles.ddItem}>
      <Text style={subStyles.ddLabel}>{label}</Text>
      <Text style={[subStyles.ddValue, { color }]}>{value}</Text>
    </View>
  );
}

function RatioItem({ label, value, color, benchmark }: { label: string; value: string; color: string; benchmark: string }) {
  return (
    <View style={subStyles.ratioItem}>
      <Text style={subStyles.ratioLabel}>{label}</Text>
      <Text style={[subStyles.ratioValue, { color }]}>{value}</Text>
      <Text style={subStyles.ratioBenchmark}>{benchmark}</Text>
    </View>
  );
}

function SizingItem({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={subStyles.sizingItem}>
      <Text style={subStyles.sizingLabel}>{label}</Text>
      <Text style={[subStyles.sizingValue, { color: color ?? COLORS.text }]}>{value}</Text>
    </View>
  );
}

function QualityItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={subStyles.qualityItem}>
      <Text style={subStyles.qualityLabel}>{label}</Text>
      <Text style={[subStyles.qualityValue, { color }]}>{value}</Text>
    </View>
  );
}

function MacroItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={subStyles.macroItem}>
      <Text style={subStyles.macroLabel}>{label}</Text>
      <Text style={[subStyles.macroValue, { color }]}>{value}</Text>
    </View>
  );
}

const subStyles = StyleSheet.create({
  varItem:       { flex: 1, alignItems: 'center', gap: 3 },
  varLabel:      { ...TEXT.labelSM, color: COLORS.textDim },
  varValue:      { ...TEXT.numericSM, fontWeight: '700' },
  varSublabel:   { ...TEXT.captionSM, color: COLORS.textDim },
  ddItem:        { flex: 1, alignItems: 'center', gap: 3 },
  ddLabel:       { ...TEXT.labelSM, color: COLORS.textDim },
  ddValue:       { ...TEXT.numericMD, fontWeight: '700' },
  ratioItem:     { flex: 1, alignItems: 'center', gap: 3 },
  ratioLabel:    { ...TEXT.labelSM, color: COLORS.textDim },
  ratioValue:    { ...TEXT.numericMD, fontWeight: '800' },
  ratioBenchmark:{ ...TEXT.captionSM, color: COLORS.textDim },
  sizingItem:    { flex: 1, alignItems: 'center', gap: 3 },
  sizingLabel:   { ...TEXT.labelSM, color: COLORS.textDim },
  sizingValue:   { ...TEXT.numericSM, fontWeight: '700' },
  qualityItem:   { flex: 1, alignItems: 'center', gap: 3 },
  qualityLabel:  { ...TEXT.labelSM, color: COLORS.textDim },
  qualityValue:  { ...TEXT.numericSM, fontWeight: '700' },
  macroItem:     { flex: 1, alignItems: 'center', gap: 3 },
  macroLabel:    { ...TEXT.labelSM, color: COLORS.textDim },
  macroValue:    { ...TEXT.numericSM, fontWeight: '700' },
});

const styles = StyleSheet.create({
  safe:              { flex: 1, backgroundColor: COLORS.background },
  content:           { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  pageHeader:        { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  pageTitle:         { ...TEXT.h1, color: COLORS.text },
  statusBadge:       { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.full, borderWidth: 1 },
  statusDot:         { width: 7, height: 7, borderRadius: 4 },
  statusText:        { ...TEXT.label, fontSize: 11 },
  cardLabel:         { ...TEXT.label, color: COLORS.textMuted },
  gaugeCard:         { gap: SPACING.md },
  gaugeRow:          { flexDirection: 'row', justifyContent: 'space-around', paddingVertical: SPACING.sm },
  varCard:           { gap: SPACING.md },
  varGrid:           { flexDirection: 'row', justifyContent: 'space-between' },
  varNote:           { flexDirection: 'row', alignItems: 'center', gap: 5, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  varNoteText:       { ...TEXT.captionSM, color: COLORS.textDim, flex: 1 },
  drawdownCard:      { gap: SPACING.md },
  drawdownGrid:      { flexDirection: 'row', justifyContent: 'space-around' },
  ddBarSection:      { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  ddBarLabel:        { ...TEXT.labelSM, color: COLORS.textDim, width: 90 },
  ddBarTrack:        { flex: 1, height: 6, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden' },
  ddBarFill:         { height: '100%', borderRadius: RADIUS.full },
  ddBarPct:          { ...TEXT.numericXS, width: 36, textAlign: 'right' },
  ratioCard:         { gap: SPACING.md },
  ratioGrid:         { flexDirection: 'row', justifyContent: 'space-around' },
  sizingCard:        { gap: SPACING.md },
  sizingGrid:        { flexDirection: 'row', justifyContent: 'space-around' },
  sizeBarRow:        { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  sizeBarLabel:      { ...TEXT.labelSM, color: COLORS.textDim, width: 70 },
  sizeBarTrack:      { flex: 1, height: 6, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden' },
  sizeBarFill:       { height: '100%', borderRadius: RADIUS.full },
  sizeBarPct:        { ...TEXT.numericXS, width: 36, textAlign: 'right' },
  qualityCard:       { gap: SPACING.md },
  qualityGrid:       { flexDirection: 'row', justifyContent: 'space-around' },
  qualityBarRow:     { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  qualityBarTrack:   { height: 8, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden' },
  qualityBarFill:    { height: '100%', borderRadius: RADIUS.full },
  macroCard:         { gap: SPACING.md },
  macroCardBlackout: { borderColor: COLORS.warning + '55', backgroundColor: COLORS.warningDim },
  macroHeader:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  blackoutBadge:     { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: COLORS.warningDim, paddingHorizontal: SPACING.sm, paddingVertical: 3, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.warning + '44' },
  blackoutText:      { ...TEXT.labelSM, color: COLORS.warning, fontSize: 10 },
  macroGrid:         { flexDirection: 'row', justifyContent: 'space-around' },
  noDataCard:        { alignItems: 'center', gap: SPACING.md, paddingVertical: SPACING.xl },
  noDataText:        { ...TEXT.h3, color: COLORS.textMuted },
  noDataSub:         { ...TEXT.bodySM, color: COLORS.textDim },
});
