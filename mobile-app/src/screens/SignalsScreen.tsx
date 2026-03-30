// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/SignalsScreen.tsx
 * =========================
 * Live AI signal feed with confidence bars, factor reasoning,
 * one-tap trade approval, and haptic feedback.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';

import { useTradingStore }   from '../store/tradingStore';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';
import { SignalCard }        from '../components/SignalCard';
import { SentimentMeter }   from '../components/SentimentMeter';
import { Card }              from '../components/Card';

import { COLORS, SPACING, RADIUS, TEXT, confidenceColor } from '../utils/theme';
import { TradingStackParamList } from '../types';

type Nav = NativeStackNavigationProp<TradingStackParamList>;

const SYMBOLS = ['All', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];
const DIRECTIONS = ['All', 'Long', 'Short'] as const;

export function SignalsScreen() {
  const navigation = useNavigation<Nav>();
  const {
    signals, sentiment, fetchSignals, fetchSentiment,
    approveSignal, isLoading,
  } = useTradingStore();

  const [selectedSymbol, setSelectedSymbol]    = useState('All');
  const [selectedDir, setSelectedDir]          = useState<typeof DIRECTIONS[number]>('All');
  const [minConfidence, setMinConfidence]       = useState(0);

  const load = useCallback(() => {
    fetchSignals(selectedSymbol !== 'All' ? selectedSymbol : undefined);
    fetchSentiment(selectedSymbol !== 'All' ? selectedSymbol : 'XAUUSD');
  }, [selectedSymbol]);

  useEffect(() => { load(); }, [selectedSymbol]);
  useRefreshOnFocus(load);

  const filtered = signals.filter((s) => {
    if (selectedSymbol !== 'All' && s.symbol !== selectedSymbol) return false;
    if (selectedDir === 'Long'  && s.direction !== 'long')  return false;
    if (selectedDir === 'Short' && s.direction !== 'short') return false;
    if (s.confidence < minConfidence) return false;
    return true;
  });

  const activeSignals  = filtered.filter((s) => new Date(s.expires_at) > new Date());
  const expiredSignals = filtered.filter((s) => new Date(s.expires_at) <= new Date());

  // Stats
  const avgConfidence = activeSignals.length > 0
    ? activeSignals.reduce((s, sig) => s + sig.confidence, 0) / activeSignals.length
    : 0;
  const longCount  = activeSignals.filter((s) => s.direction === 'long').length;
  const shortCount = activeSignals.filter((s) => s.direction === 'short').length;

  return (
    <SafeAreaView style={styles.safe}>
      {/* ── Symbol filter ── */}
      <View style={styles.filterSection}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.filterRow}
        >
          {SYMBOLS.map((sym) => (
            <TouchableOpacity
              key={sym}
              style={[styles.chip, selectedSymbol === sym && styles.chipActive]}
              onPress={() => {
                setSelectedSymbol(sym);
                Haptics.selectionAsync();
              }}
            >
              <Text style={[styles.chipText, selectedSymbol === sym && styles.chipTextActive]}>
                {sym}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {/* Direction filter */}
        <View style={styles.dirRow}>
          {DIRECTIONS.map((dir) => (
            <TouchableOpacity
              key={dir}
              style={[styles.dirChip, selectedDir === dir && styles.dirChipActive]}
              onPress={() => setSelectedDir(dir)}
            >
              <Text style={[styles.dirChipText, selectedDir === dir && styles.dirChipTextActive]}>
                {dir}
              </Text>
            </TouchableOpacity>
          ))}

          {/* Confidence threshold */}
          <TouchableOpacity
            style={[styles.confChip, minConfidence > 0 && styles.confChipActive]}
            onPress={() => setMinConfidence(minConfidence === 0 ? 0.6 : minConfidence === 0.6 ? 0.8 : 0)}
          >
            <Ionicons name="filter" size={12} color={minConfidence > 0 ? COLORS.black : COLORS.textMuted} />
            <Text style={[styles.dirChipText, minConfidence > 0 && styles.dirChipTextActive]}>
              {minConfidence === 0 ? 'All' : `≥${(minConfidence * 100).toFixed(0)}%`}
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={load}
            tintColor={COLORS.accent}
            colors={[COLORS.accent]}
          />
        }
      >
        {/* ── Stats bar ── */}
        <Card style={styles.statsCard}>
          <View style={styles.statsRow}>
            <StatItem label="ACTIVE" value={String(activeSignals.length)} color={COLORS.accent} />
            <StatItem label="LONG" value={String(longCount)} color={COLORS.buy} />
            <StatItem label="SHORT" value={String(shortCount)} color={COLORS.sell} />
            <StatItem
              label="AVG CONF"
              value={`${(avgConfidence * 100).toFixed(0)}%`}
              color={confidenceColor(avgConfidence)}
            />
          </View>
        </Card>

        {/* ── Sentiment context ── */}
        {sentiment && <SentimentMeter sentiment={sentiment} maxHeadlines={2} />}

        {/* ── Active signals ── */}
        {activeSignals.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>
              ACTIVE SIGNALS ({activeSignals.length})
            </Text>
            {activeSignals.map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                onTrade={() => navigation.navigate('PlaceOrder', {
                  symbol: signal.symbol,
                  side: signal.direction === 'long' ? 'buy' : 'sell',
                })}
                onApprove={() => approveSignal(signal.id)}
              />
            ))}
          </View>
        )}

        {/* ── Expired signals ── */}
        {expiredSignals.length > 0 && (
          <View style={styles.section}>
            <Text style={[styles.sectionTitle, { color: COLORS.textDim }]}>
              EXPIRED ({expiredSignals.length})
            </Text>
            {expiredSignals.slice(0, 5).map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                onTrade={() => {}}
              />
            ))}
          </View>
        )}

        {filtered.length === 0 && !isLoading && (
          <View style={styles.empty}>
            <Ionicons name="pulse-outline" size={48} color={COLORS.textDim} />
            <Text style={styles.emptyTitle}>No signals</Text>
            <Text style={styles.emptyText}>
              {selectedSymbol !== 'All' || selectedDir !== 'All' || minConfidence > 0
                ? 'Try adjusting your filters'
                : 'Pull to refresh — signals are generated in real time'}
            </Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={statStyles.item}>
      <Text style={statStyles.label}>{label}</Text>
      <Text style={[statStyles.value, { color }]}>{value}</Text>
    </View>
  );
}

const statStyles = StyleSheet.create({
  item:  { flex: 1, alignItems: 'center' },
  label: { ...TEXT.labelSM, color: COLORS.textDim },
  value: { ...TEXT.numericMD, fontWeight: '800', marginTop: 3 },
});

const styles = StyleSheet.create({
  safe:          { flex: 1, backgroundColor: COLORS.background },
  filterSection: { backgroundColor: COLORS.surface, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  filterRow:     { paddingHorizontal: SPACING.md, paddingVertical: SPACING.sm, gap: SPACING.sm },
  chip:          { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.full, borderWidth: 1, borderColor: COLORS.border },
  chipActive:    { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  chipText:      { ...TEXT.bodySM, color: COLORS.textMuted, fontWeight: '600' },
  chipTextActive:{ color: COLORS.black, fontWeight: '800' },
  dirRow:        { flexDirection: 'row', paddingHorizontal: SPACING.md, paddingBottom: SPACING.sm, gap: SPACING.sm },
  dirChip:       { paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border },
  dirChipActive: { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  dirChipText:   { ...TEXT.caption, color: COLORS.textMuted, fontWeight: '600' },
  dirChipTextActive: { color: COLORS.black, fontWeight: '800' },
  confChip:      { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.sm, paddingVertical: 4, borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border },
  confChipActive:{ backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  content:       { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  statsCard:     { padding: SPACING.sm },
  statsRow:      { flexDirection: 'row', justifyContent: 'space-around' },
  section:       { gap: SPACING.sm },
  sectionTitle:  { ...TEXT.label, color: COLORS.textMuted },
  empty:         { alignItems: 'center', paddingVertical: SPACING.xxl, gap: SPACING.md },
  emptyTitle:    { ...TEXT.h3, color: COLORS.textMuted },
  emptyText:     { ...TEXT.body, color: COLORS.textDim, textAlign: 'center', lineHeight: 22 },
});
