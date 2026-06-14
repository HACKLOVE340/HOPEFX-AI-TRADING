// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/StrategyBuilderScreen.tsx
 * ==================================
 * Mobile no-code strategy builder — simplified drag-and-drop style interface.
 * Connected to: /api/strategies/dynamic/*, /api/nocode/*
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity, Alert, TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { apiClient } from '../services/apiClient';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';

interface Strategy {
  name: string;
  version: string;
  status: 'active' | 'paused' | 'draft' | 'backtesting';
  win_rate: number;
  total_pnl: number;
  trades: number;
  last_updated: string;
  description: string;
}

interface StrategyTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  complexity: 'beginner' | 'intermediate' | 'advanced';
  indicators: string[];
}

type Tab = 'my' | 'templates';

export function StrategyBuilderScreen() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [templates, setTemplates] = useState<StrategyTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>('my');

  const fetchData = useCallback(async () => {
    try {
      const [stratRes, templRes] = await Promise.all([
        apiClient.get<{ strategies: Strategy[] }>('/api/strategies/dynamic/list'),
        apiClient.get<{ templates: StrategyTemplate[] }>('/api/nocode/templates').catch(() => ({ data: { templates: [] } })),
      ]);
      setStrategies(stratRes.data.strategies ?? []);
      setTemplates(templRes.data.templates ?? []);
    } catch (err) {
      console.error('Strategy fetch error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  const onRefresh = () => { setRefreshing(true); fetchData(); };

  const toggleStrategy = async (name: string, currentStatus: string) => {
    const action = currentStatus === 'active' ? 'pause' : 'activate';
    try {
      await apiClient.post(`/api/strategies/dynamic/${name}/${action}`, {});
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      fetchData();
    } catch (err) {
      Alert.alert('Error', `Failed to ${action} strategy.`);
    }
  };

  const deployTemplate = async (template: StrategyTemplate) => {
    Alert.alert(
      'Deploy Strategy',
      `Deploy "${template.name}" to your account?\n\nThis will create a new strategy from this template.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Deploy',
          onPress: async () => {
            try {
              await apiClient.post('/api/nocode/deploy', { template_id: template.id });
              Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
              setTab('my');
              fetchData();
            } catch (err) {
              Alert.alert('Error', 'Failed to deploy strategy.');
            }
          },
        },
      ]
    );
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
          <Text style={styles.title}>Strategy Builder</Text>
          <Text style={styles.subtitle}>Build, deploy, and manage trading strategies</Text>
        </View>

        {/* Tabs */}
        <View style={styles.tabRow}>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'my' && styles.tabBtnActive]}
            onPress={() => setTab('my')}
          >
            <Ionicons name="code-slash" size={16} color={tab === 'my' ? COLORS.accent : COLORS.textMuted} />
            <Text style={[styles.tabText, tab === 'my' && styles.tabTextActive]}>My Strategies ({strategies.length})</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'templates' && styles.tabBtnActive]}
            onPress={() => setTab('templates')}
          >
            <Ionicons name="grid" size={16} color={tab === 'templates' ? COLORS.accent : COLORS.textMuted} />
            <Text style={[styles.tabText, tab === 'templates' && styles.tabTextActive]}>Templates</Text>
          </TouchableOpacity>
        </View>

        {/* My Strategies */}
        {tab === 'my' && (
          <View style={styles.list}>
            {strategies.length === 0 ? (
              <Card style={styles.emptyCard}>
                <Ionicons name="code-slash-outline" size={48} color={COLORS.textMuted} />
                <Text style={styles.emptyText}>No strategies yet</Text>
                <Text style={styles.emptySubtext}>Deploy a template or create one from scratch</Text>
              </Card>
            ) : (
              strategies.map(strat => (
                <Card key={strat.name} style={styles.stratCard}>
                  <View style={styles.stratHeader}>
                    <View style={[styles.statusIndicator, {
                      backgroundColor: strat.status === 'active' ? COLORS.buy :
                        strat.status === 'paused' ? COLORS.accent :
                        strat.status === 'backtesting' ? COLORS.info : COLORS.textMuted
                    }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.stratName}>{strat.name}</Text>
                      <Text style={styles.stratMeta}>v{strat.version} • {strat.status}</Text>
                    </View>
                    <TouchableOpacity
                      style={[styles.toggleBtn, {
                        backgroundColor: strat.status === 'active' ? `${COLORS.sell}20` : `${COLORS.buy}20`
                      }]}
                      onPress={() => toggleStrategy(strat.name, strat.status)}
                    >
                      <Ionicons
                        name={strat.status === 'active' ? 'pause' : 'play'}
                        size={16}
                        color={strat.status === 'active' ? COLORS.sell : COLORS.buy}
                      />
                    </TouchableOpacity>
                  </View>
                  <Text style={styles.stratDesc} numberOfLines={2}>{strat.description}</Text>
                  <View style={styles.stratMetrics}>
                    <View style={styles.stratMetric}>
                      <Text style={styles.stratMetricValue}>{strat.win_rate}%</Text>
                      <Text style={styles.stratMetricLabel}>Win Rate</Text>
                    </View>
                    <View style={styles.stratMetric}>
                      <Text style={[styles.stratMetricValue, { color: strat.total_pnl >= 0 ? COLORS.buy : COLORS.sell }]}>
                        {strat.total_pnl >= 0 ? '+' : ''}${strat.total_pnl.toFixed(0)}
                      </Text>
                      <Text style={styles.stratMetricLabel}>P&L</Text>
                    </View>
                    <View style={styles.stratMetric}>
                      <Text style={styles.stratMetricValue}>{strat.trades}</Text>
                      <Text style={styles.stratMetricLabel}>Trades</Text>
                    </View>
                  </View>
                </Card>
              ))
            )}
          </View>
        )}

        {/* Templates */}
        {tab === 'templates' && (
          <View style={styles.list}>
            {templates.map(tmpl => (
              <Card key={tmpl.id} style={styles.templateCard}>
                <View style={styles.templateHeader}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.templateName}>{tmpl.name}</Text>
                    <Text style={styles.templateCategory}>{tmpl.category}</Text>
                  </View>
                  <View style={[styles.complexityBadge, {
                    backgroundColor: tmpl.complexity === 'beginner' ? `${COLORS.buy}20` :
                      tmpl.complexity === 'intermediate' ? `${COLORS.accent}20` : `${COLORS.sell}20`
                  }]}>
                    <Text style={[styles.complexityText, {
                      color: tmpl.complexity === 'beginner' ? COLORS.buy :
                        tmpl.complexity === 'intermediate' ? COLORS.accent : COLORS.sell
                    }]}>{tmpl.complexity}</Text>
                  </View>
                </View>
                <Text style={styles.templateDesc} numberOfLines={2}>{tmpl.description}</Text>
                <View style={styles.indicatorsRow}>
                  {tmpl.indicators.slice(0, 4).map(ind => (
                    <View key={ind} style={styles.indicatorChip}>
                      <Text style={styles.indicatorText}>{ind}</Text>
                    </View>
                  ))}
                </View>
                <TouchableOpacity style={styles.deployBtn} onPress={() => deployTemplate(tmpl)}>
                  <Ionicons name="rocket-outline" size={16} color={COLORS.background} />
                  <Text style={styles.deployBtnText}>Deploy</Text>
                </TouchableOpacity>
              </Card>
            ))}
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
  tabRow: { flexDirection: 'row', marginHorizontal: SPACING.lg, marginBottom: SPACING.md, backgroundColor: COLORS.surface, borderRadius: RADIUS.md, padding: 4 },
  tabBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: RADIUS.sm },
  tabBtnActive: { backgroundColor: `${COLORS.accent}20` },
  tabText: { ...TEXT.captionSM, color: COLORS.textMuted, fontWeight: '600' },
  tabTextActive: { color: COLORS.accent },
  list: { paddingHorizontal: SPACING.lg, paddingBottom: SPACING.xl },
  emptyCard: { padding: SPACING.xl, alignItems: 'center' },
  emptyText: { ...TEXT.body, color: COLORS.textMuted, fontWeight: '600', marginTop: SPACING.md },
  emptySubtext: { ...TEXT.caption, color: COLORS.textMuted, marginTop: 4 },
  stratCard: { marginBottom: SPACING.sm, padding: SPACING.md },
  stratHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, marginBottom: SPACING.sm },
  statusIndicator: { width: 8, height: 8, borderRadius: 4 },
  stratName: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  stratMeta: { ...TEXT.captionSM, color: COLORS.textMuted },
  toggleBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  stratDesc: { ...TEXT.caption, color: COLORS.textMuted, marginBottom: SPACING.sm },
  stratMetrics: { flexDirection: 'row', justifyContent: 'space-around', borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm },
  stratMetric: { alignItems: 'center' },
  stratMetricValue: { ...TEXT.body, color: COLORS.text, fontWeight: '800' },
  stratMetricLabel: { ...TEXT.captionSM, color: COLORS.textMuted },
  templateCard: { marginBottom: SPACING.sm, padding: SPACING.md },
  templateHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACING.sm },
  templateName: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  templateCategory: { ...TEXT.captionSM, color: COLORS.textMuted },
  complexityBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: RADIUS.sm },
  complexityText: { ...TEXT.captionSM, fontWeight: '700', textTransform: 'capitalize' },
  templateDesc: { ...TEXT.caption, color: COLORS.textMuted, marginBottom: SPACING.sm },
  indicatorsRow: { flexDirection: 'row', gap: 6, marginBottom: SPACING.md, flexWrap: 'wrap' },
  indicatorChip: { backgroundColor: `${COLORS.accent}15`, paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.sm },
  indicatorText: { ...TEXT.captionSM, color: COLORS.accent, fontWeight: '600' },
  deployBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: COLORS.accent, paddingVertical: 12, borderRadius: RADIUS.md },
  deployBtnText: { ...TEXT.body, color: COLORS.background, fontWeight: '700' },
});
