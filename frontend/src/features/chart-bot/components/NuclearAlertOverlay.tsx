/**
 * NuclearAlertOverlay.tsx
 * Full-screen nuclear alert overlay — shown when severity ≥ 7.
 * Features:
 * - Massive red overlay zone with animated border
 * - Flashing alert banner with severity, action, and explanation
 * - Historical analog projection
 * - Auto-dismiss after 10s (can be dismissed manually)
 * - "Protected view" lock when nuclear_mode active
 */

import React, { memo, useEffect } from 'react';
import { useNuclearStore } from '../store/nuclear-store';
import { severityColor, actionColor } from '../types/nuclear';
import type { NuclearAlertMessage } from '../types/nuclear';

// ─── Inject keyframes once ────────────────────────────────────────────────────

function injectAlertCSS() {
  const id = 'nuclear-alert-overlay-css';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes alertSlideDown {
      from { transform: translateY(-100%); opacity: 0; }
      to   { transform: translateY(0);     opacity: 1; }
    }
    @keyframes alertBorderPulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(255,0,51,0); }
      50%       { box-shadow: 0 0 40px 8px rgba(255,0,51,0.5); }
    }
    @keyframes alertTextBlink {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.3; }
    }
    @keyframes alertCountdown {
      from { width: 100%; }
      to   { width: 0%; }
    }
    .nuclear-alert-slide { animation: alertSlideDown 0.4s ease-out forwards; }
    .nuclear-alert-border { animation: alertBorderPulse 1.2s ease-in-out infinite; }
    .nuclear-alert-blink  { animation: alertTextBlink 0.8s ease-in-out infinite; }
  `;
  document.head.appendChild(style);
}

// ─── Countdown bar ────────────────────────────────────────────────────────────

const CountdownBar = memo(({ durationMs, color }: { durationMs: number; color: string }) => (
  <div style={s.countdownTrack}>
    <div
      style={{
        ...s.countdownFill,
        background: color,
        animation: `alertCountdown ${durationMs}ms linear forwards`,
      }}
    />
  </div>
));

// ─── Alert panel ─────────────────────────────────────────────────────────────

interface AlertPanelProps {
  alert: NuclearAlertMessage;
  onDismiss: () => void;
  isNuclearMode: boolean;
}

const AlertPanel = memo(({ alert, onDismiss, isNuclearMode }: AlertPanelProps) => {
  const color = severityColor(alert.severity);
  const actionClr = actionColor(alert.action);
  const AUTO_DISMISS_MS = isNuclearMode ? 0 : 10_000; // no auto-dismiss in nuclear mode

  useEffect(() => {
    if (AUTO_DISMISS_MS > 0) {
      const t = setTimeout(onDismiss, AUTO_DISMISS_MS);
      return () => clearTimeout(t);
    }
  }, [AUTO_DISMISS_MS, onDismiss]);

  return (
    <div
      className="nuclear-alert-slide nuclear-alert-border"
      style={{
        ...s.alertPanel,
        borderColor: color,
        background: `linear-gradient(135deg, rgba(255,0,51,0.15) 0%, rgba(6,13,24,0.97) 60%)`,
      }}
    >
      {/* Header */}
      <div style={s.alertHeader}>
        <div style={s.alertHeaderLeft}>
          <span className="nuclear-alert-blink" style={{ ...s.alertIcon, color }}>
            ☢️
          </span>
          <div>
            <div style={{ ...s.alertTitle, color }}>
              NUCLEAR ALERT — SEVERITY {alert.severity}/10
            </div>
            <div style={{ ...s.alertSubtitle, color: actionClr }}>
              RL: {alert.rl_action_label} · {alert.action.replace(/_/g, ' ').toUpperCase()}
            </div>
          </div>
        </div>
        {!isNuclearMode && (
          <button style={s.dismissBtn} onClick={onDismiss}>✕</button>
        )}
      </div>

      {/* Explanation */}
      <div style={s.explanationBox}>
        <div style={s.explanationLabel}>AI CO-PILOT EXPLANATION</div>
        <div style={s.explanationText}>{alert.explanation}</div>
      </div>

      {/* Historical analog */}
      {alert.historical_analog && (
        <div style={s.analogBox}>
          <div style={s.analogLabel}>📊 HISTORICAL ANALOG</div>
          <div style={s.analogText}>{alert.historical_analog}</div>
        </div>
      )}

      {/* Nuclear mode lock notice */}
      {isNuclearMode && (
        <div style={s.lockNotice}>
          <span style={s.lockIcon}>🔒</span>
          <span style={s.lockText}>
            PROTECTED VIEW ACTIVE — All trading halted. Manual resume required via /api/nuclear/resume
          </span>
        </div>
      )}

      {/* Countdown bar */}
      {AUTO_DISMISS_MS > 0 && (
        <CountdownBar durationMs={AUTO_DISMISS_MS} color={color} />
      )}
    </div>
  );
});

// ─── Main overlay ─────────────────────────────────────────────────────────────

const NuclearAlertOverlay = memo(() => {
  const activeAlert    = useNuclearStore((s) => s.activeAlert);
  const nuclear        = useNuclearStore((s) => s.nuclear);
  const protectedView  = useNuclearStore((s) => s.protectedView);
  const dismissAlert   = useNuclearStore((s) => s.dismissAlert);

  useEffect(() => { injectAlertCSS(); }, []);

  if (!activeAlert) return null;

  const isNuclearMode = nuclear?.action === 'nuclear_mode' || protectedView;
  const color = severityColor(activeAlert.severity);

  return (
    <>
      {/* Background tint overlay */}
      <div
        style={{
          ...s.backdrop,
          background: isNuclearMode
            ? 'rgba(255,0,51,0.08)'
            : 'rgba(255,0,51,0.04)',
          pointerEvents: isNuclearMode ? 'all' : 'none',
        }}
      />

      {/* Alert panel — top of chart area */}
      <div style={s.overlayContainer}>
        <AlertPanel
          alert={activeAlert}
          onDismiss={dismissAlert}
          isNuclearMode={isNuclearMode}
        />
      </div>

      {/* Red border frame on nuclear mode */}
      {isNuclearMode && (
        <div
          className="nuclear-alert-border"
          style={{ ...s.nuclearFrame, borderColor: color }}
        />
      )}
    </>
  );
});

export default NuclearAlertOverlay;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  backdrop: {
    position: 'fixed', inset: 0, zIndex: 200,
    pointerEvents: 'none',
    transition: 'background 0.4s ease',
  },
  overlayContainer: {
    position: 'fixed', top: 80, left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 300, width: '90%', maxWidth: 720,
  },
  alertPanel: {
    border: '2px solid',
    borderRadius: 8,
    padding: '16px 20px',
    display: 'flex', flexDirection: 'column', gap: 12,
    backdropFilter: 'blur(12px)',
  },
  alertHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
  },
  alertHeaderLeft: {
    display: 'flex', alignItems: 'center', gap: 12,
  },
  alertIcon: {
    fontSize: 32, flexShrink: 0,
  },
  alertTitle: {
    fontSize: 18, fontWeight: 900, letterSpacing: 1,
    fontFamily: 'monospace',
  },
  alertSubtitle: {
    fontSize: 12, fontWeight: 700, letterSpacing: 1.5, marginTop: 2,
    fontFamily: 'monospace',
  },
  dismissBtn: {
    background: 'transparent', border: '1px solid #334155',
    borderRadius: 4, color: 'var(--text-muted)', fontSize: 14,
    cursor: 'pointer', padding: '4px 8px', flexShrink: 0,
  },
  explanationBox: {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 6, padding: '10px 14px',
  },
  explanationLabel: {
    fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700, marginBottom: 6,
  },
  explanationText: {
    fontSize: 13, color: 'var(--text)', lineHeight: 1.6,
  },
  analogBox: {
    background: 'rgba(251,191,36,0.06)',
    border: '1px solid rgba(251,191,36,0.2)',
    borderRadius: 6, padding: '10px 14px',
  },
  analogLabel: {
    fontSize: 9, color: 'var(--warn)', letterSpacing: 2, fontWeight: 700, marginBottom: 6,
  },
  analogText: {
    fontSize: 12, color: '#cbd5e1', lineHeight: 1.6,
  },
  lockNotice: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: 'rgba(255,0,51,0.1)',
    border: '1px solid rgba(255,0,51,0.3)',
    borderRadius: 6, padding: '8px 12px',
  },
  lockIcon: { fontSize: 16 },
  lockText: {
    fontSize: 11, color: '#fca5a5', fontFamily: 'monospace', lineHeight: 1.5,
  },
  countdownTrack: {
    height: 3, background: '#1a2e4a', borderRadius: 2, overflow: 'hidden',
  },
  countdownFill: {
    height: '100%', borderRadius: 2,
  },
  nuclearFrame: {
    position: 'fixed', inset: 0, zIndex: 150,
    border: '3px solid', pointerEvents: 'none',
    borderRadius: 0,
  },
};
