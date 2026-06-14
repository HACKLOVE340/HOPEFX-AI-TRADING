// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/TransparencyScreen.tsx
 * ===============================
 * Trade Explainability — shows why each trade was taken, with full decision breakdown.
 * Connected to: /api/transparency/decisions, /api/transparency/explain/*
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/apiClient';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';

interface DecisionRecord {
  id: string;
  timestamp: string;
  symbol: string;
  direction: 'long' | 'short' | 'skip';
  confidence: number;
  outcome: 'win' | 'loss' | 'pending' | 'skipped';
  pnl: number | null;
  factors: DecisionFactor[];
  reasoning: string;
  model_version: string;
  execution_ms: number;
}

interface DecisionFactor {
  name: string;
  weight: number;
  value: number;
  direction: 'bullish' | 'bearish' | 'neutral';
  contribution: number; // -1 to 1
}

export function TransparencyScreen() {
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await apiClient.get<{ decisions: DecisionRecord[] }>('/api/transparency/decisions', {
        params: { limit: 30 },
      });
      setDecisions(res.data.decisions ?? []);
    } catch (err) {
      console.error('Transparency fetch error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  const onRefresh = () => { setRefreshing(true); fetchData(); };

  const toggleExpand = (id: string) => {
    setExpanded(prev => prev === id ? null : id);
  };

  const outcomeIcon = (outcome: string) => {
    switch (outcome) {
      case 'win': return { name: 'checkmark-circle' as const, color: COLORS.buy };
      case 'loss': return { name: 'close-circle' as const, color: COLORS.sell };
      case 'pending': return { name: 'time' as const, color: COLORS.accent };
      default: return { name: 'remove-circle' as const, color: COLORS.textMuted };
    }
  };

  const factorBarWidth = (contribution: number) => Math.abs(contribution) * 100;

  if (loading) {
    return <SafeAreaView style={styles.container}><LoadingSpinner /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.accent} />}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>Trade Transparency</Text>
          <Text style={styles.subtitle}>Understand why every decision was made</Text>
        </View>

        {/* Summary Stats */}
        <View style={styles.statsRow}>
          <Card style={styles.statCard}>
            <Text style={styles.statValue}>{decisions.length}</Text>
            <Text style={styles.statLabel}>Decisions</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={[styles.statValue, { color: COLORS.buy }]}>
              {decisions.filter(d => d.outcome === 'win').length}
            </Text>
            <Text style={styles.statLabel}>Wins</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={[styles.statValue, { color: COLORS.sell }]}>
              {decisions.filter(d => d.outcome === 'loss').length}
            </Text>
            <Text style={styles.statLabel}>Losses</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={styles.statValue}>
              {decisions.filter(d => d.direction === 'skip').length}
            </Text>
            <Text style={styles.statLabel}>Skipped</Text>
          </Card>
        </View>

        {/* Decision List */}
        <View style={styles.list}>
          {decisions.map(decision => {
            const isExpanded = expanded === decision.id;
            const { name: iconName, color: iconColor } = outcomeIcon(decision.outcome);
            return (
              <TouchableOpacity
                key={decision.id}
                activeOpacity={0.8}
                onPress={() => toggleExpand(decision.id)}
              >
                <Card style={[styles.decisionCard, isExpanded && styles.decisionCardExpanded]}>
                  {/* Compact View */}
                  <View style={styles.decisionHeader}>
                    <Ionicons name={iconName} size={20} color={iconColor} />
                    <View style={{ flex: 1, marginLeft: SPACING.sm }}>
                      <View style={styles.decisionTitleRow}>
                        <Text style={styles.decisionSymbol}>{decision.symbol}</Text>
                        <View style={[styles.directionBadge, {
                          backgroundColor: decision.direction === 'long' ? `${COLORS.buy}20` :
                            decision.direction === 'short' ? `${COLORS.sell}20` : `${COLORS.textMuted}20`
                        }]}>
                          <Text style={[styles.directionText, {
                            color: decision.direction === 'long' ? COLORS.buy :
                              decision.direction === 'short' ? COLORS.sell : COLORS.textMuted
                          }]}>{decision.direction}</Text>
                        </View>
                        <Text style={styles.confidenceText}>{(decision.confidence * 100).toFixed(0)}%</Text>
                      </View>
                      <Text style={styles.decisionTime}>
                        {new Date(decision.timestamp).toLocaleString()} • {decision.execution_ms}ms
                      </Text>
                    </View>
                    {decision.pnl !== null && (
                      <Text style={[styles.decisionPnl, { color: decision.pnl >= 0 ? COLORS.buy : COLORS.sell }]}>
                        {decision.pnl >= 0 ? '+' : ''}${decision.pnl.toFixed(2)}
                      </Text>
                    )}
                    <Ionicons
                      name={isExpanded ? 'chevron-up' : 'chevron-down'}
                      size={16}
                      color={COLORS.textMuted}
                      style={{ marginLeft: SPACING.sm }}
                    />
                  </View>

                  {/* Expanded View */}
                  {isExpanded && (
                    <View style={styles.expandedContent}>
                      {/* Reasoning */}
                      <View style={styles.reasoningBox}>
                        <Ionicons name="bulb" size={14} color={COLORS.accent} />
                        <Text style={styles.reasoningText}>{decision.reasoning}</Text>
                      </View>

                      {/* Factor Breakdown */}
                      <Text style={styles.factorsTitle}>Decision Factors</Text>
                      {decision.factors.map((factor, idx) => (
                        <View key={idx} style={styles.factorRow}>
                          <View style={styles.factorLabel}>
                            <Text style={styles.factorName}>{factor.name}</Text>
                            <Text style={[styles.factorDirection, {
                              color: factor.direction === 'bullish' ? COLORS.buy :
                                factor.direction === 'bearish' ? COLORS.sell : COLORS.textMuted
                            }]}>{factor.direction}</Text>
                          </View>
                          <View style={styles.factorBarContainer}>
                            <View style={[
                              styles.factorBar,
                              {
                                width: `${factorBarWidth(factor.contribution)}%`,
                                backgroundColor: factor.contribution > 0 ? COLORS.buy : COLORS.sell,
                                alignSelf: factor.contribution > 0 ? 'flex-start' : 'flex-end',
                              }
                            ]} />
                          </View>
                          <Text style={styles.factorWeight}>{(factor.weight * 100).toFixed(0)}%</Text>
                        </View>
                      ))}

                      {/* Model Info */}
                      <View style={styles.modelInfo}>
                        <Text style={styles.modelText}>Model: {decision.model_version}</Text>
                      </View>
                    </View>
                  )}
                </Card>
              </TouchableOpacity>
            );
          })}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: { paddingHorizontal: SPACING.lg, paddingTop: SPACING.lg, paddingBottom: SPACING.md },
  title: { ...TEXT.h1, color: COLORS.text },
  subtitle: { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  statsRow: { flexDirection: 'row', paddingHorizontal: SPACING.lg, gap: SPACING.sm, marginBottom: SPACING.md },
  statCard: { flex: 1, padding: SPACING.sm, alignItems: 'center' },
  statValue: { ...TEXT.h2, color: COLORS.text },
  statLabel: { ...TEXT.captionSM, color: COLORS.textMuted, marginTop: 2 },
  list: { paddingHorizontal: SPACING.lg, paddingBottom: SPACING.xl },
  decisionCard: { marginBottom: SPACING.sm, padding: SPACING.md },
  decisionCardExpanded: { borderColor: COLORS.accent, borderWidth: 1 },
  decisionHeader: { flexDirection: 'row', alignItems: 'center' },
  decisionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  decisionSymbol: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  directionBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.sm },
  directionText: { ...TEXT.captionSM, fontWeight: '700', textTransform: 'uppercase' },
  confidenceText: { ...TEXT.captionSM, color: COLORS.accent, fontWeight: '700' },
  decisionTime: { ...TEXT.captionSM, color: COLORS.textMuted, marginTop: 2 },
  decisionPnl: { ...TEXT.body, fontWeight: '800' },
  expandedContent: { marginTop: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.md },
  reasoningBox: { flexDirection: 'row', gap: 8, backgroundColor: `${COLORS.accent}10`, padding: SPACING.sm, borderRadius: RADIUS.md, marginBottom: SPACING.md },
  reasoningText: { ...TEXT.caption, color: COLORS.text, flex: 1 },
  factorsTitle: { ...TEXT.captionSM, color: COLORS.textMuted, fontWeight: '700', marginBottom: SPACING.sm, textTransform: 'uppercase', letterSpacing: 0.5 },
  factorRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  factorLabel: { width: 100 },
  factorName: { ...TEXT.captionSM, color: COLORS.text, fontWeight: '600' },
  factorDirection: { ...TEXT.captionSM, fontSize: 9 },
  factorBarContainer: { flex: 1, height: 6, backgroundColor: COLORS.border, borderRadius: 3, marginHorizontal: SPACING.sm },
  factorBar: { height: '100%', borderRadius: 3 },
  factorWeight: { ...TEXT.captionSM, color: COLORS.textMuted, width: 30, textAlign: 'right' },
  modelInfo: { marginTop: SPACING.md, paddingTop: SPACING.sm, borderTopWidth: 1, borderTopColor: COLORS.border },
  modelText: { ...TEXT.captionSM, color: COLORS.textMuted },
});
