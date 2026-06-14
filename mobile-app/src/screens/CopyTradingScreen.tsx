// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/CopyTradingScreen.tsx
 * ==============================
 * Social copy trading — discover master traders, manage copies, view mirrored positions.
 * Connected to: /api/leaderboard, /api/social/copy/*, /api/copy-trading/*
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { apiClient } from '../services/apiClient';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { formatCurrency, formatPct } from '../utils/formatters';

interface MasterTrader {
  id: string;
  name: string;
  return_3m: number;
  sharpe: number;
  max_dd: number;
  followers: number;
  aum: number;
  fee: number;
  win_rate: number;
  trades_per_week: number;
  verified: boolean;
  risk_score: number;
  preferred_pairs: string[];
}

interface CopyRelation {
  id: string;
  master_id: string;
  master_name: string;
  status: 'active' | 'paused' | 'stopped';
  allocation_usd: number;
  risk_multiplier: number;
  total_pnl: number;
  trades_copied: number;
  open_positions: number;
  started_at: string;
}

type Tab = 'discover' | 'active';

export function CopyTradingScreen() {
  const [leaders, setLeaders] = useState<MasterTrader[]>([]);
  const [copies, setCopies] = useState<CopyRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>('discover');

  const fetchData = useCallback(async () => {
    try {
      const [leadersRes, copiesRes] = await Promise.all([
        apiClient.get<{ leaders: MasterTrader[] }>('/api/leaderboard'),
        apiClient.get<{ copies: CopyRelation[] }>('/api/copy-trading/my-copies').catch(() => ({ data: { copies: [] } })),
      ]);
      setLeaders(leadersRes.data.leaders ?? []);
      setCopies(copiesRes.data.copies ?? []);
    } catch (err) {
      console.error('Copy trading fetch error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  const onRefresh = () => { setRefreshing(true); fetchData(); };

  const startCopy = async (leader: MasterTrader) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    Alert.alert(
      `Copy ${leader.name}?`,
      `Allocation: $10,000\nRisk: 1.0x\nFee: ${leader.fee}%\n\nStart copying this trader?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Start Copying',
          onPress: async () => {
            try {
              await apiClient.post(`/api/social/copy/${leader.id}`, {
                allocation_usd: 10000,
                risk_multiplier: 1.0,
                max_dd_stop: 15,
              });
              Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
              fetchData();
            } catch (err) {
              Alert.alert('Error', 'Failed to start copy trading.');
            }
          },
        },
      ]
    );
  };

  const pauseCopy = async (copyId: string) => {
    try {
      await apiClient.post(`/api/copy-trading/copies/${copyId}/pause`, {});
      setCopies(prev => prev.map(c => c.id === copyId ? { ...c, status: 'paused' } : c));
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch (err) {
      Alert.alert('Error', 'Failed to pause copy.');
    }
  };

  const resumeCopy = async (copyId: string) => {
    try {
      await apiClient.post(`/api/copy-trading/copies/${copyId}/resume`, {});
      setCopies(prev => prev.map(c => c.id === copyId ? { ...c, status: 'active' } : c));
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch (err) {
      Alert.alert('Error', 'Failed to resume copy.');
    }
  };

  const stopCopy = async (copyId: string) => {
    Alert.alert('Stop Copy?', 'This will close all mirrored positions.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Stop', style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.post(`/api/copy-trading/copies/${copyId}/stop`, {});
            setCopies(prev => prev.filter(c => c.id !== copyId));
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
          } catch (err) {
            Alert.alert('Error', 'Failed to stop copy.');
          }
        },
      },
    ]);
  };

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
          <Text style={styles.title}>Copy Trading</Text>
          <Text style={styles.subtitle}>Follow top traders automatically</Text>
        </View>

        {/* Stats */}
        <View style={styles.statsRow}>
          <Card style={styles.statCard}>
            <Text style={styles.statValue}>{copies.filter(c => c.status === 'active').length}</Text>
            <Text style={styles.statLabel}>Active</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={[styles.statValue, { color: copies.reduce((s, c) => s + c.total_pnl, 0) >= 0 ? COLORS.buy : COLORS.sell }]}>
              {formatCurrency(copies.reduce((s, c) => s + c.total_pnl, 0))}
            </Text>
            <Text style={styles.statLabel}>Total P&L</Text>
          </Card>
          <Card style={styles.statCard}>
            <Text style={styles.statValue}>{copies.reduce((s, c) => s + c.trades_copied, 0)}</Text>
            <Text style={styles.statLabel}>Trades</Text>
          </Card>
        </View>

        {/* Tabs */}
        <View style={styles.tabRow}>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'discover' && styles.tabBtnActive]}
            onPress={() => setTab('discover')}
          >
            <Ionicons name="search" size={16} color={tab === 'discover' ? COLORS.accent : COLORS.textMuted} />
            <Text style={[styles.tabText, tab === 'discover' && styles.tabTextActive]}>Discover</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'active' && styles.tabBtnActive]}
            onPress={() => setTab('active')}
          >
            <Ionicons name="copy" size={16} color={tab === 'active' ? COLORS.accent : COLORS.textMuted} />
            <Text style={[styles.tabText, tab === 'active' && styles.tabTextActive]}>My Copies ({copies.length})</Text>
          </TouchableOpacity>
        </View>

        {/* Discover Tab */}
        {tab === 'discover' && (
          <View style={styles.list}>
            {leaders.map((leader, idx) => (
              <Card key={leader.id} style={styles.leaderCard}>
                <View style={styles.leaderHeader}>
                  <View style={styles.rankBadge}>
                    <Text style={styles.rankText}>#{idx + 1}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <View style={styles.nameRow}>
                      <Text style={styles.leaderName}>{leader.name}</Text>
                      {leader.verified && <Ionicons name="checkmark-circle" size={14} color={COLORS.accent} />}
                    </View>
                    <Text style={styles.leaderMeta}>
                      {leader.followers} followers • ${(leader.aum / 1e6).toFixed(1)}M AUM
                    </Text>
                  </View>
                  <View style={[styles.riskBadge, {
                    backgroundColor: leader.risk_score <= 3 ? `${COLORS.buy}20` :
                      leader.risk_score <= 6 ? `${COLORS.accent}20` : `${COLORS.sell}20`
                  }]}>
                    <Text style={[styles.riskText, {
                      color: leader.risk_score <= 3 ? COLORS.buy :
                        leader.risk_score <= 6 ? COLORS.accent : COLORS.sell
                    }]}>Risk {leader.risk_score}/10</Text>
                  </View>
                </View>

                <View style={styles.metricsGrid}>
                  <View style={styles.metric}>
                    <Text style={[styles.metricValue, { color: COLORS.buy }]}>+{leader.return_3m}%</Text>
                    <Text style={styles.metricLabel}>3M Return</Text>
                  </View>
                  <View style={styles.metric}>
                    <Text style={styles.metricValue}>{leader.win_rate}%</Text>
                    <Text style={styles.metricLabel}>Win Rate</Text>
                  </View>
                  <View style={styles.metric}>
                    <Text style={styles.metricValue}>{leader.sharpe}</Text>
                    <Text style={styles.metricLabel}>Sharpe</Text>
                  </View>
                  <View style={styles.metric}>
                    <Text style={[styles.metricValue, { color: COLORS.sell }]}>{leader.max_dd}%</Text>
                    <Text style={styles.metricLabel}>Max DD</Text>
                  </View>
                </View>

                {leader.preferred_pairs.length > 0 && (
                  <View style={styles.pairsRow}>
                    {leader.preferred_pairs.slice(0, 4).map(p => (
                      <View key={p} style={styles.pairChip}>
                        <Text style={styles.pairText}>{p}</Text>
                      </View>
                    ))}
                  </View>
                )}

                <TouchableOpacity style={styles.copyBtn} onPress={() => startCopy(leader)}>
                  <Ionicons name="copy-outline" size={16} color={COLORS.background} />
                  <Text style={styles.copyBtnText}>Copy • {leader.fee}% fee</Text>
                </TouchableOpacity>
              </Card>
            ))}
          </View>
        )}

        {/* Active Tab */}
        {tab === 'active' && (
          <View style={styles.list}>
            {copies.length === 0 ? (
              <Card style={styles.emptyCard}>
                <Ionicons name="copy-outline" size={48} color={COLORS.textMuted} />
                <Text style={styles.emptyText}>No active copies</Text>
                <Text style={styles.emptySubtext}>Discover top traders and start copying</Text>
              </Card>
            ) : (
              copies.map(copy => (
                <Card key={copy.id} style={styles.copyCard}>
                  <View style={styles.copyHeader}>
                    <View style={[styles.statusDot, {
                      backgroundColor: copy.status === 'active' ? COLORS.buy : copy.status === 'paused' ? COLORS.accent : COLORS.textMuted
                    }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.copyName}>{copy.master_name}</Text>
                      <Text style={styles.copyMeta}>
                        {copy.status} • {copy.trades_copied} trades • {copy.open_positions} open
                      </Text>
                    </View>
                    <Text style={[styles.copyPnl, { color: copy.total_pnl >= 0 ? COLORS.buy : COLORS.sell }]}>
                      {copy.total_pnl >= 0 ? '+' : ''}${copy.total_pnl.toFixed(2)}
                    </Text>
                  </View>
                  <View style={styles.copyDetails}>
                    <Text style={styles.copyDetail}>${copy.allocation_usd.toLocaleString()} • {copy.risk_multiplier}x risk</Text>
                  </View>
                  <View style={styles.copyActions}>
                    {copy.status === 'active' ? (
                      <TouchableOpacity style={styles.actionBtn} onPress={() => pauseCopy(copy.id)}>
                        <Ionicons name="pause" size={16} color={COLORS.accent} />
                        <Text style={[styles.actionText, { color: COLORS.accent }]}>Pause</Text>
                      </TouchableOpacity>
                    ) : copy.status === 'paused' ? (
                      <TouchableOpacity style={styles.actionBtn} onPress={() => resumeCopy(copy.id)}>
                        <Ionicons name="play" size={16} color={COLORS.buy} />
                        <Text style={[styles.actionText, { color: COLORS.buy }]}>Resume</Text>
                      </TouchableOpacity>
                    ) : null}
                    <TouchableOpacity style={styles.actionBtn} onPress={() => stopCopy(copy.id)}>
                      <Ionicons name="close-circle" size={16} color={COLORS.sell} />
                      <Text style={[styles.actionText, { color: COLORS.sell }]}>Stop</Text>
                    </TouchableOpacity>
                  </View>
                </Card>
              ))
            )}
          </View>
        )}
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
  statCard: { flex: 1, padding: SPACING.md, alignItems: 'center' },
  statValue: { ...TEXT.h2, color: COLORS.text },
  statLabel: { ...TEXT.captionSM, color: COLORS.textMuted, marginTop: 2 },
  tabRow: { flexDirection: 'row', marginHorizontal: SPACING.lg, marginBottom: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, padding: 4 },
  tabBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: RADIUS.sm },
  tabBtnActive: { backgroundColor: `${COLORS.accent}20` },
  tabText: { ...TEXT.captionSM, color: COLORS.textMuted, fontWeight: '600' },
  tabTextActive: { color: COLORS.accent },
  list: { paddingHorizontal: SPACING.lg, paddingBottom: SPACING.xl },
  leaderCard: { marginBottom: SPACING.sm, padding: SPACING.md },
  leaderHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.md },
  rankBadge: { width: 36, height: 36, borderRadius: 18, backgroundColor: `${COLORS.accent}20`, alignItems: 'center', justifyContent: 'center' },
  rankText: { ...TEXT.captionSM, color: COLORS.accent, fontWeight: '800' },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  leaderName: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  leaderMeta: { ...TEXT.captionSM, color: COLORS.textMuted },
  riskBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: RADIUS.sm },
  riskText: { ...TEXT.captionSM, fontWeight: '700' },
  metricsGrid: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: SPACING.sm },
  metric: { alignItems: 'center' },
  metricValue: { ...TEXT.body, color: COLORS.text, fontWeight: '800' },
  metricLabel: { ...TEXT.captionSM, color: COLORS.textMuted },
  pairsRow: { flexDirection: 'row', gap: 6, marginBottom: SPACING.md },
  pairChip: { backgroundColor: `${COLORS.accent}15`, paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.sm },
  pairText: { ...TEXT.captionSM, color: COLORS.accent, fontWeight: '600' },
  copyBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: COLORS.accent, paddingVertical: 12, borderRadius: RADIUS.md },
  copyBtnText: { ...TEXT.body, color: COLORS.background, fontWeight: '700' },
  emptyCard: { padding: SPACING.xl, alignItems: 'center' },
  emptyText: { ...TEXT.body, color: COLORS.textMuted, fontWeight: '600', marginTop: SPACING.md },
  emptySubtext: { ...TEXT.caption, color: COLORS.textMuted, marginTop: 4 },
  copyCard: { marginBottom: SPACING.sm, padding: SPACING.md },
  copyHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.sm },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  copyName: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  copyMeta: { ...TEXT.captionSM, color: COLORS.textMuted },
  copyPnl: { ...TEXT.h2, fontWeight: '800' },
  copyDetails: { marginBottom: SPACING.sm },
  copyDetail: { ...TEXT.captionSM, color: COLORS.textMuted },
  copyActions: { flexDirection: 'row', gap: SPACING.md, borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  actionText: { ...TEXT.captionSM, fontWeight: '700' },
});
