/**
 * RiskHeatmap.tsx
 * Real-time risk heatmap: CVaR, VaR, position sizing, drawdown,
 * kill switch status, and data quality score from the orchestrator.
 */

import React, { memo, useMemo } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import { useRiskMetrics } from '../hooks/useChartData';
import { COLORS } from '../utils/design-tokens';
import { formatPnl, formatPct, riskColor, clamp } from '../utils/formatters';
import type { RiskMetrics } from '../types';

// ─── Risk Score Ring ──────────────────────────────────────────────────────────

const RiskRing = memo(({ score }: { score: number }) => {
  const color  = riskColor(score);
  const r      = 36;
  const cx     = 44, cy = 44;
  const circ   = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const label  = score < 25 ? 'LOW' : score < 50 ? 'MODERATE' : score < 75 ? 'HIGH' : 'CRITICAL';

  return (
    <div style={rh.ringWrapper}>
      <svg width={88} height={88}>
        {/* Background ring */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={COLORS.bg.elevated} strokeWidth={8} />
        {/* Filled ring */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeDashoffset={circ * 0.25}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${color}88)` }}
        />
        {/* Score */}
        <text x={cx} y={cy - 4} textAnchor="middle" fill={color}
          fontSize={18} fontFamily='"JetBrains Mono", monospace' fontWeight={700}>
          {score.toFixed(0)}
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill={color}
          fontSize={8} fontFamily='"JetBrains Mono", monospace' letterSpacing="0.08em">
          {label}
        </text>
      </svg>
      <div style={rh.ringLabel}>RISK SCORE</div>
    </div>
  );
});
RiskRing.displayName = 'RiskRing';

// ─── Kill Switch Banner ───────────────────────────────────────────────────────

const KillSwitchBanner = memo(({ active, reason }: { active: boolean; reason: string | null }) => {
  if (!active) return (
    <div style={{ ...rh.ksBanner, ...rh.ksOk }}>
      <span style={rhDynamic.ksDot(COLORS.profit.base)} />
      <span style={{ ...rh.ksText, color: COLORS.profit.base }}>KILL SWITCH INACTIVE — TRADING ENABLED</span>
    </div>
  );
  return (
    <div style={{ ...rh.ksBanner, ...rh.ksActive }}>
      <span style={rhDynamic.ksDot(COLORS.loss.strong)} />
      <div>
        <div style={{ ...rh.ksText, color: COLORS.loss.strong }}>⚠ KILL SWITCH ACTIVE — TRADING HALTED</div>
        {reason && <div style={rh.ksReason}>{reason}</div>}
      </div>
    </div>
  );
});
KillSwitchBanner.displayName = 'KillSwitchBanner';

// ─── Metric Row ───────────────────────────────────────────────────────────────

const MetricRow = memo(({
  label, value, color, bar, barColor, barMax = 100, warning,
}: {
  label: string; value: string; color?: string;
  bar?: number; barColor?: string; barMax?: number;
  warning?: boolean;
}) => (
  <div style={rh.metricRow}>
    <span style={rh.metricLabel}>{label}</span>
    <div style={rh.metricRight}>
      {bar !== undefined && (
        <div style={rh.metricBarBg}>
          <div style={{
            ...rh.metricBarFill,
            width: `${clamp((bar / barMax) * 100, 0, 100)}%`,
            background: barColor ?? COLORS.neon.cyan,
          }} />
        </div>
      )}
      <span style={{ ...rh.metricValue, color: color ?? COLORS.text.primary }}>
        {warning && <span style={{ color: COLORS.neon.amber, marginRight: 4 }}>⚠</span>}
        {value}
      </span>
    </div>
  </div>
));
MetricRow.displayName = 'MetricRow';

// ─── Data Quality Indicator ───────────────────────────────────────────────────

const DataQuality = memo(({ score }: { score: number }) => {
  const pct   = score * 100;
  const color = pct >= 90 ? COLORS.profit.base : pct >= 70 ? COLORS.neon.gold : COLORS.loss.base;
  const label = pct >= 90 ? 'EXCELLENT' : pct >= 70 ? 'DEGRADED' : 'POOR';
  return (
    <div style={rh.dqRow}>
      <span style={rh.metricLabel}>DATA QUALITY</span>
      <div style={rh.dqRight}>
        <div style={rh.dqBarBg}>
          <div style={{ ...rh.dqBarFill, width: `${pct}%`, background: color }} />
        </div>
        <span style={{ ...rh.dqLabel, color }}>{label} {pct.toFixed(0)}%</span>
      </div>
    </div>
  );
});
DataQuality.displayName = 'DataQuality';

// ─── CVaR Heatmap Grid ────────────────────────────────────────────────────────

const CVaRGrid = memo(({ metrics }: { metrics: RiskMetrics }) => {
  const cells = [
    { label: 'VaR 95%',  value: formatPnl(-Math.abs(metrics.var95)),  color: riskColor(Math.abs(metrics.var95 / 100) * 100) },
    { label: 'VaR 99%',  value: formatPnl(-Math.abs(metrics.var99)),  color: riskColor(Math.abs(metrics.var99 / 100) * 100 * 1.2) },
    { label: 'CVaR 95%', value: formatPnl(-Math.abs(metrics.cvar95)), color: riskColor(Math.abs(metrics.cvar95 / 100) * 100 * 1.1) },
    { label: 'CVaR 99%', value: formatPnl(-Math.abs(metrics.cvar99)), color: riskColor(Math.abs(metrics.cvar99 / 100) * 100 * 1.3) },
  ];

  return (
    <div style={rh.cvarGrid}>
      {cells.map((c) => (
        <div key={c.label} style={{ ...rh.cvarCell, border: `1px solid ${c.color}33`, background: `${c.color}0a` }}>
          <span style={rh.cvarLabel}>{c.label}</span>
          <span style={{ ...rh.cvarValue, color: c.color }}>{c.value}</span>
        </div>
      ))}
    </div>
  );
});
CVaRGrid.displayName = 'CVaRGrid';

// ─── Daily Loss Meter ─────────────────────────────────────────────────────────

const DailyLossMeter = memo(({ used, limit }: { used: number; limit: number }) => {
  if (!limit) return null;
  const pct   = clamp((used / limit) * 100, 0, 100);
  const color = pct < 50 ? COLORS.profit.base : pct < 80 ? COLORS.neon.gold : COLORS.loss.base;
  return (
    <div style={rh.dlMeter}>
      <div style={rh.dlHeader}>
        <span style={rh.metricLabel}>DAILY LOSS LIMIT</span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color }}>
          {formatPnl(used)} / {formatPnl(limit)} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div style={rh.dlBarBg}>
        <div style={{ ...rh.dlBarFill, width: `${pct}%`, background: color }} />
        {/* Warning threshold at 80% */}
        <div style={{ ...rh.dlThreshold, left: '80%' }} />
      </div>
    </div>
  );
});
DailyLossMeter.displayName = 'DailyLossMeter';

// ─── Main Component ───────────────────────────────────────────────────────────

const RiskHeatmap: React.FC = () => {
  const riskStore = useChartBotStore((s) => s.riskMetrics);
  const { data: riskFetched } = useRiskMetrics();
  const risk = riskStore ?? riskFetched;

  const marginWarning = (risk?.marginUtilisation ?? 0) > 0.7;
  const ddWarning     = Math.abs(risk?.currentDrawdown ?? 0) > 5;

  if (!risk) {
    return (
      <div style={rh.wrapper}>
        <div style={rh.header}><span style={rh.title}>RISK MONITOR</span></div>
        <div style={rh.noData}>Awaiting risk data…</div>
      </div>
    );
  }

  return (
    <div style={rh.wrapper}>
      {/* Header */}
      <div style={rh.header}>
        <span style={rh.title}>RISK MONITOR</span>
        <span style={{ ...rh.riskBadge, color: riskColor(risk.riskScore), background: `${riskColor(risk.riskScore)}18`, border: `1px solid ${riskColor(risk.riskScore)}44` }}>
          {risk.riskScore < 25 ? 'LOW RISK' : risk.riskScore < 50 ? 'MODERATE' : risk.riskScore < 75 ? 'HIGH RISK' : 'CRITICAL'}
        </span>
      </div>

      <div style={rh.body}>
        {/* Kill switch */}
        <KillSwitchBanner active={risk.killSwitchActive} reason={risk.killSwitchReason} />

        {/* Risk ring + CVaR grid */}
        <div style={rh.topSection}>
          <RiskRing score={risk.riskScore} />
          <CVaRGrid metrics={risk} />
        </div>

        {/* Daily loss meter */}
        <DailyLossMeter used={risk.dailyLossUsed} limit={risk.dailyLossLimit} />

        {/* Metrics */}
        <div style={rh.metricsSection}>
          <MetricRow
            label="POSITION SIZE"
            value={`${risk.positionSizePct.toFixed(1)}% / ${formatPnl(risk.maxPositionSize)}`}
            bar={risk.positionSizePct}
            barColor={riskColor(risk.positionSizePct * 2)}
            barMax={50}
          />
          <MetricRow
            label="CURRENT DD"
            value={formatPct(risk.currentDrawdown)}
            color={ddWarning ? COLORS.loss.base : COLORS.text.primary}
            bar={Math.abs(risk.currentDrawdown)}
            barColor={COLORS.loss.base}
            barMax={20}
            warning={ddWarning}
          />
          <MetricRow
            label="MAX DRAWDOWN"
            value={formatPct(risk.maxDrawdown)}
            color={COLORS.loss.muted}
            bar={Math.abs(risk.maxDrawdown)}
            barColor={COLORS.loss.muted}
            barMax={30}
          />
          <MetricRow
            label="MARGIN UTIL"
            value={`${(risk.marginUtilisation * 100).toFixed(1)}%`}
            color={marginWarning ? COLORS.neon.amber : COLORS.text.primary}
            bar={risk.marginUtilisation * 100}
            barColor={marginWarning ? COLORS.neon.amber : COLORS.neon.cyan}
            barMax={100}
            warning={marginWarning}
          />
        </div>

        {/* Data quality */}
        <DataQuality score={risk.dataQualityScore} />
      </div>
    </div>
  );
};

// ─── Dynamic style helpers ────────────────────────────────────────────────────

const rhDynamic = {
  ksDot: (color: string): React.CSSProperties => ({
    width: 8, height: 8, borderRadius: '50%',
    background: color,
    boxShadow: `0 0 8px ${color}`,
    flexShrink: 0, marginTop: 2,
  }),
};

// ─── Static styles ────────────────────────────────────────────────────────────

const rh: Record<string, React.CSSProperties> = {
  wrapper: {
    background: COLORS.bg.surface,
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 8, overflow: 'hidden',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 14px 8px',
    borderBottom: `1px solid ${COLORS.bg.border}`,
  },
  title: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10, fontWeight: 700,
    color: COLORS.text.muted, letterSpacing: '0.12em',
  },
  riskBadge: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9, fontWeight: 700,
    padding: '2px 7px', borderRadius: 4, letterSpacing: '0.06em',
  },
  body: { padding: '10px 12px', display: 'flex', flexDirection: 'column' as const, gap: 10 },

  ksBanner: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    padding: '7px 10px', borderRadius: 6,
  },
  ksOk: {
    background: `${COLORS.profit.base}0d`,
    border: `1px solid ${COLORS.profit.border}`,
  },
  ksActive: {
    background: `${COLORS.loss.base}18`,
    border: `1px solid ${COLORS.loss.base}66`,
    animation: 'pulse 2s infinite',
  },
  ksText: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, letterSpacing: '0.06em' },
  ksReason: { fontFamily: '"Inter", sans-serif', fontSize: 10, color: COLORS.text.secondary, marginTop: 2 },

  topSection: { display: 'flex', alignItems: 'center', gap: 12 },
  ringWrapper: { display: 'flex', flexDirection: 'column' as const, alignItems: 'center', gap: 2, flexShrink: 0 },
  ringLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, letterSpacing: '0.1em' },

  cvarGrid: { flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 },
  cvarCell: { borderRadius: 5, padding: '6px 8px', display: 'flex', flexDirection: 'column' as const, gap: 2 },
  cvarLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, letterSpacing: '0.06em' },
  cvarValue: { fontFamily: '"JetBrains Mono", monospace', fontSize: 11, fontWeight: 700 },

  dlMeter: { display: 'flex', flexDirection: 'column' as const, gap: 5 },
  dlHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  dlBarBg: { height: 6, background: COLORS.bg.elevated, borderRadius: 3, overflow: 'hidden', position: 'relative' as const },
  dlBarFill: { height: '100%', borderRadius: 3, transition: 'width 400ms ease' },
  dlThreshold: { position: 'absolute' as const, top: 0, bottom: 0, width: 1, background: COLORS.neon.amber, opacity: 0.6 },

  metricsSection: { display: 'flex', flexDirection: 'column' as const, gap: 7 },
  metricRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  metricLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, letterSpacing: '0.06em', flexShrink: 0 },
  metricRight: { display: 'flex', alignItems: 'center', gap: 8, flex: 1, justifyContent: 'flex-end' as const },
  metricBarBg: { width: 60, height: 3, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  metricBarFill: { height: '100%', borderRadius: 2, transition: 'width 400ms ease' },
  metricValue: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, minWidth: 80, textAlign: 'right' as const },

  dqRow: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingTop: 6, borderTop: `1px solid ${COLORS.bg.border}` },
  dqRight: { display: 'flex', alignItems: 'center', gap: 8 },
  dqBarBg: { width: 60, height: 3, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  dqBarFill: { height: '100%', borderRadius: 2, transition: 'width 400ms ease' },
  dqLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700 },

  noData: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.text.muted, padding: '20px', textAlign: 'center' as const },
};

export default memo(RiskHeatmap);
