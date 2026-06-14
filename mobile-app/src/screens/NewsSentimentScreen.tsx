// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/NewsSentimentScreen.tsx
 * ================================
 * Real-time news feed with nuclear wordmap sentiment scoring.
 * Connected to: /api/news/feed, /api/sentiment/latest, /api/news/nuclear-score
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, StyleSheet,
  RefreshControl, TouchableOpacity, Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/apiClient';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../utils/theme';
import { Card } from '../components/Card';
import { LoadingSpinner } from '../components/LoadingSpinner';

interface NewsItem {
  id: string;
  title: string;
  source: string;
  published_at: string;
  url: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
  impact: 'high' | 'medium' | 'low';
  nuclear_score: number; // -100 to +100
  symbols: string[];
}

interface SentimentOverview {
  symbol: string;
  overall_score: number;
  news_count: number;
  bullish_pct: number;
  bearish_pct: number;
  neutral_pct: number;
  nuclear_alert: boolean;
  last_updated: string;
}

export function NewsSentimentScreen() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [sentiment, setSentiment] = useState<SentimentOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<'all' | 'high' | 'bullish' | 'bearish'>('all');

  const fetchData = useCallback(async () => {
    try {
      const [newsRes, sentRes] = await Promise.all([
        apiClient.get<{ articles: NewsItem[] }>('/api/news/feed', { params: { limit: 50 } }),
        apiClient.get<SentimentOverview>('/api/sentiment/latest', { params: { symbol: 'XAUUSD' } }),
      ]);
      setNews(newsRes.data.articles ?? []);
      setSentiment(sentRes.data);
    } catch (err) {
      console.error('News fetch error:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const onRefresh = () => { setRefreshing(true); fetchData(); };

  const filteredNews = news.filter(item => {
    if (filter === 'all') return true;
    if (filter === 'high') return item.impact === 'high';
    if (filter === 'bullish') return item.sentiment === 'bullish';
    if (filter === 'bearish') return item.sentiment === 'bearish';
    return true;
  });

  const sentimentColor = (score: number) =>
    score > 20 ? COLORS.buy : score < -20 ? COLORS.sell : COLORS.textMuted;

  const impactColor = (impact: string) =>
    impact === 'high' ? COLORS.sell : impact === 'medium' ? COLORS.accent : COLORS.textMuted;

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <LoadingSpinner />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.accent} />}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.title}>News & Sentiment</Text>
          <Text style={styles.subtitle}>Nuclear Wordmap Scoring</Text>
        </View>

        {/* Sentiment Overview Card */}
        {sentiment && (
          <Card style={styles.sentimentCard}>
            <View style={styles.sentimentHeader}>
              <Text style={styles.sentimentSymbol}>{sentiment.symbol}</Text>
              {sentiment.nuclear_alert && (
                <View style={styles.nuclearBadge}>
                  <Ionicons name="warning" size={12} color={COLORS.sell} />
                  <Text style={styles.nuclearText}>NUCLEAR</Text>
                </View>
              )}
            </View>
            <View style={styles.sentimentScore}>
              <Text style={[styles.scoreValue, { color: sentimentColor(sentiment.overall_score) }]}>
                {sentiment.overall_score > 0 ? '+' : ''}{sentiment.overall_score}
              </Text>
              <Text style={styles.scoreLabel}>Overall Score</Text>
            </View>
            <View style={styles.sentimentBar}>
              <View style={[styles.barSegment, { flex: sentiment.bullish_pct, backgroundColor: COLORS.buy }]} />
              <View style={[styles.barSegment, { flex: sentiment.neutral_pct, backgroundColor: COLORS.textMuted }]} />
              <View style={[styles.barSegment, { flex: sentiment.bearish_pct, backgroundColor: COLORS.sell }]} />
            </View>
            <View style={styles.sentimentLegend}>
              <Text style={[styles.legendText, { color: COLORS.buy }]}>
                {sentiment.bullish_pct.toFixed(0)}% Bull
              </Text>
              <Text style={[styles.legendText, { color: COLORS.textMuted }]}>
                {sentiment.neutral_pct.toFixed(0)}% Neutral
              </Text>
              <Text style={[styles.legendText, { color: COLORS.sell }]}>
                {sentiment.bearish_pct.toFixed(0)}% Bear
              </Text>
            </View>
            <Text style={styles.newsCount}>{sentiment.news_count} articles analyzed</Text>
          </Card>
        )}

        {/* Filter Tabs */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterRow}>
          {(['all', 'high', 'bullish', 'bearish'] as const).map(f => (
            <TouchableOpacity
              key={f}
              style={[styles.filterChip, filter === f && styles.filterChipActive]}
              onPress={() => setFilter(f)}
            >
              <Text style={[styles.filterText, filter === f && styles.filterTextActive]}>
                {f === 'all' ? 'All' : f === 'high' ? 'High Impact' : f.charAt(0).toUpperCase() + f.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {/* News Feed */}
        <View style={styles.newsList}>
          {filteredNews.map(item => (
            <TouchableOpacity
              key={item.id}
              style={styles.newsCard}
              onPress={() => Linking.openURL(item.url)}
              activeOpacity={0.7}
            >
              <View style={styles.newsHeader}>
                <View style={[styles.impactDot, { backgroundColor: impactColor(item.impact) }]} />
                <Text style={styles.newsSource}>{item.source}</Text>
                <Text style={styles.newsTime}>
                  {new Date(item.published_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </Text>
              </View>
              <Text style={styles.newsTitle} numberOfLines={2}>{item.title}</Text>
              <View style={styles.newsFooter}>
                <View style={[
                  styles.sentimentChip,
                  { backgroundColor: item.sentiment === 'bullish' ? `${COLORS.buy}20` :
                    item.sentiment === 'bearish' ? `${COLORS.sell}20` : `${COLORS.textMuted}20` }
                ]}>
                  <Ionicons
                    name={item.sentiment === 'bullish' ? 'trending-up' : item.sentiment === 'bearish' ? 'trending-down' : 'remove'}
                    size={12}
                    color={item.sentiment === 'bullish' ? COLORS.buy : item.sentiment === 'bearish' ? COLORS.sell : COLORS.textMuted}
                  />
                  <Text style={[styles.sentimentChipText, {
                    color: item.sentiment === 'bullish' ? COLORS.buy : item.sentiment === 'bearish' ? COLORS.sell : COLORS.textMuted
                  }]}>
                    {item.sentiment}
                  </Text>
                </View>
                <Text style={[styles.nuclearScoreText, { color: sentimentColor(item.nuclear_score) }]}>
                  Score: {item.nuclear_score > 0 ? '+' : ''}{item.nuclear_score}
                </Text>
                {item.symbols.length > 0 && (
                  <View style={styles.symbolsRow}>
                    {item.symbols.slice(0, 3).map(s => (
                      <Text key={s} style={styles.symbolTag}>{s}</Text>
                    ))}
                  </View>
                )}
              </View>
            </TouchableOpacity>
          ))}
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
  sentimentCard: { marginHorizontal: SPACING.lg, marginBottom: SPACING.md, padding: SPACING.lg },
  sentimentHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: SPACING.sm },
  sentimentSymbol: { ...TEXT.h2, color: COLORS.text },
  nuclearBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: `${COLORS.sell}20`, paddingHorizontal: 8, paddingVertical: 4, borderRadius: RADIUS.sm },
  nuclearText: { ...TEXT.captionSM, color: COLORS.sell, fontWeight: '800' },
  sentimentScore: { alignItems: 'center', marginBottom: SPACING.md },
  scoreValue: { fontSize: 42, fontWeight: '900' },
  scoreLabel: { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  sentimentBar: { flexDirection: 'row', height: 6, borderRadius: 3, overflow: 'hidden', marginBottom: SPACING.sm },
  barSegment: { height: '100%' },
  sentimentLegend: { flexDirection: 'row', justifyContent: 'space-between' },
  legendText: { ...TEXT.captionSM, fontWeight: '600' },
  newsCount: { ...TEXT.captionSM, color: COLORS.textMuted, textAlign: 'center', marginTop: SPACING.sm },
  filterRow: { paddingHorizontal: SPACING.lg, marginBottom: SPACING.md },
  filterChip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: RADIUS.md, backgroundColor: COLORS.surface, marginRight: 8, borderWidth: 1, borderColor: COLORS.border },
  filterChipActive: { backgroundColor: `${COLORS.accent}20`, borderColor: COLORS.accent },
  filterText: { ...TEXT.captionSM, color: COLORS.textMuted, fontWeight: '600' },
  filterTextActive: { color: COLORS.accent },
  newsList: { paddingHorizontal: SPACING.lg, paddingBottom: SPACING.xl },
  newsCard: { backgroundColor: COLORS.surface, borderRadius: RADIUS.lg, padding: SPACING.md, marginBottom: SPACING.sm, borderWidth: 1, borderColor: COLORS.border },
  newsHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: 6 },
  impactDot: { width: 6, height: 6, borderRadius: 3, marginRight: 6 },
  newsSource: { ...TEXT.captionSM, color: COLORS.textMuted, fontWeight: '600', flex: 1 },
  newsTime: { ...TEXT.captionSM, color: COLORS.textMuted },
  newsTitle: { ...TEXT.body, color: COLORS.text, fontWeight: '600', marginBottom: 8 },
  newsFooter: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sentimentChip: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.sm },
  sentimentChipText: { ...TEXT.captionSM, fontWeight: '700', textTransform: 'capitalize' },
  nuclearScoreText: { ...TEXT.captionSM, fontWeight: '700' },
  symbolsRow: { flexDirection: 'row', gap: 4, marginLeft: 'auto' },
  symbolTag: { ...TEXT.captionSM, color: COLORS.accent, backgroundColor: `${COLORS.accent}15`, paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.sm, fontWeight: '600' },
});
