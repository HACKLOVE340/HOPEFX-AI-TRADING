/**
 * Prop Firm Challenge Tracker — live drawdown, profit target, trading days.
 *
 * Wires to: GET /api/risk/prop-firm-status  (every 10s)
 *
 * Uses TanStack Query for data fetching (retry, stale-while-revalidate,
 * deduplication) and usePolling to pause polling when the tab is hidden.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../hooks/useApi';
import { usePolling } from '../hooks/usePolling';
import { useStore, selectIsAuth, useHasHydrated } from '../store';

interface PropFirmStatus {
  daily_loss_pct: number;
  daily_loss_limit: number;
  max_drawdown_pct: number;
  max_drawdown_limit: number;
  profit_target_pct: number;
  profit_target_amount: number;
  profit_target_goal: number;
  trading_days_completed: number;
  trading_days_required: number;
  paused: boolean;
  kill_switch_active: boolean;
  ai_message: string;
  current_equity: number;
  starting_equity: number;
}

// ── Progress bar ──────────────────────────────────────────────────────────────

const ProgressBar: React.FC<{
  label: string;
  value: number;
  limit: number;
  amount?: string;
  invert?: boolean;
}> = ({ label, value, limit, amount, invert = false }) => {
  const pct    = Math.min((value / limit) * 100, 100);
  const danger = invert ? pct >= 100 : pct >= 95;
  const warn   = !invert && pct >= 80;

  const barColor = danger ? '#ef4444' : warn ? '#f59e0b' : invert ? '#22c55e' : '#3b82f6';
  const labelColor = danger ? '#f87171' : warn ? '#fbbf24' : '#cbd5e1';

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 13, color: '#94a3b8' }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'monospace', color: labelColor }}>
          {amount ?? `${(value * 100).toFixed(2)}% / ${(limit * 100).toFixed(0)}%`}
        </span>
      </div>
      <div style={{ width: '100%', background: '#334155', borderRadius: 6, height: 12, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 6,
          background: barColor, transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const PropFirmTracker: React.FC = () => {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const enabled  = hydrated && isAuth;

  const { data: status, error, isLoading, refetch } = useQuery<PropFirmStatus>({
    queryKey:        ['prop-firm-status'],
    queryFn:         async () => {
      const res = await api.get<PropFirmStatus>('/risk/prop-firm-status');
      return res.data;
    },
    enabled,
    staleTime:       8_000,
    // Polling is driven by usePolling below so the interval pauses when the
    // tab is hidden — avoids unnecessary requests while the user is away.
    refetchInterval: false,
    retry:           2,
  });

  // Pause polling when the tab is hidden; resume + immediate refetch on focus.
  usePolling(() => { if (enabled) refetch(); }, 10_000);

  const statusIcon = !status ? null
    : status.kill_switch_active ? '❌'
    : status.paused ? '⚠️'
    : '✅';

  const bannerStyle: React.CSSProperties = !status ? {} : {
    background: status.kill_switch_active ? '#450a0a'
      : status.paused ? '#431407'
      : '#052e16',
    border: `1px solid ${status.kill_switch_active ? '#7f1d1d' : status.paused ? '#92400e' : '#14532d'}`,
    color: status.kill_switch_active ? '#fca5a5'
      : status.paused ? '#fcd34d'
      : '#86efac',
  };

  const errorMsg = error instanceof Error ? error.message : error ? String(error) : null;

  return (
    <div style={s.page}>
      <div style={s.header}>
        <span style={{ fontSize: 28 }}>🛡️</span>
        <h1 style={s.title}>Prop Firm Challenge Tracker</h1>
        {statusIcon && <span style={{ fontSize: 22 }}>{statusIcon}</span>}
      </div>

      {isLoading && <div style={s.loading}>Loading challenge status…</div>}

      {errorMsg && (
        <div style={s.errorBox}>{errorMsg}</div>
      )}

      {status && (
        <>
          {/* AI message banner */}
          <div style={{ ...s.banner, ...bannerStyle }}>
            🤖 AI: {status.ai_message}
          </div>

          {/* Equity summary */}
          <div style={s.equityGrid}>
            <div style={s.equityCard}>
              <div style={s.equityLabel}>Current Equity</div>
              <div style={s.equityValue}>
                ${status.current_equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div style={s.equityCard}>
              <div style={s.equityLabel}>Starting Equity</div>
              <div style={{ ...s.equityValue, color: '#94a3b8' }}>
                ${status.starting_equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>

          {/* Progress bars */}
          <div style={s.progressCard}>
            <ProgressBar
              label="Daily Loss"
              value={status.daily_loss_pct}
              limit={status.daily_loss_limit}
              amount={`${(status.daily_loss_pct * 100).toFixed(2)}% / ${(status.daily_loss_limit * 100).toFixed(0)}% limit`}
            />
            <ProgressBar
              label="Max Drawdown"
              value={status.max_drawdown_pct}
              limit={status.max_drawdown_limit}
              amount={`${(status.max_drawdown_pct * 100).toFixed(2)}% / ${(status.max_drawdown_limit * 100).toFixed(0)}% limit`}
            />
            <ProgressBar
              label="Profit Target"
              value={status.profit_target_pct}
              limit={1.0}
              invert
              amount={`$${status.profit_target_amount.toFixed(0)} / $${status.profit_target_goal.toFixed(0)}`}
            />

            {/* Trading days */}
            <div style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 13, color: '#94a3b8' }}>📅 Trading Days</span>
                <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'monospace', color: '#cbd5e1' }}>
                  {status.trading_days_completed} / {status.trading_days_required}
                </span>
              </div>
              <div style={{ width: '100%', background: '#334155', borderRadius: 6, height: 12, overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.min((status.trading_days_completed / status.trading_days_required) * 100, 100)}%`,
                  height: '100%', borderRadius: 6, background: '#3b82f6', transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
          </div>

          {/* P&L summary */}
          <div style={s.pnlRow}>
            <span style={{ fontSize: 14, color: '#94a3b8' }}>📈 P&L:</span>
            <span style={{
              fontSize: 16, fontWeight: 700,
              color: status.profit_target_amount >= 0 ? '#4ade80' : '#f87171',
            }}>
              {status.profit_target_amount >= 0 ? '+' : ''}${status.profit_target_amount.toFixed(2)}
            </span>
          </div>
        </>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:        { padding: 24, maxWidth: 700, margin: '0 auto' },
  header:      { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 },
  title:       { fontSize: 22, fontWeight: 700, color: '#f1f5f9', margin: 0, flex: 1 },
  loading:     { textAlign: 'center', color: '#475569', padding: 48 },
  errorBox:    { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', padding: '12px 16px', marginBottom: 16, fontSize: 13 },
  banner:      { borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 14, fontWeight: 500 },
  equityGrid:  { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 },
  equityCard:  { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  equityLabel: { fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  equityValue: { fontSize: 22, fontWeight: 700, fontFamily: 'monospace', color: '#f1f5f9' },
  progressCard:{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: '20px 24px', marginBottom: 16 },
  pnlRow:      { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 0' },
};

export default PropFirmTracker;
