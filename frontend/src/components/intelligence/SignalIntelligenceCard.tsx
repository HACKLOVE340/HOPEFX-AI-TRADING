/**
 * SignalIntelligenceCard — renders a single engine signal with the full
 * intelligence context the API already provides but the UI used to drop:
 * calibrated confidence, categorical strength, model consensus (how many
 * strategies agreed), risk/reward, market regime/session, and the raw
 * pre-calibration probability + model version from `metadata`.
 *
 * Pure presentational component (read-only). Source: GET /api/signals/*.
 */

import React from 'react';
import type { EngineSignal, SignalStrength } from '../../types';

// ── Strength styling ──────────────────────────────────────────────────────────
const STRENGTH_META: Record<SignalStrength, { label: string; color: string }> = {
  very_strong: { label: 'Very Strong', color: '#22c55e' },
  strong:      { label: 'Strong',      color: '#4ade80' },
  moderate:    { label: 'Moderate',    color: '#fbbf24' },
  weak:        { label: 'Weak',        color: '#fb923c' },
  very_weak:   { label: 'Very Weak',   color: '#f87171' },
};

const dirMeta = (d: EngineSignal['direction']) =>
  d === 'buy'  ? { label: 'BUY',  color: '#22c55e', arrow: '▲' } :
  d === 'sell' ? { label: 'SELL', color: '#f87171', arrow: '▼' } :
                 { label: 'HOLD', color: '#94a3b8', arrow: '■' };

const num = (v: unknown, dp = 2): string =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(dp) : '—';

// ── Confidence meter ──────────────────────────────────────────────────────────
const ConfidenceMeter: React.FC<{ value: number; raw?: number }> = ({ value, raw }) => {
  const calibrated = Math.max(0, Math.min(1, value));
  const color = calibrated >= 0.7 ? '#22c55e' : calibrated >= 0.55 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ minWidth: 0, flex: 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>
          Confidence
        </span>
        <span style={{ fontSize: 12, fontWeight: 700, color }}>
          {(calibrated * 100).toFixed(0)}%
          {raw != null && Number.isFinite(raw) && (
            <span style={{ color: '#475569', fontWeight: 500 }}> · raw {(raw * 100).toFixed(0)}%</span>
          )}
        </span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: '#1e293b', overflow: 'hidden', position: 'relative' }}>
        <div style={{ width: `${calibrated * 100}%`, height: '100%', background: color, transition: 'width 0.3s' }} />
        {/* raw probability tick for calibration comparison */}
        {raw != null && Number.isFinite(raw) && (
          <div style={{
            position: 'absolute', top: -1, bottom: -1,
            left: `${Math.max(0, Math.min(1, raw)) * 100}%`,
            width: 2, background: '#cbd5e1', opacity: 0.6,
          }} />
        )}
      </div>
    </div>
  );
};

const Chip: React.FC<{ children: React.ReactNode; title?: string; color?: string }> = ({ children, title, color }) => (
  <span title={title} style={{
    fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 5,
    background: 'rgba(148,163,184,0.08)', border: '1px solid #1e293b',
    color: color ?? '#94a3b8', whiteSpace: 'nowrap',
  }}>
    {children}
  </span>
);

export const SignalIntelligenceCard: React.FC<{ signal: EngineSignal }> = ({ signal }) => {
  const dir = dirMeta(signal.direction);
  const strength = STRENGTH_META[signal.strength] ?? STRENGTH_META.moderate;
  const meta = signal.metadata ?? {};
  const rawProb = typeof meta.probability === 'number' ? meta.probability : undefined;
  const modelVersion = typeof meta.model_version === 'string' ? meta.model_version : undefined;
  const consensus = signal.total_strategies > 0
    ? signal.strategies_agreeing.length / signal.total_strategies
    : 0;
  const stale = signal.is_valid === false;

  return (
    <div style={{
      background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12,
      padding: 14, opacity: stale ? 0.6 : 1,
    }}>
      {/* Header: symbol + direction + strength */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 800, color: '#f1f5f9' }}>{signal.symbol}</span>
        <span style={{
          fontSize: 11, fontWeight: 800, padding: '2px 8px', borderRadius: 5,
          color: dir.color, background: `${dir.color}1a`, border: `1px solid ${dir.color}40`,
        }}>
          {dir.arrow} {dir.label}
        </span>
        <span title="Categorical signal strength tier" style={{
          fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
          color: strength.color, background: `${strength.color}14`, border: `1px solid ${strength.color}33`,
          textTransform: 'uppercase', letterSpacing: '0.04em',
        }}>
          {strength.label}
        </span>
        {stale && <Chip color="#f87171" title="Signal past its expiry">expired</Chip>}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#334155' }}>
          {signal.timeframe} · {new Date(signal.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {/* Confidence meter (calibrated vs raw) */}
      <div style={{ marginBottom: 12 }}>
        <ConfidenceMeter value={signal.confidence} raw={rawProb} />
      </div>

      {/* Levels */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        {([
          ['Entry', signal.entry_price, '#cbd5e1'],
          ['Stop',  signal.stop_loss,   '#f87171'],
          ['Target',signal.take_profit, '#22c55e'],
        ] as const).map(([label, val, color]) => (
          <div key={label} style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>{label}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color }}>{num(val)}</div>
          </div>
        ))}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>R:R</div>
          <div style={{ fontSize: 13, fontWeight: 700, color: signal.risk_reward_ratio >= 1.5 ? '#22c55e' : '#fbbf24' }}>
            {num(signal.risk_reward_ratio, 2)}
          </div>
        </div>
      </div>

      {/* Model consensus bar */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>
            Model consensus
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#93c5fd' }}>
            {signal.strategies_agreeing.length}/{signal.total_strategies} agree
          </span>
        </div>
        <div style={{ height: 5, borderRadius: 3, background: '#1e293b', overflow: 'hidden' }}>
          <div style={{ width: `${consensus * 100}%`, height: '100%', background: '#3b82f6' }} />
        </div>
        {signal.strategies_agreeing.length > 0 && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }}>
            {signal.strategies_agreeing.map((s) => <Chip key={s}>{s}</Chip>)}
          </div>
        )}
      </div>

      {/* Context chips */}
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {signal.regime  && <Chip title="Market regime at signal time">📈 {signal.regime}</Chip>}
        {signal.session && <Chip title="Trading session">🕐 {signal.session}</Chip>}
        {modelVersion   && <Chip title="Model version that produced this signal" color="#93c5fd">⚙ {modelVersion}</Chip>}
      </div>
    </div>
  );
};

export default SignalIntelligenceCard;
