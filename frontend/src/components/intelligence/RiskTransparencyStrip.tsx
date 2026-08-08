/**
 * RiskTransparencyStrip — makes the live risk state visible: kill-switch,
 * daily loss, drawdown, open risk, and tail-risk (CVaR) + Sharpe.
 *
 * Read-only. Sourced from data already in the store:
 *   - riskSnapshot (WS chart-bot channel): daily_loss_pct, max_drawdown_pct,
 *     open_risk_pct, kill_switch_active
 *   - account (AccountMetrics): cvar_95, sharpe_ratio, max_drawdown, kill_switch
 *
 * This surface does NOT change any risk gate — it only reflects the gate state
 * the risk manager already enforces.
 */

import React from 'react';
import { useStore, selectRiskSnapshot, selectAccount, selectKillSwitch } from '../../store';

const fmtPct = (v: number | null | undefined, dp = 1): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(dp)}%`;

const Cell: React.FC<{
  label: string;
  value: string;
  tone?: 'ok' | 'warn' | 'bad' | 'muted';
  title?: string;
}> = ({ label, value, tone = 'muted', title }) => {
  const fg = { ok: '#22c55e', warn: '#fbbf24', bad: '#f87171', muted: '#e2e8f0' }[tone];
  return (
    <div title={title} style={{
      flex: 1, minWidth: 120, padding: '10px 12px',
      background: '#0f172a', border: '1px solid #1e293b', borderRadius: 9,
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 800, color: fg, marginTop: 2 }}>{value}</div>
    </div>
  );
};

export const RiskTransparencyStrip: React.FC = () => {
  const risk    = useStore(selectRiskSnapshot);
  const account = useStore(selectAccount);

  // Shared selector — see S10-02.
  const killSwitch = useStore(selectKillSwitch);

  // Prefer the live WS snapshot; fall back to account metrics where present.
  const dailyLoss   = risk?.daily_loss_pct;
  const ddLimit     = risk?.max_drawdown_pct;
  const openRisk    = risk?.open_risk_pct ?? account?.open_risk_pct;
  // account.max_drawdown is a fraction (e.g. -0.05) → render as %.
  const realizedDd  = account?.max_drawdown != null ? Math.abs(account.max_drawdown) * 100 : undefined;
  // cvar_95 is a fraction 0–1.
  const cvar        = account?.cvar_95 != null ? account.cvar_95 * 100 : undefined;
  const sharpe      = account?.sharpe_ratio;

  const hasAny = risk != null || account != null;

  return (
    <div style={{
      background: '#0d1421',
      border: `1px solid ${killSwitch ? 'rgba(248,113,113,0.4)' : '#1e293b'}`,
      borderRadius: 12, padding: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>🛡️ Risk State</span>
        <span style={{
          fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 5,
          textTransform: 'uppercase', letterSpacing: '0.06em',
          color: killSwitch ? '#f87171' : '#22c55e',
          background: killSwitch ? 'rgba(248,113,113,0.12)' : 'rgba(34,197,94,0.12)',
          border: `1px solid ${killSwitch ? 'rgba(248,113,113,0.35)' : 'rgba(34,197,94,0.3)'}`,
        }}>
          {killSwitch ? '⛔ Kill switch active' : '✓ Trading enabled'}
        </span>
      </div>

      {!hasAny ? (
        <div style={{ fontSize: 13, color: '#475569' }}>
          Risk telemetry will appear once the live feed is connected.
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Cell
            label="Daily loss"
            value={fmtPct(dailyLoss)}
            tone={dailyLoss == null ? 'muted' : dailyLoss <= 0 ? 'ok' : dailyLoss > 3 ? 'bad' : 'warn'}
            title="Realised + unrealised loss so far today, as a % of equity."
          />
          <Cell
            label="Max DD limit"
            value={fmtPct(ddLimit)}
            tone="muted"
            title="The maximum drawdown the risk manager allows before halting trading."
          />
          <Cell
            label="Realised DD"
            value={fmtPct(realizedDd)}
            tone={realizedDd == null ? 'muted' : realizedDd > 10 ? 'bad' : realizedDd > 5 ? 'warn' : 'ok'}
            title="Largest peak-to-trough equity decline recorded."
          />
          <Cell
            label="Open risk"
            value={fmtPct(openRisk)}
            tone={openRisk == null ? 'muted' : openRisk > 5 ? 'warn' : 'ok'}
            title="Total equity at risk across all open positions if every stop is hit."
          />
          <Cell
            label="CVaR 95%"
            value={fmtPct(cvar, 2)}
            tone={cvar == null ? 'muted' : cvar > 5 ? 'warn' : 'ok'}
            title="Conditional Value at Risk — expected loss in the worst 5% of outcomes."
          />
          <Cell
            label="Sharpe"
            value={sharpe == null || !Number.isFinite(sharpe) ? '—' : sharpe.toFixed(2)}
            tone={sharpe == null ? 'muted' : sharpe >= 1 ? 'ok' : sharpe >= 0 ? 'warn' : 'bad'}
            title="Risk-adjusted return. >1 is good, <0 means losing relative to risk taken."
          />
        </div>
      )}
    </div>
  );
};

export default RiskTransparencyStrip;
