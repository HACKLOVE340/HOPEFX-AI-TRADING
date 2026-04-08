/**
 * NuclearDecisionTrace.tsx
 * Renders the structured SHAP-style decision trace from the explainability engine.
 * Shows: feature importance bars, step-by-step reasoning chain, action advice.
 * Embeds inside NuclearExplainPanel when decision_trace data is available.
 */

import React, { memo } from 'react';
import { useNuclearStore } from '../store/nuclear-store';
import { severityColor } from '../types/nuclear';

// ─── Types (mirroring backend FeatureScore) ───────────────────────────────────

interface FeatureScore {
  name: string;
  value: number;
  importance: number;
  direction: 'bullish' | 'bearish' | 'neutral';
  description: string;
}

// ─── Feature importance bar ───────────────────────────────────────────────────

const ImportanceBar = memo(({ feature }: { feature: FeatureScore }) => {
  const pct   = Math.round(feature.importance * 100);
  const color = feature.direction === 'bearish' ? '#ef4444'
              : feature.direction === 'bullish' ? '#00ff88'
              : '#64748b';
  const [hovered, setHovered] = React.useState(false);

  return (
    <div
      style={s.featureRow}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={feature.description}
    >
      <span style={s.featureName}>{feature.name.replace('keyword: ', '').replace(/"/g, '')}</span>
      <div style={s.barTrack}>
        <div style={{ ...s.barFill, width: `${pct}%`, background: color }} />
      </div>
      <span style={{ ...s.featurePct, color }}>{pct}%</span>
      {hovered && (
        <div style={s.tooltip}>{feature.description}</div>
      )}
    </div>
  );
});

// ─── Decision trace steps ─────────────────────────────────────────────────────

const DecisionTrace = memo(({ steps }: { steps: string[] }) => (
  <div style={s.traceList}>
    {steps.map((step, i) => {
      const isDecision = step.startsWith('[7]');
      const isWarning  = step.includes('NUCLEAR') || step.includes('liquidat');
      return (
        <div
          key={i}
          style={{
            ...s.traceStep,
            borderLeftColor: isDecision
              ? (isWarning ? '#ff0033' : '#00ff88')
              : '#1a2e4a',
            background: isDecision ? 'rgba(255,255,255,0.03)' : 'transparent',
          }}
        >
          <span style={{
            ...s.traceText,
            color: isDecision ? (isWarning ? '#fca5a5' : '#86efac') : '#94a3b8',
            fontWeight: isDecision ? 700 : 400,
          }}>
            {step}
          </span>
        </div>
      );
    })}
  </div>
));

// ─── Confidence breakdown ─────────────────────────────────────────────────────

const ConfidenceBreakdown = memo(({ breakdown }: { breakdown: Record<string, number> }) => {
  const entries = Object.entries(breakdown);
  if (!entries.length) return null;
  return (
    <div style={s.confGrid}>
      {entries.map(([key, val]) => (
        <div key={key} style={s.confCell}>
          <span style={s.confLabel}>{key.replace(/_/g, ' ')}</span>
          <span style={{ ...s.confValue, color: val > 0.5 ? '#ef4444' : '#64748b' }}>
            {(val * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
});

// ─── Main component ───────────────────────────────────────────────────────────

const NuclearDecisionTrace = memo(() => {
  const nuclear = useNuclearStore((s) => s.nuclear);

  // These fields are populated by the explainability engine
  const featureScores    = nuclear?.feature_scores    as FeatureScore[] | undefined;
  const decisionTrace    = nuclear?.decision_trace;
  const riskNarrative    = nuclear?.risk_narrative;
  const actionAdvice     = nuclear?.action_advice;
  const confBreakdown    = nuclear?.confidence_breakdown;

  if (!nuclear || (!featureScores?.length && !decisionTrace?.length)) return null;

  const severity = nuclear.severity;
  const color    = severityColor(severity);

  return (
    <div style={s.wrapper}>
      {/* Feature importance */}
      {featureScores && featureScores.length > 0 && (
        <div style={s.section}>
          <div style={s.sectionTitle}>FEATURE IMPORTANCE (SHAP-style)</div>
          {featureScores.map((f, i) => (
            <ImportanceBar key={i} feature={f} />
          ))}
        </div>
      )}

      {/* Confidence breakdown */}
      {confBreakdown && Object.keys(confBreakdown).length > 0 && (
        <div style={s.section}>
          <div style={s.sectionTitle}>CONFIDENCE BREAKDOWN</div>
          <ConfidenceBreakdown breakdown={confBreakdown} />
        </div>
      )}

      {/* Decision trace */}
      {decisionTrace && decisionTrace.length > 0 && (
        <div style={s.section}>
          <div style={s.sectionTitle}>DECISION TRACE</div>
          <DecisionTrace steps={decisionTrace} />
        </div>
      )}

      {/* Risk narrative */}
      {riskNarrative && (
        <div style={{ ...s.narrativeBox, borderColor: color }}>
          <div style={s.sectionTitle}>RISK NARRATIVE</div>
          <p style={s.narrativeText}>{riskNarrative}</p>
        </div>
      )}

      {/* Action advice */}
      {actionAdvice && (
        <div style={{
          ...s.adviceBox,
          borderColor: color,
          background: severity >= 7 ? 'rgba(255,0,51,0.06)' : 'rgba(0,255,136,0.04)',
        }}>
          <div style={{ ...s.sectionTitle, color }}>OPERATOR ACTION REQUIRED</div>
          <p style={s.adviceText}>{actionAdvice}</p>
        </div>
      )}
    </div>
  );
});

export default NuclearDecisionTrace;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  wrapper: {
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  section: {
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  sectionTitle: {
    fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700, marginBottom: 4,
  },
  featureRow: {
    display: 'flex', alignItems: 'center', gap: 6,
    position: 'relative', cursor: 'default',
  },
  featureName: {
    fontSize: 9, color: '#64748b', width: 80, flexShrink: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
    fontFamily: 'monospace',
  },
  barTrack: {
    flex: 1, height: 4, background: '#1a2e4a', borderRadius: 2, overflow: 'hidden',
  },
  barFill: {
    height: '100%', borderRadius: 2, transition: 'width 0.4s ease',
  },
  featurePct: {
    fontSize: 9, fontFamily: 'monospace', width: 28, textAlign: 'right', flexShrink: 0,
  },
  tooltip: {
    position: 'absolute', bottom: '100%', left: 0, right: 0,
    background: '#0f1f35', border: '1px solid #1a2e4a',
    borderRadius: 4, padding: '6px 8px',
    fontSize: 10, color: '#cbd5e1', lineHeight: 1.5,
    zIndex: 10, pointerEvents: 'none',
    whiteSpace: 'normal',
  },
  traceList: {
    display: 'flex', flexDirection: 'column', gap: 4,
  },
  traceStep: {
    borderLeft: '2px solid',
    paddingLeft: 8, paddingTop: 3, paddingBottom: 3,
    transition: 'border-color 0.3s ease',
  },
  traceText: {
    fontSize: 10, lineHeight: 1.6, fontFamily: 'monospace',
  },
  confGrid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6,
  },
  confCell: {
    display: 'flex', flexDirection: 'column', gap: 1,
  },
  confLabel: {
    fontSize: 8, color: '#334155', letterSpacing: 1, textTransform: 'capitalize',
  },
  confValue: {
    fontSize: 12, fontWeight: 700, fontFamily: 'monospace',
  },
  narrativeBox: {
    border: '1px solid', borderRadius: 6, padding: '8px 10px',
    background: 'rgba(255,255,255,0.02)',
    transition: 'border-color 0.4s ease',
  },
  narrativeText: {
    fontSize: 11, color: '#cbd5e1', lineHeight: 1.7, margin: 0,
  },
  adviceBox: {
    border: '1px solid', borderRadius: 6, padding: '8px 10px',
    transition: 'all 0.4s ease',
  },
  adviceText: {
    fontSize: 11, color: '#e2e8f0', lineHeight: 1.7, margin: 0,
  },
};
