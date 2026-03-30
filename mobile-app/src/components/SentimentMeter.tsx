// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/SentimentMeter.tsx
 * ==============================
 * Visual sentiment intensity meter with score bar, regime badge,
 * and top headlines from NewsSentimentEngine.
 */

import React, { useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking } from 'react-native';
import Animated, {
  useSharedValue, useAnimatedStyle, withTiming, Easing,
} from 'react-native-reanimated';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../utils/theme';
import { SentimentData } from '../types';

interface Props {
  sentiment: SentimentData | null;
  maxHeadlines?: number;
}

export function SentimentMeter({ sentiment, maxHeadlines = 3 }: Props) {
  // score is -1 to +1; map to 0–1 for bar
  const barProgress = useSharedValue(0.5);

  useEffect(() => {
    if (sentiment) {
      barProgress.value = withTiming((sentiment.score + 1) / 2, {
        duration: 700,
        easing: Easing.out(Easing.cubic),
      });
    }
  }, [sentiment?.score]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${barProgress.value * 100}%` as any,
  }));

  const score   = sentiment?.score ?? 0;
  const regime  = sentiment?.regime ?? 'neutral';
  const intensity = sentiment?.intensity ?? 0;

  const regimeColor =
    regime === 'bullish' ? COLORS.profit :
    regime === 'bearish' ? COLORS.loss :
    regime === 'mixed'   ? COLORS.warning : COLORS.textMuted;

  const regimeIcon =
    regime === 'bullish' ? 'trending-up' :
    regime === 'bearish' ? 'trending-down' :
    regime === 'mixed'   ? 'swap-horizontal' : 'remove';

  const scoreColor = score > 0.2 ? COLORS.profit : score < -0.2 ? COLORS.loss : COLORS.textMuted;

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>SENTIMENT</Text>
        <View style={[styles.regimeBadge, { borderColor: regimeColor + '55', backgroundColor: regimeColor + '15' }]}>
          <Ionicons name={regimeIcon as any} size={12} color={regimeColor} />
          <Text style={[styles.regimeText, { color: regimeColor }]}>{regime.toUpperCase()}</Text>
        </View>
      </View>

      {/* Score display */}
      <View style={styles.scoreRow}>
        <Text style={[styles.scoreValue, { color: scoreColor }]}>
          {score >= 0 ? '+' : ''}{score.toFixed(3)}
        </Text>
        <View style={styles.statsCol}>
          <Text style={styles.statLine}>
            <Text style={styles.statLabel}>Bullish  </Text>
            <Text style={[styles.statVal, { color: COLORS.profit }]}>
              {((sentiment?.bullish_ratio ?? 0) * 100).toFixed(0)}%
            </Text>
          </Text>
          <Text style={styles.statLine}>
            <Text style={styles.statLabel}>Bearish  </Text>
            <Text style={[styles.statVal, { color: COLORS.loss }]}>
              {((sentiment?.bearish_ratio ?? 0) * 100).toFixed(0)}%
            </Text>
          </Text>
          <Text style={styles.statLine}>
            <Text style={styles.statLabel}>Articles </Text>
            <Text style={styles.statVal}>{sentiment?.article_count_1h ?? 0}/h</Text>
          </Text>
        </View>
      </View>

      {/* Sentiment bar: bearish ←——→ bullish */}
      <View style={styles.barSection}>
        <Text style={[styles.barEndLabel, { color: COLORS.loss }]}>BEAR</Text>
        <View style={styles.barTrack}>
          {/* Center marker */}
          <View style={styles.barCenter} />
          <Animated.View style={[
            styles.barFill,
            barStyle,
            { backgroundColor: score >= 0 ? COLORS.profit : COLORS.loss },
          ]} />
        </View>
        <Text style={[styles.barEndLabel, { color: COLORS.profit }]}>BULL</Text>
      </View>

      {/* Intensity indicator */}
      <View style={styles.intensityRow}>
        <Text style={styles.intensityLabel}>INTENSITY</Text>
        <View style={styles.intensityDots}>
          {[0.2, 0.4, 0.6, 0.8, 1.0].map((threshold) => (
            <View
              key={threshold}
              style={[
                styles.intensityDot,
                { backgroundColor: intensity >= threshold ? COLORS.warning : COLORS.border },
              ]}
            />
          ))}
        </View>
        <Text style={[styles.intensityValue, { color: intensity > 0.6 ? COLORS.warning : COLORS.textMuted }]}>
          {(intensity * 100).toFixed(0)}%
        </Text>
      </View>

      {/* Top headlines */}
      {sentiment?.top_headlines && sentiment.top_headlines.length > 0 && (
        <View style={styles.headlines}>
          <Text style={styles.headlinesTitle}>TOP HEADLINES</Text>
          {sentiment.top_headlines.slice(0, maxHeadlines).map((h) => (
            <TouchableOpacity
              key={h.id}
              style={styles.headline}
              onPress={() => h.url && Linking.openURL(h.url)}
              activeOpacity={0.7}
            >
              <View style={[styles.headlineSentDot, {
                backgroundColor: h.sentiment_score > 0.1 ? COLORS.profit :
                                  h.sentiment_score < -0.1 ? COLORS.loss : COLORS.textMuted,
              }]} />
              <View style={styles.headlineContent}>
                <Text style={styles.headlineTitle} numberOfLines={2}>{h.title}</Text>
                <View style={styles.headlineMeta}>
                  <Text style={styles.headlineSource}>{h.source}</Text>
                  {h.impact === 'high' && (
                    <View style={styles.highImpactBadge}>
                      <Text style={styles.highImpactText}>HIGH IMPACT</Text>
                    </View>
                  )}
                </View>
              </View>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container:       {
    backgroundColor: COLORS.surface, borderRadius: RADIUS.xl,
    padding: SPACING.md, borderWidth: 1, borderColor: COLORS.border,
    gap: SPACING.sm, ...SHADOW.md,
  },
  header:          { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title:           { ...TEXT.label, color: COLORS.textMuted },
  regimeBadge:     { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: SPACING.sm, paddingVertical: 3, borderRadius: RADIUS.full, borderWidth: 1 },
  regimeText:      { ...TEXT.labelSM, fontSize: 10 },
  scoreRow:        { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  scoreValue:      { ...TEXT.displayMD, fontWeight: '900', width: 90 },
  statsCol:        { flex: 1, gap: 3 },
  statLine:        { flexDirection: 'row' },
  statLabel:       { ...TEXT.caption, color: COLORS.textMuted, width: 60 },
  statVal:         { ...TEXT.numericXS, color: COLORS.text },
  barSection:      { flexDirection: 'row', alignItems: 'center', gap: SPACING.xs },
  barEndLabel:     { ...TEXT.labelSM, width: 32, textAlign: 'center' },
  barTrack:        { flex: 1, height: 8, backgroundColor: COLORS.border, borderRadius: RADIUS.full, overflow: 'hidden', position: 'relative' },
  barCenter:       { position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, backgroundColor: COLORS.borderBright, zIndex: 1 },
  barFill:         { height: '100%', borderRadius: RADIUS.full },
  intensityRow:    { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  intensityLabel:  { ...TEXT.labelSM, color: COLORS.textDim, width: 70 },
  intensityDots:   { flexDirection: 'row', gap: 4, flex: 1 },
  intensityDot:    { width: 10, height: 10, borderRadius: 5 },
  intensityValue:  { ...TEXT.numericXS, width: 36, textAlign: 'right' },
  headlines:       { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACING.sm, gap: SPACING.sm },
  headlinesTitle:  { ...TEXT.labelSM, color: COLORS.textDim },
  headline:        { flexDirection: 'row', gap: SPACING.sm, alignItems: 'flex-start' },
  headlineSentDot: { width: 6, height: 6, borderRadius: 3, marginTop: 5 },
  headlineContent: { flex: 1, gap: 3 },
  headlineTitle:   { ...TEXT.bodySM, color: COLORS.text, lineHeight: 17 },
  headlineMeta:    { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  headlineSource:  { ...TEXT.caption, color: COLORS.textMuted },
  highImpactBadge: { backgroundColor: COLORS.warningDim, paddingHorizontal: 5, paddingVertical: 1, borderRadius: RADIUS.xs, borderWidth: 1, borderColor: COLORS.warning + '44' },
  highImpactText:  { ...TEXT.captionSM, color: COLORS.warning, fontSize: 9 },
});
