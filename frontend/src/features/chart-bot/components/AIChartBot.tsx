/**
 * AIChartBot.tsx
 * True AI Chart Analysis Bot — user clicks any part of the chart and
 * the AI instantly delivers a professional, contextual explanation:
 * current regime, key driving features, confidence level, risk assessment,
 * and recommended action. Powered by the orchestrator ML signals.
 */

import React, { useEffect, useRef, memo, useCallback } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import { useAIAnalysis } from '../hooks/useChartData';
import { COLORS } from '../utils/design-tokens';
import { extractApiError } from '../../../lib/utils';
import {
  formatPrice, formatDateTime, formatConfidence, confidenceLabel,
  regimeLabel, regimeColor, confidenceColor,
} from '../utils/formatters';
import type { AIAnalysis, ChartClickContext } from '../types';

// ─── Typing animation hook ────────────────────────────────────────────────────

function useTypewriter(text: string, speed = 18) {
  const [displayed, setDisplayed] = React.useState('');
  const indexRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    indexRef.current = 0;
    setDisplayed('');
    const tick = () => {
      if (indexRef.current < text.length) {
        setDisplayed(text.slice(0, indexRef.current + 1));
        indexRef.current++;
        timerRef.current = setTimeout(tick, speed);
      }
    };
    timerRef.current = setTimeout(tick, speed);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [text, speed]);

  return displayed;
}

// ─── Regime Badge ─────────────────────────────────────────────────────────────

const RegimeBadge = memo(({ regime, confidence }: { regime: string; confidence: number }) => {
  const color = regimeColor(regime);
  return (
    <div style={{ ...ab.regimeBadge, background: `${color}18`, border: `1px solid ${color}44`, color }}>
      <span style={abDynamic.regimeDot(color)} />
      {regimeLabel(regime)}
      <span style={{ ...ab.regimeConf, color: `${color}cc` }}>{formatConfidence(confidence)}</span>
    </div>
  );
});
RegimeBadge.displayName = 'RegimeBadge';

// ─── Action Badge ─────────────────────────────────────────────────────────────

const ActionBadge = memo(({ action, confidence }: { action: string; confidence: number }) => {
  const colorMap: Record<string, string> = {
    buy:  COLORS.profit.base,
    sell: COLORS.loss.base,
    hold: COLORS.neon.gold,
    wait: COLORS.text.muted,
  };
  const color = colorMap[action] ?? COLORS.text.muted;
  return (
    <div style={{ ...ab.actionBadge, background: `${color}18`, border: `1px solid ${color}55` }}>
      <span style={{ ...ab.actionText, color }}>{action.toUpperCase()}</span>
      <div style={ab.confBar}>
        <div style={{ ...ab.confFill, width: `${confidence * 100}%`, background: color }} />
      </div>
      <span style={{ ...ab.confLabel, color }}>{confidenceLabel(confidence)}</span>
    </div>
  );
});
ActionBadge.displayName = 'ActionBadge';

// ─── Feature Importance Bar ───────────────────────────────────────────────────

const FeatureBar = memo(({ name, importance, direction }: { name: string; importance: number; direction: string }) => {
  const color = direction === 'bullish' ? COLORS.profit.base
              : direction === 'bearish' ? COLORS.loss.base
              : COLORS.text.muted;
  return (
    <div style={ab.featureRow}>
      <span style={ab.featureName}>{name}</span>
      <div style={ab.featureBarBg}>
        <div style={{ ...ab.featureBarFill, width: `${importance * 100}%`, background: color }} />
      </div>
      <span style={{ ...ab.featureImportance, color }}>{(importance * 100).toFixed(0)}%</span>
    </div>
  );
});
FeatureBar.displayName = 'FeatureBar';

// ─── Price Targets ────────────────────────────────────────────────────────────

const PriceTargets = memo(({ targets, current }: { targets: AIAnalysis['priceTargets']; current: number }) => (
  <div style={ab.targetsGrid}>
    <TargetItem label="BULL" price={targets.bull} current={current} color={COLORS.profit.base} />
    <TargetItem label="BASE" price={targets.base} current={current} color={COLORS.neon.cyan} />
    <TargetItem label="BEAR" price={targets.bear} current={current} color={COLORS.loss.base} />
  </div>
));
PriceTargets.displayName = 'PriceTargets';

const TargetItem = memo(({ label, price, current, color }: { label: string; price: number; current: number; color: string }) => {
  const diff    = price - current;
  const diffPct = (diff / current) * 100;
  return (
    <div style={{ ...ab.targetItem, border: `1px solid ${color}33` }}>
      <span style={{ ...ab.targetLabel, color }}>{label}</span>
      <span style={{ ...ab.targetPrice, color }}>{formatPrice(price)}</span>
      <span style={{ ...ab.targetDiff, color: diff >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
        {diff >= 0 ? '+' : ''}{diffPct.toFixed(2)}%
      </span>
    </div>
  );
});
TargetItem.displayName = 'TargetItem';

// ─── Analysis Panel ───────────────────────────────────────────────────────────

// ─── Provenance strip ─────────────────────────────────────────────────────────

const Provenance = memo(({ analysis }: { analysis: AIAnalysis }) => {
  const degraded = analysis.degraded === true;
  const bars = analysis.barsAnalyzed;
  const model = analysis.modelAvailable ? (analysis.modelVersion ?? 'model') : 'no model';
  return (
    <div style={{ ...ab.provenance, ...(degraded ? ab.provenanceDegraded : null) }}>
      <span style={ab.provItem}>{degraded ? '⚠ DEGRADED' : '● LIVE'}</span>
      <span style={ab.provItem}>model: {model}</span>
      {bars !== undefined && <span style={ab.provItem}>bars: {bars}</span>}
      {analysis.dataSource && <span style={ab.provItem}>src: {analysis.dataSource}</span>}
    </div>
  );
});
Provenance.displayName = 'Provenance';

// ─── Analysis Panel ───────────────────────────────────────────────────────────

const AnalysisPanel = memo(({ analysis }: { analysis: AIAnalysis }) => {
  const summary = useTypewriter(analysis.summary, 14);

  // Server-supplied model importances win; the nearest signal's own features
  // are the fallback so an older cached payload still renders something real.
  const featureBars = React.useMemo(() => {
    const src = analysis.features?.length
      ? analysis.features
      : (analysis.context.nearestSignal?.features ?? []);
    return [...src].sort((a, b) => b.importance - a.importance).slice(0, 6);
  }, [analysis.features, analysis.context.nearestSignal]);

  return (
    <div style={ab.analysisPanel}>
      {/* Where this answer came from — shown before the answer itself, so a
          placeholder can never be mistaken for a read of the market. */}
      <Provenance analysis={analysis} />

      {/* Regime + Action row */}
      <div style={ab.topRow}>
        <RegimeBadge regime={analysis.regime} confidence={analysis.regimeConfidence} />
        <ActionBadge action={analysis.recommendedAction} confidence={analysis.actionConfidence} />
      </div>

      {/* Summary with typewriter */}
      <div style={ab.summaryBox}>
        <span style={ab.summaryLabel}>AI ANALYSIS</span>
        <p style={ab.summaryText}>{summary}<span style={ab.cursor}>|</span></p>
      </div>

      {/* Key drivers */}
      {analysis.keyDrivers.length > 0 && (
        <div style={ab.section}>
          <span style={ab.sectionLabel}>KEY DRIVERS</span>
          <ul style={ab.driverList}>
            {analysis.keyDrivers.map((d, i) => (
              <li key={i} style={ab.driverItem}>
                <span style={ab.driverDot} />
                {d}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Feature importance — from the model that produced this verdict.
          Falls back to the nearest ML signal's own features when the server
          did not supply any. Previously this read only
          `context.nearestSignal.features`, which is part of the REQUEST and was
          hard-coded null at the only place a click context is built, so the
          section could never render. */}
      {featureBars.length > 0 && (
        <div style={ab.section}>
          <span style={ab.sectionLabel}>ML FEATURE IMPORTANCE · {analysis.modelVersion ?? 'model'}</span>
          <div style={{ marginTop: 6 }}>
            {featureBars.map((f) => (
              <FeatureBar key={f.name} name={f.name} importance={f.importance} direction={f.direction} />
            ))}
          </div>
          <span style={ab.featureNote}>
            Global model importance — which inputs this model relies on overall, not attribution for this call.
          </span>
        </div>
      )}

      {/* Price targets */}
      <div style={ab.section}>
        <span style={ab.sectionLabel}>PRICE TARGETS · {analysis.timeHorizon}</span>
        <PriceTargets targets={analysis.priceTargets} current={analysis.context.price} />
      </div>

      {/* Risk assessment */}
      <div style={ab.riskBox}>
        <span style={ab.sectionLabel}>RISK ASSESSMENT</span>
        <p style={ab.riskText}>{analysis.riskAssessment}</p>
      </div>

      {/* Warnings */}
      {analysis.warnings.length > 0 && (
        <div style={ab.warningsBox}>
          {analysis.warnings.map((w, i) => (
            <div key={i} style={ab.warning}>
              <span style={ab.warnIcon}>⚠</span>
              {w}
            </div>
          ))}
        </div>
      )}

      <div style={ab.timestamp}>
        Generated {formatDateTime(analysis.timestamp)}
      </div>
    </div>
  );
});
AnalysisPanel.displayName = 'AnalysisPanel';

// ─── Click Prompt ─────────────────────────────────────────────────────────────

const ClickPrompt = memo(() => (
  <div style={ab.clickPrompt}>
    <div style={ab.promptIcon}>
      <svg width={32} height={32} viewBox="0 0 32 32" fill="none">
        <circle cx={16} cy={16} r={15} stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.4} />
        <circle cx={16} cy={16} r={10} stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.3} />
        <circle cx={16} cy={16} r={4}  fill={COLORS.neon.purple} opacity={0.8} />
        <line x1={16} y1={2}  x2={16} y2={8}  stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.5} />
        <line x1={16} y1={24} x2={16} y2={30} stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.5} />
        <line x1={2}  y1={16} x2={8}  y2={16} stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.5} />
        <line x1={24} y1={16} x2={30} y2={16} stroke={COLORS.neon.purple} strokeWidth={1} opacity={0.5} />
      </svg>
    </div>
    <p style={ab.promptTitle}>Click any point on the chart</p>
    <p style={ab.promptSub}>
      The AI will instantly analyse the market regime, ML signal confidence,
      key driving features, risk assessment, and recommended action at that price level.
    </p>
  </div>
));
ClickPrompt.displayName = 'ClickPrompt';

// ─── Loading State ────────────────────────────────────────────────────────────

const AnalysisLoading = memo(({ context }: { context: ChartClickContext }) => (
  <div style={ab.loadingPanel}>
    <div style={ab.loadingHeader}>
      <div style={ab.loadingSpinner} />
      <span style={ab.loadingTitle}>ANALYSING MARKET CONTEXT</span>
    </div>
    <div style={ab.loadingPrice}>
      <span style={ab.loadingLabel}>PRICE</span>
      <span style={ab.loadingVal}>{formatPrice(context.price)}</span>
    </div>
    <div style={ab.loadingPrice}>
      <span style={ab.loadingLabel}>TIME</span>
      <span style={ab.loadingVal}>{formatDateTime(context.time)}</span>
    </div>
    <div style={ab.loadingSteps}>
      {['Reading ML signals…', 'Computing regime…', 'Evaluating risk…', 'Generating analysis…'].map((step, i) => (
        <div key={i} style={ab.loadingStep}>
          <div style={ab.loadingStepDot} />
          <span style={ab.loadingStepText}>{step}</span>
        </div>
      ))}
    </div>
  </div>
));
AnalysisLoading.displayName = 'AnalysisLoading';

// ─── Main Component ───────────────────────────────────────────────────────────

const AIChartBot: React.FC = () => {
  const analysis    = useChartBotStore((s) => s.aiAnalysis);
  const pending     = useChartBotStore((s) => s.aiPending);
  const error       = useChartBotStore((s) => s.aiError);
  const context     = useChartBotStore((s) => s.clickContext);
  const setAnalysis = useChartBotStore((s) => s.setAIAnalysis);
  const setPending  = useChartBotStore((s) => s.setAIPending);
  const setError    = useChartBotStore((s) => s.setAIError);
  const clearAI     = useChartBotStore((s) => s.clearAI);

  const { mutate: requestAnalysis } = useAIAnalysis();

  // Auto-trigger analysis when click context changes
  useEffect(() => {
    if (!context) return;
    setPending(true);
    requestAnalysis(context, {
      onSuccess: (data) => setAnalysis(data),
      onError:   (err)  => setError(extractApiError(err, 'Analysis failed')),
    });
  }, [context, requestAnalysis, setPending, setAnalysis, setError]);

  const handleClear = useCallback(() => clearAI(), [clearAI]);

  return (
    <div style={ab.wrapper}>
      {/* Header */}
      <div style={ab.header}>
        <div style={ab.headerLeft}>
          <div style={ab.aiDot} />
          <span style={ab.title}>AI CHART BOT</span>
          {pending && <span style={ab.pendingBadge}>THINKING…</span>}
        </div>
        {(analysis || context) && (
          <button onClick={handleClear} style={ab.clearBtn}>CLEAR</button>
        )}
      </div>

      {/* Content */}
      <div style={ab.content}>
        {pending && context ? (
          <AnalysisLoading context={context} />
        ) : error ? (
          <div style={ab.errorBox}>
            <span style={ab.errorIcon}>✕</span>
            <span style={ab.errorText}>{error}</span>
            <button onClick={handleClear} style={ab.retryBtn}>RETRY</button>
          </div>
        ) : analysis ? (
          <AnalysisPanel analysis={analysis} />
        ) : (
          <ClickPrompt />
        )}
      </div>
    </div>
  );
};

// ─── Dynamic style helpers ────────────────────────────────────────────────────

const abDynamic = {
  regimeDot: (color: string): React.CSSProperties => ({
    width: 6, height: 6, borderRadius: '50%',
    background: color,
    boxShadow: `0 0 6px ${color}`,
    flexShrink: 0,
  }),
};

// ─── Static styles ────────────────────────────────────────────────────────────

const ab: Record<string, React.CSSProperties> = {
  wrapper: {
    background: COLORS.bg.surface,
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 8,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px 8px',
    borderBottom: `1px solid ${COLORS.bg.border}`,
    background: COLORS.bg.elevated,
  },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 8 },
  aiDot: {
    width: 8, height: 8, borderRadius: '50%',
    background: COLORS.neon.purple,
    boxShadow: `0 0 8px ${COLORS.neon.purple}`,
    animation: 'pulse 2s infinite',
  },
  title: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10, fontWeight: 700,
    color: COLORS.neon.purple,
    letterSpacing: '0.12em',
  },
  pendingBadge: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 8, color: COLORS.neon.cyan,
    background: `${COLORS.neon.cyan}18`,
    border: `1px solid ${COLORS.neon.cyan}44`,
    padding: '1px 6px', borderRadius: 3,
    letterSpacing: '0.08em',
  },
  clearBtn: {
    background: 'transparent',
    border: `1px solid ${COLORS.bg.divider}`,
    borderRadius: 4,
    color: COLORS.text.muted,
    cursor: 'pointer',
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9, padding: '3px 8px',
    letterSpacing: '0.06em',
  },
  content: { flex: 1, overflowY: 'auto' },
  analysisPanel: { padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 },
  topRow: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  regimeBadge: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '5px 10px', borderRadius: 6,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
  },
  regimeConf: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, marginLeft: 4 },
  actionBadge: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '5px 10px', borderRadius: 6, flex: 1,
  },
  actionText: { fontFamily: '"JetBrains Mono", monospace', fontSize: 13, fontWeight: 900, letterSpacing: '0.08em' },
  confBar: { flex: 1, height: 4, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  confFill: { height: '100%', borderRadius: 2, transition: 'width 600ms ease' },
  confLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, letterSpacing: '0.06em', flexShrink: 0 },
  summaryBox: {
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.divider}`,
    borderRadius: 6, padding: '10px 12px',
  },
  summaryLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 8, color: COLORS.neon.purple,
    letterSpacing: '0.12em', display: 'block', marginBottom: 6,
  },
  summaryText: {
    fontFamily: '"Inter", sans-serif',
    fontSize: 12, color: COLORS.text.primary,
    lineHeight: 1.6, margin: 0,
  },
  cursor: { color: COLORS.neon.purple, animation: 'blink 1s step-end infinite' },
  section: { display: 'flex', flexDirection: 'column', gap: 4 },
  sectionLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 8, color: COLORS.text.muted,
    letterSpacing: '0.12em', textTransform: 'uppercase',
  },
  driverList: { margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 },
  driverItem: {
    display: 'flex', alignItems: 'flex-start', gap: 6,
    fontFamily: '"Inter", sans-serif', fontSize: 11,
    color: COLORS.text.secondary, lineHeight: 1.4,
  },
  driverDot: { width: 4, height: 4, borderRadius: '50%', background: COLORS.neon.cyan, marginTop: 5, flexShrink: 0 },
  provenance: {
    display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center',
    padding: '4px 8px', borderRadius: 4,
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.divider}`,
  },
  provenanceDegraded: {
    background: `${COLORS.neon.amber}0d`,
    border: `1px solid ${COLORS.neon.amber}44`,
  },
  provItem: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 8, color: COLORS.text.muted, letterSpacing: '0.06em',
  },
  featureNote: {
    fontFamily: '"Inter", sans-serif', fontSize: 9,
    color: COLORS.text.muted, lineHeight: 1.4, marginTop: 4, display: 'block',
  },
  featureRow: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 },
  featureName: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, width: 100, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  featureBarBg: { flex: 1, height: 4, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  featureBarFill: { height: '100%', borderRadius: 2, transition: 'width 400ms ease' },
  featureImportance: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, width: 28, textAlign: 'right' },
  targetsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 6 },
  targetItem: { borderRadius: 6, padding: '8px 10px', background: COLORS.bg.elevated, display: 'flex', flexDirection: 'column', gap: 3 },
  targetLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, fontWeight: 700, letterSpacing: '0.1em' },
  targetPrice: { fontFamily: '"JetBrains Mono", monospace', fontSize: 12, fontWeight: 700 },
  targetDiff:  { fontFamily: '"JetBrains Mono", monospace', fontSize: 9 },
  riskBox: {
    background: COLORS.risk.bg,
    border: `1px solid ${COLORS.loss.border}`,
    borderRadius: 6, padding: '8px 12px',
  },
  riskText: { fontFamily: '"Inter", sans-serif', fontSize: 11, color: COLORS.text.secondary, lineHeight: 1.5, margin: '4px 0 0' },
  warningsBox: { display: 'flex', flexDirection: 'column', gap: 4 },
  warning: {
    display: 'flex', alignItems: 'flex-start', gap: 6,
    fontFamily: '"Inter", sans-serif', fontSize: 10,
    color: COLORS.neon.amber, lineHeight: 1.4,
    background: `${COLORS.neon.amber}0d`,
    border: `1px solid ${COLORS.neon.amber}33`,
    borderRadius: 4, padding: '5px 8px',
  },
  warnIcon: { flexShrink: 0, fontSize: 10 },
  timestamp: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, letterSpacing: '0.06em', textAlign: 'right' },
  clickPrompt: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32px 20px', gap: 12, textAlign: 'center' },
  promptIcon: { opacity: 0.7 },
  promptTitle: { fontFamily: '"JetBrains Mono", monospace', fontSize: 12, color: COLORS.text.secondary, margin: 0, letterSpacing: '0.04em' },
  promptSub: { fontFamily: '"Inter", sans-serif', fontSize: 11, color: COLORS.text.muted, margin: 0, lineHeight: 1.6, maxWidth: 260 },
  loadingPanel: { padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 10 },
  loadingHeader: { display: 'flex', alignItems: 'center', gap: 8 },
  loadingSpinner: {
    width: 14, height: 14, borderRadius: '50%',
    border: `2px solid ${COLORS.bg.elevated}`,
    borderTopColor: COLORS.neon.purple,
    animation: 'spin 0.8s linear infinite',
  },
  loadingTitle: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.neon.purple, letterSpacing: '0.1em' },
  loadingPrice: { display: 'flex', gap: 10, alignItems: 'center' },
  loadingLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, letterSpacing: '0.08em', width: 40 },
  loadingVal: { fontFamily: '"JetBrains Mono", monospace', fontSize: 12, color: COLORS.text.primary, fontWeight: 700 },
  loadingSteps: { display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 },
  loadingStep: { display: 'flex', alignItems: 'center', gap: 8 },
  loadingStepDot: { width: 4, height: 4, borderRadius: '50%', background: COLORS.neon.purple, opacity: 0.6 },
  loadingStepText: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.text.muted },
  errorBox: { padding: '16px 14px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 },
  errorIcon: { fontSize: 20, color: COLORS.loss.base },
  errorText: { fontFamily: '"Inter", sans-serif', fontSize: 11, color: COLORS.text.secondary, textAlign: 'center' },
  retryBtn: {
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.divider}`,
    borderRadius: 4, color: COLORS.text.secondary,
    cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10, padding: '5px 12px', letterSpacing: '0.06em',
  },
};

export default memo(AIChartBot);
