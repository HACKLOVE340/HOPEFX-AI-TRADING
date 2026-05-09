/**
 * Prop Firm Challenge Tracker — live drawdown, profit target, trading days.
 *
 * Wires to: GET /api/risk/prop-firm-status  (every 10s)
 *
 * Uses TanStack Query for data fetching (retry, stale-while-revalidate,
 * deduplication) and usePolling to pause polling when the tab is hidden.
 */

import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { propFirmExtApi } from '../hooks/useApi';
import { usePolling } from '../hooks/usePolling';
import { useStore, selectIsAuth, useHasHydrated } from '../store';
import { extractApiError } from '../lib/utils';

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

interface ChallengeRecord {
  challenge_id: string;
  account_size: number;
  phase: string;
  result: 'passed' | 'failed' | 'active';
  started_at: string;
  ended_at: string | null;
  profit_pct: number;
  max_drawdown_pct: number;
}

interface BreachAlert {
  alert_id: string;
  alert_type: string;
  message: string;
  severity: 'warning' | 'critical';
  created_at: string;
  acknowledged: boolean;
}

interface DailyStat {
  date: string;
  pnl: number;
  trades: number;
  drawdown_pct: number;
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
  const navigate = useNavigate();
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const enabled  = hydrated && isAuth;
  const [activeTab, setActiveTab] = useState<'live' | 'history' | 'alerts' | 'daily'>('live');
  const [ackingId, setAckingId]   = useState<string | null>(null);

  const { data: status, error, isLoading, refetch } = useQuery<PropFirmStatus>({
    queryKey:        ['prop-firm-status'],
    queryFn:         async () => (await propFirmExtApi.status()).data as PropFirmStatus,
    enabled,
    staleTime:       8_000,
    refetchInterval: false,
    retry:           2,
  });

  const historyQ = useQuery<ChallengeRecord[]>({
    queryKey: ['prop-firm-history'],
    queryFn:  async () => {
      const r = await propFirmExtApi.history();
      const d = r.data as ChallengeRecord[] | { challenges?: ChallengeRecord[] };
      return Array.isArray(d) ? d : (d.challenges ?? []);
    },
    enabled: enabled && activeTab === 'history',
    staleTime: 60_000,
  });

  const alertsQ = useQuery<BreachAlert[]>({
    queryKey: ['prop-firm-alerts'],
    queryFn:  async () => {
      const r = await propFirmExtApi.breachAlerts();
      const d = r.data as BreachAlert[] | { alerts?: BreachAlert[] };
      return Array.isArray(d) ? d : (d.alerts ?? []);
    },
    enabled: enabled && activeTab === 'alerts',
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const dailyQ = useQuery<DailyStat[]>({
    queryKey: ['prop-firm-daily'],
    queryFn:  async () => {
      const r = await propFirmExtApi.dailyStats();
      const d = r.data as DailyStat[] | { stats?: DailyStat[] };
      return Array.isArray(d) ? d : (d.stats ?? []);
    },
    enabled: enabled && activeTab === 'daily',
    staleTime: 60_000,
  });

  const handleAcknowledge = useCallback(async (alertId: string) => {
    setAckingId(alertId);
    try {
      await propFirmExtApi.acknowledgeAlert(alertId);
      alertsQ.refetch();
    } catch { /* non-fatal */ }
    finally { setAckingId(null); }
  }, [alertsQ]);

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

  const errorMsg = error ? extractApiError(error, 'An error occurred') : null;

  return (
    <div className="page-content">
      <div style={s.header}>
        <span style={{ fontSize: 28 }}>🛡️</span>
        <h1 style={s.title}>Prop Firm Challenge Tracker</h1>
        {statusIcon && <span style={{ fontSize: 22 }}>{statusIcon}</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {(['live', 'history', 'alerts', 'daily'] as const).map(t => (
            <button key={t} onClick={() => setActiveTab(t)} style={{
              background: activeTab === t ? '#1e3a5f' : '#1e293b',
              border: `1px solid ${activeTab === t ? '#3b82f6' : '#334155'}`,
              borderRadius: 8, color: activeTab === t ? '#60a5fa' : '#64748b',
              cursor: 'pointer', fontSize: 12, fontWeight: 600, padding: '6px 12px',
            }}>
              {t === 'live' ? '📊 Live' : t === 'history' ? '📋 History' : t === 'alerts' ? `🚨 Alerts${alertsQ.data?.filter(a => !a.acknowledged).length ? ` (${alertsQ.data.filter(a => !a.acknowledged).length})` : ''}` : '📅 Daily'}
            </button>
          ))}
          <div style={{ width: 1, height: 24, background: '#334155' }} />
          <button
            onClick={() => navigate('/risk-calculator')}
            style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 8, color: '#fbbf24', fontSize: 12, fontWeight: 700, padding: '6px 12px', cursor: 'pointer' }}
          >
            🛡 Risk Calc
          </button>
          <button
            onClick={() => navigate('/trade')}
            style={{ background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', borderRadius: 8, color: '#4ade80', fontSize: 12, fontWeight: 700, padding: '6px 12px', cursor: 'pointer' }}
          >
            ⚡ Trade
          </button>
        </div>
      </div>

      {/* ── History Tab ── */}
      {activeTab === 'history' && (
        <div style={s.progressCard}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px' }}>Challenge History</h3>
          {historyQ.isLoading && <div style={s.loading}>Loading…</div>}
          {!historyQ.isLoading && (historyQ.data ?? []).length === 0 && (
            <div style={{ textAlign: 'center', padding: 32, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 32 }}>🏆</div>
              <div style={{ color: '#94a3b8', fontSize: 14, fontWeight: 600 }}>No challenge history yet</div>
              <div style={{ color: '#64748b', fontSize: 12 }}>Complete a challenge phase to see your history here.</div>
              <button onClick={() => navigate('/trade')}
                style={{ padding: '6px 16px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.4)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer', marginTop: 4 }}>
                ⚡ Start Trading
              </button>
            </div>
          )}
          {(historyQ.data ?? []).map(ch => (
            <div key={ch.challenge_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #1e293b' }}>
              <div>
                <div style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 14 }}>Phase {ch.phase} — ${ch.account_size.toLocaleString()}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{new Date(ch.started_at).toLocaleDateString()} {ch.ended_at ? `→ ${new Date(ch.ended_at).toLocaleDateString()}` : '(active)'}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: ch.result === 'passed' ? '#4ade80' : ch.result === 'failed' ? '#f87171' : '#f59e0b' }}>
                  {ch.result.toUpperCase()}
                </div>
                <div style={{ fontSize: 12, color: '#64748b' }}>P&L: {ch.profit_pct >= 0 ? '+' : ''}{ch.profit_pct.toFixed(2)}% · DD: {ch.max_drawdown_pct.toFixed(2)}%</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Alerts Tab ── */}
      {activeTab === 'alerts' && (
        <div style={s.progressCard}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px' }}>Breach Alerts</h3>
          {alertsQ.isLoading && <div style={s.loading}>Loading…</div>}
          {!alertsQ.isLoading && (alertsQ.data ?? []).length === 0 && (
            <div style={{ color: '#4ade80', textAlign: 'center', padding: 32 }}>✅ No breach alerts. All limits within bounds.</div>
          )}
          {(alertsQ.data ?? []).map(alert => (
            <div key={alert.alert_id} style={{ background: alert.severity === 'critical' ? '#450a0a' : '#431407', border: `1px solid ${alert.severity === 'critical' ? '#7f1d1d' : '#92400e'}`, borderRadius: 8, padding: '12px 16px', marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: alert.severity === 'critical' ? '#f87171' : '#fbbf24', marginBottom: 4 }}>
                  {alert.severity === 'critical' ? '🚨' : '⚠️'} {alert.alert_type}
                </div>
                <div style={{ fontSize: 13, color: '#94a3b8' }}>{alert.message}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{new Date(alert.created_at).toLocaleString()}</div>
              </div>
              {!alert.acknowledged && (
                <button onClick={() => handleAcknowledge(alert.alert_id)} disabled={ackingId === alert.alert_id}
                  style={{ background: '#334155', border: 'none', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '4px 10px', flexShrink: 0, marginLeft: 12 }}>
                  {ackingId === alert.alert_id ? '…' : 'Acknowledge'}
                </button>
              )}
              {alert.acknowledged && <span style={{ fontSize: 11, color: '#4ade80', flexShrink: 0, marginLeft: 12 }}>✓ Ack</span>}
            </div>
          ))}
        </div>
      )}

      {/* ── Daily Stats Tab ── */}
      {activeTab === 'daily' && (
        <div style={s.progressCard}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px' }}>Daily P&L Stats</h3>
          {dailyQ.isLoading && <div style={s.loading}>Loading…</div>}
          {!dailyQ.isLoading && (dailyQ.data ?? []).length === 0 && (
            <div style={{ textAlign: 'center', padding: 32, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 32 }}>📈</div>
              <div style={{ color: '#94a3b8', fontSize: 14, fontWeight: 600 }}>No daily stats yet</div>
              <div style={{ color: '#64748b', fontSize: 12 }}>Trade to start building your daily P&amp;L record.</div>
              <button onClick={() => navigate('/trade')}
                style={{ padding: '6px 16px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.4)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer', marginTop: 4 }}>
                ⚡ Start Trading
              </button>
            </div>
          )}
          {(dailyQ.data ?? []).length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={dailyQ.data} margin={{ top: 4, right: 8, left: 0, bottom: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip contentStyle={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 6, fontSize: 11 }}
                  formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, 'P&L']} />
                <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                  {(dailyQ.data ?? []).map((d, i) => (
                    <Cell key={i} fill={d.pnl >= 0 ? '#4ade80' : '#f87171'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          {(dailyQ.data ?? []).map(d => (
            <div key={d.date} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: 13 }}>
              <span style={{ color: '#94a3b8' }}>{d.date}</span>
              <span style={{ color: d.pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>{d.pnl >= 0 ? '+' : ''}${d.pnl.toFixed(2)}</span>
              <span style={{ color: '#64748b' }}>{d.trades} trades</span>
              <span style={{ color: '#f87171' }}>DD: {d.drawdown_pct.toFixed(2)}%</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Live Tab ── */}
      {activeTab === 'live' && (
      <>
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
