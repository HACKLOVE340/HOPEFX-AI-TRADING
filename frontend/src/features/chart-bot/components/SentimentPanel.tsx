/**
 * SentimentPanel.tsx
 * High-intensity sentiment gauge + contextual news feed with
 * gold-specific impact scoring from NewsSentimentEngine.
 */

import React, { memo, useMemo } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import { useSentiment, useNews } from '../hooks/useChartData';
import { COLORS } from '../utils/design-tokens';
import {
  sentimentColor, impactColor, formatRelativeTime, formatConfidence,
} from '../utils/formatters';
import type { SentimentSnapshot, NewsItem } from '../types';

// ─── Sentiment Arc Gauge ──────────────────────────────────────────────────────

const SentimentArc = memo(({ snapshot }: { snapshot: SentimentSnapshot }) => {
  // score: -1 to +1 → angle: -135° to +135°
  const score     = snapshot.score;
  const color     = sentimentColor(score);
  const labelText = snapshot.label.replace('_', ' ').toUpperCase();

  const cx = 80, cy = 72, r = 56;
  const toRad = (d: number) => (d * Math.PI) / 180;

  // Arc from -135° to +135° (270° sweep)
  const arcStart = -135;
  const arcEnd   = 135;
  const arcPath  = (start: number, end: number, radius: number) => {
    const s = { x: cx + radius * Math.cos(toRad(start)), y: cy + radius * Math.sin(toRad(start)) };
    const e = { x: cx + radius * Math.cos(toRad(end)),   y: cy + radius * Math.sin(toRad(end))   };
    const large = Math.abs(end - start) > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
  };

  // Filled arc from start to needle position
  const filledEnd = arcStart + ((score + 1) / 2) * 270;
  const needleAngle = arcStart + ((score + 1) / 2) * 270;
  const nx = cx + (r - 10) * Math.cos(toRad(needleAngle));
  const ny = cy + (r - 10) * Math.sin(toRad(needleAngle));

  // Zone ticks
  const zones = [
    { angle: arcStart,        label: 'BEAR', color: COLORS.loss.base },
    { angle: arcStart + 67.5, label: '',     color: COLORS.neon.gold },
    { angle: arcStart + 135,  label: 'NEU',  color: COLORS.text.muted },
    { angle: arcStart + 202.5,label: '',     color: COLORS.neon.gold },
    { angle: arcEnd,          label: 'BULL', color: COLORS.profit.base },
  ];

  return (
    <div style={sg.arcWrapper}>
      <svg width={160} height={100} style={{ display: 'block', margin: '0 auto' }}>
        {/* Background arc */}
        <path
          d={arcPath(arcStart, arcEnd, r)}
          fill="none"
          stroke={COLORS.bg.elevated}
          strokeWidth={10}
          strokeLinecap="round"
        />
        {/* Filled arc */}
        <path
          d={arcPath(arcStart, filledEnd, r)}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          opacity={0.9}
        />
        {/* Zone ticks */}
        {zones.map((z, i) => {
          const tx = cx + (r + 6) * Math.cos(toRad(z.angle));
          const ty = cy + (r + 6) * Math.sin(toRad(z.angle));
          return z.label ? (
            <text key={i} x={tx} y={ty} textAnchor="middle" dominantBaseline="middle"
              fill={z.color} fontSize={7} fontFamily='"JetBrains Mono", monospace' fontWeight={700}>
              {z.label}
            </text>
          ) : (
            <circle key={i} cx={tx} cy={ty} r={1.5} fill={z.color} opacity={0.5} />
          );
        })}
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={5} fill={color} />
        {/* Score text */}
        <text x={cx} y={cy + 18} textAnchor="middle" fill={color}
          fontSize={18} fontFamily='"JetBrains Mono", monospace' fontWeight={700}>
          {score >= 0 ? '+' : ''}{(score * 100).toFixed(0)}
        </text>
        <text x={cx} y={cy + 30} textAnchor="middle" fill={color}
          fontSize={8} fontFamily='"JetBrains Mono", monospace' letterSpacing="0.08em">
          {labelText}
        </text>
      </svg>

      {/* Sub-scores */}
      <div style={sg.subScores}>
        <SubScore label="GOLD" value={snapshot.goldSpecificScore} />
        <SubScore label="USD"  value={snapshot.usdScore} />
        <SubScore label="GEO"  value={snapshot.geopoliticalScore} />
      </div>

      <div style={sg.confidence}>
        CONFIDENCE <span style={{ color: COLORS.neon.cyan }}>{formatConfidence(snapshot.confidence)}</span>
        &nbsp;·&nbsp;
        SOURCES <span style={{ color: COLORS.text.primary }}>{snapshot.sources}</span>
      </div>
    </div>
  );
});
SentimentArc.displayName = 'SentimentArc';

const SubScore = memo(({ label, value }: { label: string; value: number }) => {
  const color = sentimentColor(value);
  const pct   = ((value + 1) / 2) * 100;
  return (
    <div style={sg.subScoreItem}>
      <span style={sg.subLabel}>{label}</span>
      <div style={sg.subBar}>
        <div style={{ ...sg.subFill, width: `${pct}%`, background: color }} />
      </div>
      <span style={{ ...sg.subVal, color }}>
        {value >= 0 ? '+' : ''}{(value * 100).toFixed(0)}
      </span>
    </div>
  );
});
SubScore.displayName = 'SubScore';

// ─── News Feed ────────────────────────────────────────────────────────────────

const NewsCard = memo(({ item }: { item: NewsItem }) => {
  const sentColor  = sentimentColor(item.sentimentScore);
  const impColor   = impactColor(item.impactLabel);
  const impactPct  = item.goldImpactScore * 100;

  return (
    <div style={nc.card}>
      {/* Impact bar on left edge */}
      <div style={{ ...nc.impactBar, background: impColor, opacity: 0.6 + item.goldImpactScore * 0.4 }} />

      <div style={nc.body}>
        {/* Tags + time */}
        <div style={nc.meta}>
          <span style={{ ...nc.impactBadge, background: `${impColor}22`, color: impColor, border: `1px solid ${impColor}44` }}>
            {item.impactLabel.toUpperCase()}
          </span>
          {item.tags.slice(0, 2).map((t) => (
            <span key={t} style={nc.tag}>{t}</span>
          ))}
          <span style={nc.time}>{formatRelativeTime(item.publishedAt)}</span>
        </div>

        {/* Headline */}
        <div style={nc.headline}>{item.headline}</div>

        {/* Source + scores */}
        <div style={nc.footer}>
          <span style={nc.source}>{item.source}</span>
          <div style={nc.scores}>
            <span style={{ ...nc.score, color: sentColor }}>
              SENT {item.sentimentScore >= 0 ? '+' : ''}{(item.sentimentScore * 100).toFixed(0)}
            </span>
            <span style={{ ...nc.score, color: impColor }}>
              GOLD {impactPct.toFixed(0)}%
            </span>
          </div>
        </div>

        {/* Gold impact bar */}
        <div style={nc.goldBar}>
          <div style={{ ...nc.goldFill, width: `${impactPct}%`, background: impColor }} />
        </div>
      </div>
    </div>
  );
});
NewsCard.displayName = 'NewsCard';

// ─── Main Component ───────────────────────────────────────────────────────────

const SentimentPanel: React.FC = () => {
  const symbol       = useChartBotStore((s) => s.symbol);
  const sentStore    = useChartBotStore((s) => s.sentiment);
  const newsStore    = useChartBotStore((s) => s.news);

  const { data: sentFetched } = useSentiment(symbol.replace('/', ''));
  const { data: newsFetched } = useNews(symbol.replace('/', ''));

  const sentiment = sentStore ?? sentFetched;
  // Memoised because the ternary produces a new array reference on every
  // render when it falls through to `[]`, which makes the sort below re-run
  // every time regardless of whether any news changed.
  const news      = useMemo(
    () => (newsStore.length ? newsStore : (newsFetched ?? [])),
    [newsStore, newsFetched],
  );

  // Sort news: high impact first, then by recency
  const sortedNews = useMemo(() =>
    [...news].sort((a, b) => {
      const impactOrder = { high: 0, medium: 1, low: 2 };
      const ia = impactOrder[a.impactLabel] ?? 2;
      const ib = impactOrder[b.impactLabel] ?? 2;
      if (ia !== ib) return ia - ib;
      return b.publishedAt - a.publishedAt;
    }),
  [news]);

  return (
    <div style={sp.wrapper}>
      {/* Header */}
      <div style={sp.header}>
        <span style={sp.title}>SENTIMENT</span>
        {sentiment && (
          <span style={{ ...sp.badge, color: sentimentColor(sentiment.score), background: `${sentimentColor(sentiment.score)}18`, border: `1px solid ${sentimentColor(sentiment.score)}44` }}>
            {sentiment.label.replace('_', ' ').toUpperCase()}
          </span>
        )}
      </div>

      {/* Gauge */}
      {sentiment ? (
        <SentimentArc snapshot={sentiment} />
      ) : (
        <div style={sp.noData}>Awaiting sentiment data…</div>
      )}

      {/* News feed */}
      <div style={sp.newsHeader}>
        <span style={sp.newsTitle}>GOLD NEWS FEED</span>
        <span style={sp.newsCount}>{news.length} items</span>
      </div>

      <div style={sp.newsList}>
        {sortedNews.length === 0 ? (
          <div style={sp.noData}>No news items loaded.</div>
        ) : (
          sortedNews.map((item) => <NewsCard key={item.id} item={item} />)
        )}
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const sg: Record<string, React.CSSProperties> = {
  arcWrapper: { padding: '8px 12px 4px' },
  subScores: { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 },
  subScoreItem: { display: 'flex', alignItems: 'center', gap: 8 },
  subLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, letterSpacing: '0.08em', width: 28, flexShrink: 0 },
  subBar: { flex: 1, height: 4, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  subFill: { height: '100%', borderRadius: 2, transition: 'width 400ms ease' },
  subVal: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, width: 28, textAlign: 'right' as const },
  confidence: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, letterSpacing: '0.06em', marginTop: 8, textAlign: 'center' as const },
};

const nc: Record<string, React.CSSProperties> = {
  card: { display: 'flex', gap: 0, borderBottom: `1px solid ${COLORS.bg.border}`, position: 'relative' as const },
  impactBar: { width: 3, flexShrink: 0 },
  body: { flex: 1, padding: '8px 10px' },
  meta: { display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' as const, marginBottom: 4 },
  impactBadge: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, letterSpacing: '0.06em' },
  tag: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, background: COLORS.bg.elevated, padding: '1px 4px', borderRadius: 3 },
  time: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, marginLeft: 'auto' as const },
  headline: { fontFamily: '"Inter", sans-serif', fontSize: 12, color: COLORS.text.primary, lineHeight: 1.4, marginBottom: 5 },
  footer: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  source: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted },
  scores: { display: 'flex', gap: 8 },
  score: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700 },
  goldBar: { height: 2, background: COLORS.bg.elevated, borderRadius: 1, overflow: 'hidden' },
  goldFill: { height: '100%', borderRadius: 1, transition: 'width 400ms ease' },
};

const sp: Record<string, React.CSSProperties> = {
  wrapper: { background: COLORS.bg.surface, border: `1px solid ${COLORS.bg.border}`, borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column' as const },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px 8px', borderBottom: `1px solid ${COLORS.bg.border}` },
  title: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, color: COLORS.text.muted, letterSpacing: '0.12em' },
  badge: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, letterSpacing: '0.06em' },
  newsHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px 6px', borderTop: `1px solid ${COLORS.bg.border}` },
  newsTitle: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, color: COLORS.text.muted, letterSpacing: '0.1em' },
  newsCount: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted },
  newsList: { overflowY: 'auto' as const, maxHeight: 420, flex: 1 },
  noData: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.text.muted, padding: '20px', textAlign: 'center' as const },
};

export default memo(SentimentPanel);
