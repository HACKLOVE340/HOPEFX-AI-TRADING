/**
 * NuclearGeopoliticalBanner.tsx
 * Top-banner geopolitical risk gauge — color-coded, flashing on severity ≥ 7.
 * Shows: severity score, action label, matched terms, and a live gauge bar.
 */

import React, { memo, useEffect, useRef } from 'react';
import { useNuclearStore } from '../store/nuclear-store';
import { severityColor, actionColor, severityLabel } from '../types/nuclear';
import type { NuclearState, GeopoliticalGauge } from '../types/nuclear';

// ─── Gauge bar ────────────────────────────────────────────────────────────────

const GaugeBar = memo(({ score, color }: { score: number; color: string }) => (
  <div style={s.gaugeTrack}>
    <div
      style={{
        ...s.gaugeFill,
        width: `${score}%`,
        background: `linear-gradient(90deg, #00ff88 0%, ${color} 100%)`,
        boxShadow: score >= 70 ? `0 0 12px ${color}` : 'none',
        transition: 'width 0.6s ease, background 0.4s ease',
      }}
    />
    {/* Severity zone markers */}
    {[50, 70, 90].map((pct) => (
      <div key={pct} style={{ ...s.gaugeMarker, left: `${pct}%` }} />
    ))}
  </div>
));

// ─── Matched terms pills ──────────────────────────────────────────────────────

const TermPills = memo(({ nuclear }: { nuclear: NuclearState }) => {
  const top = [...nuclear.matched_terms]
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 5);
  if (!top.length) return null;
  return (
    <div style={s.termRow}>
      {top.map((t, i) => (
        <span key={i} style={{ ...s.termPill, borderColor: severityColor(nuclear.severity) }}>
          {t.term}
          <span style={s.termWeight}>{t.weight.toFixed(1)}</span>
        </span>
      ))}
    </div>
  );
});

// ─── Main banner ──────────────────────────────────────────────────────────────

interface Props {
  onClickExplain?: () => void;
}

const NuclearGeopoliticalBanner = memo(({ onClickExplain }: Props) => {
  const nuclear = useNuclearStore((s) => s.nuclear);
  const gauge   = useNuclearStore((s) => s.gauge);
  const flashRef = useRef<HTMLDivElement>(null);

  const severity = nuclear?.severity ?? 0;
  const action   = nuclear?.action ?? 'normal';
  const color    = severityColor(severity);
  const isAlert  = severity >= 7;

  // CSS flash animation injection
  useEffect(() => {
    const id = 'nuclear-banner-flash';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = `
      @keyframes nuclearFlash {
        0%, 100% { opacity: 1; box-shadow: 0 0 0 rgba(255,0,51,0); }
        50%       { opacity: 0.85; box-shadow: 0 0 24px rgba(255,0,51,0.6); }
      }
      @keyframes nuclearPulse {
        0%, 100% { transform: scale(1); }
        50%       { transform: scale(1.04); }
      }
      .nuclear-flash-active {
        animation: nuclearFlash 1s ease-in-out infinite;
      }
      .nuclear-pulse-dot {
        animation: nuclearPulse 0.8s ease-in-out infinite;
      }
    `;
    document.head.appendChild(style);
  }, []);

  if (!nuclear && !gauge) return null;

  const gaugeScore = gauge?.score ?? severity * 10;
  const gaugeLabel = gauge?.label ?? severityLabel(severity);

  return (
    <div
      ref={flashRef}
      className={isAlert ? 'nuclear-flash-active' : ''}
      style={{
        ...s.banner,
        borderColor: color,
        background: isAlert
          ? `linear-gradient(135deg, rgba(255,0,51,0.12) 0%, rgba(6,13,24,0.98) 100%)`
          : `linear-gradient(135deg, rgba(0,255,136,0.04) 0%, rgba(6,13,24,0.98) 100%)`,
      }}
    >
      {/* Left: severity badge */}
      <div style={s.leftSection}>
        <div
          className={isAlert ? 'nuclear-pulse-dot' : ''}
          style={{
            ...s.severityBadge,
            background: color,
            boxShadow: `0 0 16px ${color}`,
          }}
        >
          {severity}
        </div>
        <div style={s.labelStack}>
          <span style={{ ...s.gaugeLabel, color }}>
            {isAlert && '☢️ '}{gaugeLabel}
          </span>
          <span style={s.actionLabel}>
            {action.replace(/_/g, ' ').toUpperCase()}
          </span>
        </div>
      </div>

      {/* Center: gauge bar + matched terms */}
      <div style={s.centerSection}>
        <div style={s.gaugeRow}>
          <span style={s.gaugeCaption}>GEOPOLITICAL RISK</span>
          <span style={{ ...s.gaugeScore, color }}>{gaugeScore}/100</span>
        </div>
        <GaugeBar score={gaugeScore} color={color} />
        {nuclear && <TermPills nuclear={nuclear} />}
      </div>

      {/* Right: RL action + explain button */}
      <div style={s.rightSection}>
        {nuclear && (
          <>
            <div style={s.rlBox}>
              <span style={s.rlLabel}>RL AGENT</span>
              <span style={{
                ...s.rlAction,
                color: actionColor(action),
                borderColor: actionColor(action),
              }}>
                {nuclear.rl_action_label}
              </span>
              <span style={s.rlConf}>
                {Number.isFinite(nuclear.confidence) ? (nuclear.confidence * 100).toFixed(0) : '—'}% conf
              </span>
            </div>
            <button style={{ ...s.explainBtn, borderColor: color, color }} onClick={onClickExplain}>
              WHY? →
            </button>
          </>
        )}
      </div>
    </div>
  );
});

export default NuclearGeopoliticalBanner;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  banner: {
    display: 'flex', alignItems: 'center', gap: 16,
    padding: '10px 20px',
    borderBottom: '2px solid',
    borderTop: '1px solid',
    background: 'rgba(6,13,24,0.98)',
    minHeight: 72,
    flexShrink: 0,
    zIndex: 100,
    transition: 'border-color 0.4s ease, background 0.4s ease',
  },
  leftSection: {
    display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
  },
  severityBadge: {
    width: 44, height: 44, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 18, fontWeight: 900, color: '#000',
    flexShrink: 0,
    transition: 'background 0.4s ease, box-shadow 0.4s ease',
  },
  labelStack: {
    display: 'flex', flexDirection: 'column', gap: 2,
  },
  gaugeLabel: {
    fontSize: 14, fontWeight: 800, letterSpacing: 1,
    transition: 'color 0.4s ease',
  },
  actionLabel: {
    fontSize: 10, color: '#64748b', letterSpacing: 1.5, fontWeight: 600,
  },
  centerSection: {
    flex: 1, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0,
  },
  gaugeRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  gaugeCaption: {
    fontSize: 10, color: '#475569', letterSpacing: 2, fontWeight: 700,
  },
  gaugeScore: {
    fontSize: 12, fontWeight: 700, fontFamily: 'monospace',
    transition: 'color 0.4s ease',
  },
  gaugeTrack: {
    position: 'relative', height: 6, background: '#1a2e4a',
    borderRadius: 3, overflow: 'visible',
  },
  gaugeFill: {
    position: 'absolute', left: 0, top: 0, height: '100%',
    borderRadius: 3, transition: 'width 0.6s ease',
  },
  gaugeMarker: {
    position: 'absolute', top: -2, width: 1, height: 10,
    background: '#334155', transform: 'translateX(-50%)',
  },
  termRow: {
    display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2,
  },
  termPill: {
    display: 'flex', alignItems: 'center', gap: 4,
    padding: '2px 8px', borderRadius: 10,
    border: '1px solid', fontSize: 10, color: '#94a3b8',
    background: 'rgba(255,255,255,0.03)',
    fontFamily: 'monospace',
  },
  termWeight: {
    color: '#475569', fontSize: 9,
  },
  rightSection: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0,
  },
  rlBox: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2,
  },
  rlLabel: {
    fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700,
  },
  rlAction: {
    fontSize: 13, fontWeight: 800, letterSpacing: 1,
    padding: '2px 8px', border: '1px solid', borderRadius: 4,
    fontFamily: 'monospace',
    transition: 'color 0.4s ease, border-color 0.4s ease',
  },
  rlConf: {
    fontSize: 10, color: '#64748b', fontFamily: 'monospace',
  },
  explainBtn: {
    background: 'transparent', border: '1px solid',
    borderRadius: 4, padding: '4px 10px',
    fontSize: 11, fontWeight: 700, letterSpacing: 1,
    cursor: 'pointer', fontFamily: 'monospace',
    transition: 'background 0.2s ease',
  },
};
