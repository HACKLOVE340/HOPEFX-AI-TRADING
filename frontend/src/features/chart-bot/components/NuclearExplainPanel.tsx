/**
 * NuclearExplainPanel.tsx
 * Right-sidebar explainability panel — shows:
 * - RL decision log with confidence breakdown
 * - WORDMAP category scores (SHAP-style bar chart)
 * - Matched terms with weights
 * - Current exposure / CVaR
 * - Nuclear event history
 */

import React, { memo } from 'react';
import { useNuclearStore } from '../store/nuclear-store';
import { severityColor, actionColor } from '../types/nuclear';
import type { NuclearState, NuclearRiskData, NuclearEvent } from '../types/nuclear';
import NuclearDecisionTrace from './NuclearDecisionTrace';

/** Guard .toFixed against undefined/NaN risk fields (partial WS payloads). */
const safeFixed = (v: number | null | undefined, dec: number): string =>
  Number.isFinite(v as number) ? (v as number).toFixed(dec) : '—';

// ─── SHAP-style feature bar ───────────────────────────────────────────────────

const FeatureBar = memo(({
  label, value, maxValue, color,
}: { label: string; value: number; maxValue: number; color: string }) => {
  const pct = maxValue > 0 ? Math.min(100, (value / maxValue) * 100) : 0;
  return (
    <div style={s.featureRow}>
      <span style={s.featureLabel}>{label}</span>
      <div style={s.featureTrack}>
        <div style={{ ...s.featureFill, width: `${pct}%`, background: color }} />
      </div>
      <span style={{ ...s.featureValue, color }}>{safeFixed(value, 2)}</span>
    </div>
  );
});

// ─── RL decision card ─────────────────────────────────────────────────────────

const RLDecisionCard = memo(({ nuclear }: { nuclear: NuclearState }) => {
  const color = actionColor(nuclear.action);
  return (
    <div style={{ ...s.card, borderColor: color }}>
      <div style={s.cardHeader}>
        <span style={s.cardTitle}>RL DECISION</span>
        <span style={{ ...s.rlBadge, background: color, color: '#000' }}>
          {nuclear.rl_action_label}
        </span>
      </div>
      <div style={s.decisionGrid}>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>SEVERITY</span>
          <span style={{ ...s.cellValue, color: severityColor(nuclear.severity) }}>
            {nuclear.severity}/10
          </span>
        </div>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>CONFIDENCE</span>
          <span style={{ ...s.cellValue, color }}>
            {(nuclear.confidence * 100).toFixed(0)}%
          </span>
        </div>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>VOL FACTOR</span>
          <span style={s.cellValue}>×{nuclear.vol_factor.toFixed(2)}</span>
        </div>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>SENTIMENT</span>
          <span style={s.cellValue}>+{nuclear.sentiment_factor.toFixed(2)}</span>
        </div>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>AGENT</span>
          <span style={{ ...s.cellValue, color: nuclear.rl_agent_loaded ? '#00ff88' : '#fbbf24' }}>
            {nuclear.rl_agent_loaded ? 'PPO RL' : 'RULES'}
          </span>
        </div>
        <div style={s.decisionCell}>
          <span style={s.cellLabel}>PAUSED</span>
          <span style={{ ...s.cellValue, color: nuclear.trading_paused ? '#ff0033' : '#00ff88' }}>
            {nuclear.trading_paused ? 'YES' : 'NO'}
          </span>
        </div>
      </div>
    </div>
  );
});

// ─── Category scores (SHAP-style) ─────────────────────────────────────────────

const CategoryScores = memo(({ nuclear }: { nuclear: NuclearState }) => {
  const entries = Object.entries(nuclear.category_scores)
    .sort(([, a], [, b]) => b - a);
  if (!entries.length) return null;
  const maxVal = entries[0]?.[1] ?? 1;

  return (
    <div style={s.card}>
      <div style={s.cardHeader}>
        <span style={s.cardTitle}>WORDMAP CATEGORY SCORES</span>
        <span style={s.cardSubtitle}>SHAP-style</span>
      </div>
      <div style={s.featureList}>
        {entries.map(([cat, val]) => (
          <FeatureBar
            key={cat}
            label={cat.replace(/_/g, ' ')}
            value={val}
            maxValue={maxVal}
            color={severityColor(Math.round(val))}
          />
        ))}
      </div>
    </div>
  );
});

// ─── Matched terms ────────────────────────────────────────────────────────────

const MatchedTerms = memo(({ nuclear }: { nuclear: NuclearState }) => {
  const top = [...nuclear.matched_terms]
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 8);
  if (!top.length) return null;

  return (
    <div style={s.card}>
      <div style={s.cardHeader}>
        <span style={s.cardTitle}>MATCHED KEYWORDS</span>
        <span style={s.cardSubtitle}>{nuclear.matched_terms.length} total</span>
      </div>
      <div style={s.termList}>
        {top.map((t, i) => (
          <div key={i} style={s.termRow}>
            <div style={s.termLeft}>
              <span style={{ ...s.termText, color: severityColor(Math.round(t.weight)) }}>
                {t.term}
              </span>
              <span style={s.termCat}>{t.category}</span>
            </div>
            <div style={s.termRight}>
              <span style={s.termWeight}>w={t.weight.toFixed(1)}</span>
              <span style={{ ...s.termContrib, color: severityColor(Math.round(t.contribution)) }}>
                +{t.contribution.toFixed(2)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

// ─── Risk metrics ─────────────────────────────────────────────────────────────

const RiskMetricsCard = memo(({ risk }: { risk: NuclearRiskData }) => (
  <div style={{ ...s.card, borderColor: risk.kill_switch_active ? '#ff0033' : '#1a2e4a' }}>
    <div style={s.cardHeader}>
      <span style={s.cardTitle}>RISK METRICS</span>
      {risk.kill_switch_active && (
        <span style={s.killBadge}>KILL SWITCH</span>
      )}
    </div>
    <div style={s.riskGrid}>
      <RiskRow label="CVaR 95%" value={`${safeFixed(risk.cvar_95 * 100, 2)}%`} danger={risk.cvar_95 > 0.02} />
      <RiskRow label="CVaR 99%" value={`${safeFixed(risk.cvar_99 * 100, 2)}%`} danger={risk.cvar_99 > 0.03} />
      <RiskRow label="VaR 95%"  value={`${safeFixed(risk.var_95 * 100, 2)}%`}  danger={false} />
      <RiskRow label="Exposure" value={`${safeFixed(risk.exposure * 100, 1)}%`} danger={risk.exposure > 0.8} />
      <RiskRow label="Max Risk" value={`${safeFixed(risk.max_risk * 100, 0)}%`} danger={risk.max_risk === 0} />
      <RiskRow label="Drawdown" value={`${safeFixed(risk.drawdown_pct, 2)}%`}     danger={risk.drawdown_pct > 2} />
      <RiskRow label="Daily P&L" value={`$${safeFixed(risk.daily_pnl, 2)}`}       danger={risk.daily_pnl < 0} />
      <RiskRow label="Equity"   value={`$${safeFixed(risk.equity, 2)}`}           danger={false} />
    </div>
  </div>
));

const RiskRow = memo(({ label, value, danger }: { label: string; value: string; danger: boolean }) => (
  <div style={s.riskRow}>
    <span style={s.riskLabel}>{label}</span>
    <span style={{ ...s.riskValue, color: danger ? '#ef4444' : '#94a3b8' }}>{value}</span>
  </div>
));

// ─── Event history ────────────────────────────────────────────────────────────

const EventHistory = memo(({ events }: { events: NuclearEvent[] }) => {
  if (!events.length) return null;
  return (
    <div style={s.card}>
      <div style={s.cardHeader}>
        <span style={s.cardTitle}>NUCLEAR EVENT LOG</span>
        <span style={s.cardSubtitle}>{events.length} events</span>
      </div>
      <div style={s.eventList}>
        {[...events].reverse().slice(0, 10).map((ev, i) => (
          <div key={i} style={s.eventRow}>
            <div style={s.eventHeader}>
              <span style={{ ...s.eventSeverity, color: severityColor(ev.severity) }}>
                SEV {ev.severity}
              </span>
              <span style={s.eventAction}>{ev.action.replace(/_/g, ' ')}</span>
              <span style={s.eventTime}>
                {new Date(ev.ts).toLocaleTimeString()}
              </span>
            </div>
            <div style={s.eventText}>{ev.text.slice(0, 80)}{ev.text.length > 80 ? '…' : ''}</div>
          </div>
        ))}
      </div>
    </div>
  );
});

// ─── Main panel ───────────────────────────────────────────────────────────────

const NuclearExplainPanel = memo(() => {
  const nuclear      = useNuclearStore((s) => s.nuclear);
  const risk         = useNuclearStore((s) => s.risk);
  const nuclearEvents = useNuclearStore((s) => s.nuclearEvents);

  return (
    <div style={s.panel}>
      <div style={s.panelHeader}>
        <span style={s.panelTitle}>AI EXPLAINABILITY</span>
        <span style={s.panelSubtitle}>RL + WORDMAP</span>
      </div>

      <div style={s.scrollArea}>
        {nuclear ? (
          <>
            {/* Co-pilot explanation */}
            <div style={s.explainBox}>
              <div style={s.explainLabel}>CO-PILOT SUMMARY</div>
              <div style={s.explainText}>{nuclear.explanation}</div>
            </div>

            <RLDecisionCard nuclear={nuclear} />
            <CategoryScores nuclear={nuclear} />
            <MatchedTerms nuclear={nuclear} />
            <NuclearDecisionTrace />
          </>
        ) : (
          <div style={s.emptyState}>
            <div style={s.emptyIcon}>🛡️</div>
            <div style={s.emptyText}>No nuclear events detected</div>
            <div style={s.emptySubtext}>System monitoring active</div>
          </div>
        )}

        {risk && <RiskMetricsCard risk={risk} />}
        <EventHistory events={nuclearEvents} />
      </div>
    </div>
  );
});

export default NuclearExplainPanel;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  panel: {
    width: 300, flexShrink: 0,
    background: '#060d18',
    borderLeft: '1px solid #1a2e4a',
    display: 'flex', flexDirection: 'column',
    height: '100%', overflow: 'hidden',
  },
  panelHeader: {
    padding: '12px 16px',
    borderBottom: '1px solid #1a2e4a',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    flexShrink: 0,
  },
  panelTitle: {
    fontSize: 11, fontWeight: 800, letterSpacing: 2, color: '#94a3b8',
  },
  panelSubtitle: {
    fontSize: 9, color: '#475569', letterSpacing: 1.5,
  },
  scrollArea: {
    flex: 1, overflowY: 'auto', padding: '12px',
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  explainBox: {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1a2e4a',
    borderRadius: 6, padding: '10px 12px',
  },
  explainLabel: {
    fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700, marginBottom: 6,
  },
  explainText: {
    fontSize: 12, color: '#cbd5e1', lineHeight: 1.7,
  },
  card: {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid #1a2e4a',
    borderRadius: 6, padding: '10px 12px',
    transition: 'border-color 0.4s ease',
  },
  cardHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: 10,
  },
  cardTitle: {
    fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700,
  },
  cardSubtitle: {
    fontSize: 9, color: '#334155',
  },
  rlBadge: {
    fontSize: 10, fontWeight: 800, padding: '2px 8px',
    borderRadius: 4, fontFamily: 'monospace',
  },
  decisionGrid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
  },
  decisionCell: {
    display: 'flex', flexDirection: 'column', gap: 2,
  },
  cellLabel: {
    fontSize: 8, color: '#334155', letterSpacing: 1.5, fontWeight: 700,
  },
  cellValue: {
    fontSize: 13, fontWeight: 700, color: '#94a3b8', fontFamily: 'monospace',
  },
  featureList: {
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  featureRow: {
    display: 'flex', alignItems: 'center', gap: 8,
  },
  featureLabel: {
    fontSize: 10, color: '#64748b', width: 90, flexShrink: 0,
    textTransform: 'capitalize',
  },
  featureTrack: {
    flex: 1, height: 4, background: '#1a2e4a', borderRadius: 2, overflow: 'hidden',
  },
  featureFill: {
    height: '100%', borderRadius: 2, transition: 'width 0.4s ease',
  },
  featureValue: {
    fontSize: 10, fontFamily: 'monospace', width: 36, textAlign: 'right', flexShrink: 0,
  },
  termList: {
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  termRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '4px 0', borderBottom: '1px solid #0f1f35',
  },
  termLeft: {
    display: 'flex', flexDirection: 'column', gap: 1,
  },
  termText: {
    fontSize: 11, fontWeight: 600, fontFamily: 'monospace',
  },
  termCat: {
    fontSize: 9, color: '#334155', textTransform: 'capitalize',
  },
  termRight: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 1,
  },
  termWeight: {
    fontSize: 9, color: '#475569', fontFamily: 'monospace',
  },
  termContrib: {
    fontSize: 11, fontWeight: 700, fontFamily: 'monospace',
  },
  riskGrid: {
    display: 'flex', flexDirection: 'column', gap: 4,
  },
  riskRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '3px 0', borderBottom: '1px solid #0a1628',
  },
  riskLabel: {
    fontSize: 10, color: '#475569',
  },
  riskValue: {
    fontSize: 11, fontFamily: 'monospace', fontWeight: 600,
  },
  killBadge: {
    fontSize: 9, fontWeight: 800, color: '#ff0033',
    border: '1px solid #ff0033', borderRadius: 3,
    padding: '1px 6px', letterSpacing: 1,
  },
  eventList: {
    display: 'flex', flexDirection: 'column', gap: 8,
  },
  eventRow: {
    padding: '6px 0', borderBottom: '1px solid #0a1628',
  },
  eventHeader: {
    display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3,
  },
  eventSeverity: {
    fontSize: 10, fontWeight: 800, fontFamily: 'monospace',
  },
  eventAction: {
    fontSize: 9, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1,
  },
  eventTime: {
    fontSize: 9, color: '#334155', marginLeft: 'auto', fontFamily: 'monospace',
  },
  eventText: {
    fontSize: 10, color: '#64748b', lineHeight: 1.5,
  },
  emptyState: {
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    padding: '32px 16px', gap: 8,
  },
  emptyIcon: { fontSize: 32 },
  emptyText: { fontSize: 13, color: '#475569', fontWeight: 600 },
  emptySubtext: { fontSize: 11, color: '#334155' },
};
