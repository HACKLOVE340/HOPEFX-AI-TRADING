/**
 * components/panels/SentimentGauge.tsx
 * News sentiment panel from NewsSentimentEngine.
 * Shows: bullish/bearish arc gauge, score, momentum, article feed.
 */

import React, { useMemo } from 'react';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { Badge } from '../ui/Badge';
import { sentimentColor, fmtRelative, cn } from '../../lib/utils';
import type { NewsArticle } from '../../types';

// ── SVG arc gauge ─────────────────────────────────────────────────────────────

function ArcGauge({ score }: { score: number }) {
  // Guard: clamp to [-1, 1] and treat NaN/Infinity as 0 (neutral).
  // A backend bug returning null or a non-finite value must not produce
  // NaN SVG coordinates that silently blank the gauge.
  const safeScore = Number.isFinite(score) ? Math.max(-1, Math.min(1, score)) : 0;

  const cx = 80, cy = 80, r = 60;
  const startAngle = 210; // degrees
  const sweepAngle = 120; // total arc = 120° each side

  // Needle angle: -1 → 210°, 0 → 270°, +1 → 330°
  const needleAngle = 270 + safeScore * sweepAngle;
  // Use safeScore for all downstream calculations
  const score = safeScore; // shadow param with validated value

  const toRad = (deg: number) => (deg * Math.PI) / 180;

  // Arc path helper
  const arcPath = (start: number, end: number, color: string, opacity = 1) => {
    const s = toRad(start);
    const e = toRad(end);
    const x1 = cx + r * Math.cos(s);
    const y1 = cy + r * Math.sin(s);
    const x2 = cx + r * Math.cos(e);
    const y2 = cy + r * Math.sin(e);
    const large = Math.abs(end - start) > 180 ? 1 : 0;
    return (
      <path
        d={`M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeLinecap="round"
        opacity={opacity}
      />
    );
  };

  // Needle
  const needleRad = toRad(needleAngle);
  const nx = cx + (r - 10) * Math.cos(needleRad);
  const ny = cy + (r - 10) * Math.sin(needleRad);
  const needleColor = sentimentColor(score);

  return (
    <svg width="160" height="100" viewBox="0 0 160 100" className="mx-auto">
      {/* Background arc */}
      {arcPath(startAngle, startAngle + sweepAngle * 2, '#1e2d3d')}
      {/* Bear arc (left half) */}
      {arcPath(startAngle, 270, '#ff1744', 0.7)}
      {/* Bull arc (right half) */}
      {arcPath(270, startAngle + sweepAngle * 2, '#00e676', 0.7)}
      {/* Active fill */}
      {score < 0
        ? arcPath(needleAngle, 270, '#ff1744')
        : arcPath(270, needleAngle, '#00e676')}
      {/* Needle */}
      <line
        x1={cx} y1={cy}
        x2={nx.toFixed(2)} y2={ny.toFixed(2)}
        stroke={needleColor}
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r="4" fill={needleColor} />
      {/* Labels */}
      <text x="18" y="92" fill="#ff1744" fontSize="9" fontFamily="monospace" fontWeight="600">BEAR</text>
      <text x="118" y="92" fill="#00e676" fontSize="9" fontFamily="monospace" fontWeight="600">BULL</text>
    </svg>
  );
}

// ── Article row ───────────────────────────────────────────────────────────────

function ArticleRow({ article }: { article: NewsArticle }) {
  const scoreColor = sentimentColor(article.sentiment_score);
  const variant =
    article.sentiment_label === 'bullish' ? 'bull' :
    article.sentiment_label === 'bearish' ? 'bear' : 'neutral';

  return (
    <div className="flex flex-col gap-1 py-2.5 border-b border-[#1e2d3d] last:border-0">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] text-slate-300 leading-snug line-clamp-2 flex-1">
          {article.headline}
        </p>
        <span
          className="font-mono tabular-nums text-[11px] font-semibold shrink-0"
          style={{ color: scoreColor }}
        >
          {Number.isFinite(article.sentiment_score)
            ? `${article.sentiment_score >= 0 ? '+' : ''}${article.sentiment_score.toFixed(2)}`
            : '—'}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={variant} dot>{article.sentiment_label}</Badge>
        <span className="text-[9px] text-slate-600 font-mono">{article.source}</span>
        <span className="text-[9px] text-slate-600 ml-auto">{fmtRelative(article.published_at)}</span>
        {/* sentiment_score guard: backend may return null/NaN for unscored articles */}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SentimentGauge() {
  const sentiment = useStore((s) => s.sentiment);

  const score    = sentiment?.signal.news_sentiment_score ?? 0;
  const momentum = sentiment?.signal.news_sentiment_momentum ?? 0;
  const articles = sentiment?.recent_articles ?? [];
  const bullRatio = sentiment?.signal.news_bullish_ratio ?? 0.5;
  const artCount  = sentiment?.signal.news_article_count_1h ?? 0;

  const label = score > 0.3 ? 'BULLISH' : score < -0.3 ? 'BEARISH' : 'NEUTRAL';
  const labelVariant = score > 0.3 ? 'bull' : score < -0.3 ? 'bear' : 'neutral';

  const headerRight = (
    <Badge variant={labelVariant} dot>{label}</Badge>
  );

  return (
    <Panel title="Sentiment" headerRight={headerRight} noPad bodyClass="p-0">
      <div className="flex flex-col h-full overflow-hidden">

        {/* Gauge */}
        <div className="px-4 pt-3 pb-2 border-b border-[#1e2d3d] shrink-0">
          <ArcGauge score={score} />

          {/* Score + stats row */}
          <div className="flex items-center justify-between mt-2 px-2">
            <div className="flex flex-col items-center">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Score</span>
              <span
                className="font-mono tabular-nums text-sm font-bold"
                style={{ color: sentimentColor(score) }}
              >
                {score >= 0 ? '+' : ''}{score.toFixed(3)}
              </span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Momentum</span>
              <span
                className={cn(
                  'font-mono tabular-nums text-xs font-semibold',
                  momentum >= 0 ? 'text-[#00e676]' : 'text-[#ff1744]',
                )}
              >
                {momentum >= 0 ? '▲' : '▼'} {Math.abs(momentum).toFixed(3)}
              </span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">Bull Ratio</span>
              <span className="font-mono tabular-nums text-xs text-[#00e676]">
                {(bullRatio * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-[9px] text-slate-600 uppercase tracking-wider">1h Articles</span>
              <span className="font-mono tabular-nums text-xs text-slate-300">
                {artCount}
              </span>
            </div>
          </div>
        </div>

        {/* Article feed */}
        <div className="flex-1 overflow-y-auto scrollbar-terminal px-4 py-1">
          {articles.length === 0 ? (
            <div className="flex items-center justify-center h-16 text-slate-600 text-xs">
              No recent articles
            </div>
          ) : (
            articles.map((a) => (
            <ArticleRow key={`${a.published_at}-${a.source}`} article={a} />
          ))
          )}
        </div>
      </div>
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const SentimentGaugeGuarded = withPanelGuard(SentimentGauge, 'Sentiment', 3);
