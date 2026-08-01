/**
 * components/panels/RiskDashboard.tsx
 * Risk metrics panel: CVaR, position sizing, kill switch, data quality score.
 * Wired to Zustand account + orchestratorHealth slices.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { MetricTile } from '../ui/MetricTile';
import { StatusDot } from '../ui/StatusDot';
import { ConfidenceBar } from '../ui/ConfidenceBar';
import { fmtPrice, fmtPct, fmtPctRaw, fmtRatio, cn, fmtMarginLevel, marginLevelIsSafe } from '../../lib/utils';

// ── Kill switch indicator ─────────────────────────────────────────────────────

function KillSwitchBadge({ active }: { active: boolean }) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 px-3 py-1.5 rounded border text-xs font-semibold uppercase tracking-wider',
        active
          ? 'bg-[#ff1744]/10 border-[#ff1744]/30 text-[#ff1744] animate-pulse'
          : 'bg-[#00e676]/5 border-[#00e676]/20 text-[#00e676]',
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', active ? 'bg-[#ff1744]' : 'bg-[#00e676]')} />
      {active ? 'KILL SWITCH ACTIVE' : 'TRADING ENABLED'}
    </div>
  );
}

// ── Source health row ─────────────────────────────────────────────────────────

function SourceHealthRow({ name, health }: { name: string; health: Record<string, unknown> }) {
  const isAlive = health.is_alive as boolean;
  const latency = health.latency_ms as number | undefined;
  const conf    = health.confidence as number | undefined;

  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#1e2d3d] last:border-0">
      <div className="flex items-center gap-2">
        <StatusDot status={isAlive ? 'ok' : 'offline'} />
        <span className="text-[11px] text-slate-300 font-mono">{name}</span>
      </div>
      <div className="flex items-center gap-4">
        {latency != null && (
          <span className="text-[10px] font-mono text-slate-500">
            {latency.toFixed(0)}ms
          </span>
        )}
        {conf != null && (
          <span
            className="text-[10px] font-mono tabular-nums"
            style={{ color: conf > 0.8 ? '#00e676' : conf > 0.5 ? '#ffb800' : '#ff3b5c' }}
          >
            {(conf * 100).toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function RiskDashboard() {
  const navigate = useNavigate();
  const account  = useStore((s) => s.account);
  const health   = useStore((s) => s.orchestratorHealth);
  const quality  = useStore((s) => s.qualityReport);

  const killSwitch    = account?.kill_switch ?? false;
  const qualityScore  = health?.quality_score ?? null;
  const sourceHealth  = quality?.source_health as Record<string, Record<string, unknown>> | undefined;

  const marginLevel = account?.margin_level ?? 0;
  const marginColor =
    marginLevelIsSafe(marginLevel) ? '#00e676' :
    marginLevel > 100 ? '#ffb800' : '#ff3b5c';

  return (
    <Panel
      title="Risk Dashboard"
      noPad
      bodyClass="p-0"
      headerRight={
        <button
          onClick={() => navigate('/risk-calculator')}
          className="text-[10px] font-bold px-2 py-0.5 rounded"
          style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', color: '#fbbf24', cursor: 'pointer' }}
        >
          🛡 Calculator
        </button>
      }
    >
      <div className="flex flex-col h-full overflow-y-auto scrollbar-terminal">

        {/* Kill switch */}
        <div className="px-4 py-3 border-b border-[#1e2d3d]">
          <KillSwitchBadge active={killSwitch} />
        </div>

        {/* Account risk metrics */}
        <div className="grid grid-cols-2 gap-px bg-[#1e2d3d] border-b border-[#1e2d3d]">
          {[
            {
              label: 'Balance',
              value: `$${fmtPrice(account?.balance)}`,
              color: '#e2e8f0',
            },
            {
              label: 'Equity',
              value: `$${fmtPrice(account?.equity)}`,
              color: '#00d4ff',
            },
            {
              label: 'Daily P&L',
              value: account ? fmtPctRaw(account.daily_pnl_pct) : '—',
              color: account?.daily_pnl == null ? '#475569' : account.daily_pnl >= 0 ? '#00e676' : '#ff1744',
            },
            {
              label: 'Total P&L',
              value: account ? fmtPrice(account.total_pnl) : '—',
              color: account?.total_pnl == null ? '#475569' : account.total_pnl >= 0 ? '#00e676' : '#ff1744',
            },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-[#0d1421] px-4 py-3">
              <MetricTile label={label} value={value} valueColor={color} compact />
            </div>
          ))}
        </div>

        {/* Margin level */}
        <div className="px-4 py-3 border-b border-[#1e2d3d]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">Margin Level</span>
            <span className="font-mono tabular-nums text-xs font-semibold" style={{ color: marginColor }}>
              {account ? fmtMarginLevel(marginLevel) : '—'}
            </span>
          </div>
          <div className="h-1.5 bg-[#1e2d3d] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width:           `${Math.min(marginLevel / 5, 100)}%`,
                backgroundColor: marginColor,
              }}
            />
          </div>
          <div className="flex justify-between mt-1">
            <span className="text-[9px] text-slate-700">0%</span>
            <span className="text-[9px] text-slate-700">500%</span>
          </div>
        </div>

        {/* Risk ratios */}
        <div className="px-4 py-3 border-b border-[#1e2d3d] grid grid-cols-2 gap-3">
          <MetricTile
            label="CVaR 95%"
            value={account?.cvar_95 != null ? `${(account.cvar_95 * 100).toFixed(1)}%` : '—'}
            valueColor="#ff3b5c"
            compact
          />
          <MetricTile
            label="Max Drawdown"
            value={fmtPct(account?.max_drawdown, 1)}
            valueColor="#ff3b5c"
            compact
          />
          <MetricTile
            label="Win Rate"
            value={fmtPct(account?.win_rate, 1)}
            valueColor="#00e676"
            compact
          />
          <MetricTile
            label="Sharpe"
            value={account ? fmtRatio(account.sharpe_ratio) : '—'}
            valueColor="#00d4ff"
            compact
          />
        </div>

        {/* Data quality score */}
        {qualityScore != null && (
          <div className="px-4 py-3 border-b border-[#1e2d3d]">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] text-slate-500 uppercase tracking-wider">Data Quality Score</span>
              <span
                className="font-mono tabular-nums text-xs font-semibold"
                style={{ color: qualityScore > 0.8 ? '#00e676' : qualityScore > 0.5 ? '#ffb800' : '#ff3b5c' }}
              >
                {(qualityScore * 100).toFixed(0)}%
              </span>
            </div>
            <ConfidenceBar value={qualityScore} height="md" />
            {quality && (
              <div className="flex items-center gap-4 mt-2">
                <span className="text-[9px] text-slate-600">
                  {quality.ticks_accepted}/{quality.ticks_received} accepted
                </span>
                <span className="text-[9px] text-slate-600">
                  {quality.active_sources.length} sources
                </span>
                <span className="text-[9px] text-slate-600">
                  Primary: {quality.primary_source}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Feed source health */}
        {sourceHealth && Object.keys(sourceHealth).length > 0 && (
          <div className="px-4 py-3">
            <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-2">
              Feed Sources
            </span>
            {Object.entries(sourceHealth).map(([name, h]) => (
              <SourceHealthRow key={name} name={name} health={h} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const RiskDashboardGuarded = withPanelGuard(RiskDashboard, 'Risk Dashboard', 4);
