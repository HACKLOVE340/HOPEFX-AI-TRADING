// superadmin/RiskManagementSection.tsx
// Circuit breakers, VaR/ES, stress tests, prop firm breach tracking, drawdown tracker
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, StatusBadge, ActionBtn, KpiTile,
  ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type {
  CircuitBreakerState, VaRMetrics, StressTestResult,
  PropBreach, DrawdownStats,
} from './types';
import { asArray, extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

const fmtMoney = (n: number, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n);
const fmtPct = (n: number) => `${n.toFixed(2)}%`;
const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const CB_COLORS: Record<string, { color: string; bg: string }> = {
  closed:    { color: '#4ade80', bg: '#052e16' },
  open:      { color: '#f87171', bg: '#450a0a' },
  half_open: { color: '#fbbf24', bg: '#78350f' },
};

const BREACH_SEVERITY_COLORS: Record<string, { color: string; bg: string }> = {
  warning:      { color: '#fbbf24', bg: '#78350f' },
  breach:       { color: '#f87171', bg: '#450a0a' },
  disqualified: { color: '#dc2626', bg: '#7f1d1d' },
};

const BREACH_STATUS_COLORS: Record<string, string> = {
  open:         '#f87171',
  reviewed:     '#fbbf24',
  resolved:     '#4ade80',
  disqualified: '#dc2626',
};

type RiskTab = 'overview' | 'circuit-breakers' | 'stress-tests' | 'prop-breaches' | 'drawdown';

const RiskManagementSection: React.FC = () => {
  const [tab, setTab]             = useState<RiskTab>('overview');
  const [breakers, setBreakers]   = useState<CircuitBreakerState[]>([]);
  const [varMetrics, setVarMetrics] = useState<VaRMetrics | null>(null);
  const [stressTests, setStressTests] = useState<StressTestResult[]>([]);
  const [propBreaches, setPropBreaches] = useState<PropBreach[]>([]);
  const [drawdown, setDrawdown]   = useState<DrawdownStats | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [busy, setBusy]           = useState<string | null>(null);
  const [msg, setMsg]             = useState('');
  const [msgOk, setMsgOk] = useState(true);
  const [confirm, setConfirm]     = useState<{ name: string; action: string } | null>(null);
  const [breachFilter, setBreachFilter] = useState('');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [cbRes, varRes, stRes, pbRes, ddRes] = await Promise.all([
        superadminApi.circuitBreakers(),
        superadminApi.varMetrics(),
        superadminApi.stressTestResults(),
        superadminApi.propBreaches(),
        superadminApi.drawdownStats(),
      ]);
      if (!mountedRef.current) return;
      setBreakers(asArray(cbRes.data.circuit_breakers ?? cbRes.data.breakers ?? cbRes.data));
      setVarMetrics(varRes.data);
      setStressTests(asArray(stRes.data, 'results'));
      setPropBreaches(asArray(pbRes.data, 'breaches'));
      setDrawdown(ddRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load risk data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const resetBreaker = async (name: string) => {
    setBusy(`reset-${name}`); setMsg('');
    try {
      await superadminApi.resetCircuitBreaker(name);
      setMsgOk(true);
      setMsg(`Circuit breaker "${name}" reset to CLOSED`);
      load();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Reset failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const forceOpenBreaker = async (name: string) => {
    setBusy(`open-${name}`); setMsg('');
    try {
      await superadminApi.forceOpenBreaker(name);
      setMsgOk(true);
      setMsg(`Circuit breaker "${name}" force-opened`);
      load();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Force-open failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const runStressTest = async (scenario: string) => {
    setBusy(`stress-${scenario}`); setMsg('');
    try {
      await superadminApi.runStressTest(scenario);
      setMsgOk(true);
      setMsg(`Stress test "${scenario}" queued — results will appear shortly`);
      setTimeout(load, 3000);
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Stress test failed'));
    } finally { setBusy(null); }
  };

  const openBreakers = breakers.filter(b => b.state === 'open').length;

  const filteredBreaches = breachFilter
    ? propBreaches.filter(b => b.status === breachFilter || b.severity === breachFilter || b.breach_type === breachFilter)
    : propBreaches;

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  const TABS: { id: RiskTab; label: string; icon: string }[] = [
    { id: 'overview',        label: 'Overview',       icon: '📊' },
    { id: 'circuit-breakers',label: 'Circuit Breakers',icon: '⚡' },
    { id: 'stress-tests',    label: 'Stress Tests',   icon: '🔬' },
    { id: 'prop-breaches',   label: 'Prop Breaches',  icon: '🛡️' },
    { id: 'drawdown',        label: 'Drawdown',       icon: '📉' },
  ];

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>

      {confirm && (
        <ConfirmDialog
          title={confirm.action === 'open'
            ? `Force-Open Circuit Breaker: ${confirm.name}`
            : `Reset Circuit Breaker: ${confirm.name}`}
          message={confirm.action === 'open'
            ? 'This will force the circuit breaker to OPEN state, blocking all requests to this service. Use for emergency isolation only.'
            : 'This will force the circuit breaker back to CLOSED state. Only do this after confirming the underlying issue is resolved.'}
          confirmLabel={confirm.action === 'open' ? 'Force Open' : 'Reset to Closed'}
          variant={confirm.action === 'open' ? 'danger' : 'warning'}
          onConfirm={() => confirm.action === 'open' ? forceOpenBreaker(confirm.name) : resetBreaker(confirm.name)}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* VaR KPI strip — always visible */}
      {varMetrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
          <KpiTile label="VaR 95%"          value={fmtMoney(varMetrics.var_95, varMetrics.currency)}           icon="📉" accent="#ef4444" />
          <KpiTile label="VaR 99%"          value={fmtMoney(varMetrics.var_99, varMetrics.currency)}           icon="📉" accent="#dc2626" />
          <KpiTile label="Expected Shortfall" value={fmtMoney(varMetrics.expected_shortfall, varMetrics.currency)} icon="⚠️" accent="#f59e0b" />
          <KpiTile label="Max Drawdown"     value={fmtPct(varMetrics.max_drawdown)}                            icon="📊" accent="#f87171" />
          <KpiTile label="Current Drawdown" value={fmtPct(varMetrics.current_drawdown)}                        icon="📊" accent={varMetrics.current_drawdown > 5 ? '#ef4444' : '#22c55e'} />
          <KpiTile label="Sharpe Ratio"     value={varMetrics.sharpe_ratio.toFixed(2)}                         icon="⭐" accent="#3b82f6" />
          <KpiTile label="Open Breakers"    value={openBreakers}                                               icon="⚡" accent={openBreakers > 0 ? '#ef4444' : '#22c55e'} />
          <KpiTile label="Prop Breaches"    value={propBreaches.filter(b => b.status === 'open').length}       icon="🛡️" accent={propBreaches.filter(b => b.status === 'open').length > 0 ? '#f59e0b' : '#22c55e'} />
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: tab === t.id ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t.id ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t.id ? '#f8fafc' : '#64748b',
            padding: '7px 14px', fontSize: 13, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span>{t.icon}</span>{t.label}
          </button>
        ))}
      </div>

      {/* ── Overview ── */}
      {tab === 'overview' && varMetrics && (
        <SectionCard title="Risk Overview" icon="📊" accent="#f97316" subtitle="Platform-wide risk metrics">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {[
              { label: 'Portfolio Value',    value: fmtMoney(varMetrics.portfolio_value, varMetrics.currency), color: '#22c55e' },
              { label: 'VaR 95%',            value: fmtMoney(varMetrics.var_95, varMetrics.currency),          color: '#ef4444' },
              { label: 'VaR 99%',            value: fmtMoney(varMetrics.var_99, varMetrics.currency),          color: '#dc2626' },
              { label: 'Expected Shortfall', value: fmtMoney(varMetrics.expected_shortfall, varMetrics.currency), color: '#f59e0b' },
              { label: 'Max Drawdown',       value: fmtPct(varMetrics.max_drawdown),                           color: '#f87171' },
              { label: 'Current Drawdown',   value: fmtPct(varMetrics.current_drawdown),                       color: varMetrics.current_drawdown > 5 ? '#ef4444' : '#4ade80' },
              { label: 'Sharpe Ratio',       value: varMetrics.sharpe_ratio.toFixed(2),                        color: '#3b82f6' },
              { label: 'Sortino Ratio',      value: varMetrics.sortino_ratio.toFixed(2),                       color: '#8b5cf6' },
              { label: 'Calmar Ratio',       value: varMetrics.calmar_ratio.toFixed(2),                        color: '#06b6d4' },
            ].map(m => (
              <div key={m.label} style={{ background: '#1e293b', borderRadius: 8, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: m.color }}>{m.value}</div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {/* ── Circuit Breakers ── */}
      {tab === 'circuit-breakers' && (
        <SectionCard title="Circuit Breakers" icon="⚡" accent="#ef4444"
          subtitle={`${openBreakers} open · ${breakers.length} total`}
          actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
          {openBreakers > 0 && (
            <div style={{ background: '#450a0a', border: '1px solid #dc2626', borderRadius: 8, padding: '10px 14px', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 16 }}>🛑</span>
              <span style={{ fontSize: 13, color: '#f87171', fontWeight: 600 }}>{openBreakers} circuit breaker{openBreakers > 1 ? 's' : ''} OPEN — affected services are failing fast</span>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {breakers.map(b => {
              const sc = CB_COLORS[b.state] ?? CB_COLORS.closed;
              return (
                <div key={b.name} style={{ background: '#1e293b', borderRadius: 10, padding: '14px 16px', border: `1px solid ${sc.color}33` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>{b.name}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: sc.color, background: sc.bg, border: `1px solid ${sc.color}44`, borderRadius: 4, padding: '2px 8px' }}>
                      {b.state.replace('_', ' ').toUpperCase()}
                    </span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 10 }}>
                    {[
                      { label: 'Failures',     value: b.failure_count },
                      { label: 'Threshold',    value: b.threshold },
                      { label: 'Last Failure', value: fmtDate(b.last_failure) },
                      { label: 'Last Success', value: fmtDate(b.last_success) },
                    ].map(m => (
                      <div key={m.label} style={{ background: '#0f172a', borderRadius: 6, padding: '6px 8px' }}>
                        <div style={{ fontSize: 10, color: '#475569' }}>{m.label}</div>
                        <div style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>{m.value}</div>
                      </div>
                    ))}
                  </div>
                  {b.state !== 'closed' && (
                    <ActionBtn label="Reset to Closed" onClick={() => setConfirm({ name: b.name, action: 'reset' })} variant="warning" size="sm" loading={busy === `reset-${b.name}`} />
                  )}
                  {b.state === 'closed' && (
                    <ActionBtn label="Force Open" onClick={() => setConfirm({ name: b.name, action: 'open' })} variant="danger" size="sm" loading={busy === `open-${b.name}`} />
                  )}
                </div>
              );
            })}
            {breakers.length === 0 && <div style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>No circuit breakers registered.</div>}
          </div>
        </SectionCard>
      )}

      {/* ── Stress Tests ── */}
      {tab === 'stress-tests' && (
        <SectionCard title="Stress Testing" icon="🔬" accent="#8b5cf6"
          subtitle="On-demand scenario analysis — results update in ~3s">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
            {[
              { label: '2008 Financial Crisis', scenario: 'gfc_2008' },
              { label: 'COVID Crash (2020)',     scenario: 'covid_2020' },
              { label: 'Flash Crash',            scenario: 'flash_crash' },
              { label: 'Rate Shock +300bps',     scenario: 'rate_shock_300' },
              { label: 'USD Collapse -20%',      scenario: 'usd_collapse' },
              { label: 'Liquidity Crisis',       scenario: 'liquidity_crisis' },
            ].map(s => (
              <ActionBtn key={s.scenario} label={s.label} onClick={() => runStressTest(s.scenario)} variant="ghost" icon="▶️" size="sm" loading={busy === `stress-${s.scenario}`} />
            ))}
          </div>
          {stressTests.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #1e293b' }}>
                    {['Scenario', 'P&L Impact', 'P&L %', 'Max Loss', 'Probability', 'Run At'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {stressTests.map((t, i) => (
                    <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{t.name ?? t.scenario}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 700, color: (t.pnl_usd ?? t.pnl_impact ?? 0) < 0 ? '#f87171' : '#4ade80' }}>
                        {t.pnl_usd != null ? fmtMoney(t.pnl_usd) : t.pnl_impact != null ? fmtMoney(t.pnl_impact) : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', color: t.pnl_pct < 0 ? '#f87171' : '#4ade80' }}>{fmtPct(t.pnl_pct)}</td>
                      <td style={{ padding: '10px 12px', color: '#f87171' }}>{t.max_loss != null ? fmtMoney(t.max_loss) : '—'}</td>
                      <td style={{ padding: '10px 12px', color: '#94a3b8' }}>
                        {t.probability != null ? fmtPct(t.probability * 100) : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{t.run_at ? fmtDate(t.run_at) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {stressTests.length === 0 && (
            <EmptyState compact icon="🧪" title="No stress test results yet" description="Run a scenario above to simulate portfolio stress conditions." />
          )}
        </SectionCard>
      )}

      {/* ── Prop Firm Breaches ── */}
      {tab === 'prop-breaches' && (
        <SectionCard title="Prop Firm Breach Tracker" icon="🛡️" accent="#f59e0b"
          subtitle={`${propBreaches.filter(b => b.status === 'open').length} open breaches · ${propBreaches.length} total`}
          actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>

          {/* Filter bar */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            {[
              { value: '',             label: 'All' },
              { value: 'open',         label: 'Open' },
              { value: 'reviewed',     label: 'Reviewed' },
              { value: 'resolved',     label: 'Resolved' },
              { value: 'disqualified', label: 'Disqualified' },
              { value: 'breach',       label: 'Severity: Breach' },
              { value: 'warning',      label: 'Severity: Warning' },
            ].map(f => (
              <button key={f.value} onClick={() => setBreachFilter(f.value)} style={{
                background: breachFilter === f.value ? '#1e293b' : 'transparent',
                border: `1px solid ${breachFilter === f.value ? '#475569' : '#1e293b'}`,
                borderRadius: 6, color: breachFilter === f.value ? '#f8fafc' : '#64748b',
                padding: '5px 12px', fontSize: 12, cursor: 'pointer',
              }}>
                {f.label}
              </button>
            ))}
          </div>

          {filteredBreaches.length === 0 ? (
            <EmptyState compact icon="✅" title="No prop firm breaches found" description="Breach events will appear here when traders exceed their risk thresholds." />
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #1e293b' }}>
                    {['User', 'Account', 'Breach Type', 'Threshold', 'Actual', 'Severity', 'Status', 'Detected'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredBreaches.map(b => {
                    const sev = BREACH_SEVERITY_COLORS[b.severity] ?? BREACH_SEVERITY_COLORS.warning;
                    return (
                      <tr key={b.breach_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                        <td style={{ padding: '10px 12px' }}>
                          <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{b.username}</div>
                          <div style={{ fontSize: 11, color: '#475569' }}>{b.user_id}</div>
                        </td>
                        <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }}>{b.account_id}</td>
                        <td style={{ padding: '10px 12px' }}>
                          <span style={{ fontSize: 11, color: '#cbd5e1', background: '#1e293b', borderRadius: 4, padding: '2px 7px' }}>
                            {b.breach_type.replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{b.threshold}%</td>
                        <td style={{ padding: '10px 12px', fontWeight: 700, color: '#f87171' }}>{b.actual_value.toFixed(2)}%</td>
                        <td style={{ padding: '10px 12px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: sev.color, background: sev.bg, border: `1px solid ${sev.color}44`, borderRadius: 4, padding: '2px 8px' }}>
                            {b.severity.toUpperCase()}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: BREACH_STATUS_COLORS[b.status] ?? '#94a3b8' }}>
                            {b.status}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(b.detected_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {/* ── Drawdown Tracker ── */}
      {tab === 'drawdown' && (
        <SectionCard title="Drawdown Tracker" icon="📉" accent="#f97316"
          subtitle="Platform-wide drawdown statistics"
          actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
          {drawdown ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
                <KpiTile label="Current Drawdown"     value={fmtPct(drawdown.current_drawdown_pct)}                                                  icon="📉" accent={drawdown.current_drawdown_pct > 10 ? '#ef4444' : drawdown.current_drawdown_pct > 5 ? '#f59e0b' : '#22c55e'} />
                <KpiTile label="Max Drawdown"         value={fmtPct(drawdown.max_drawdown_pct)}                                                      icon="📊" accent="#f87171" />
                <KpiTile label="Peak Equity"          value={fmtMoney(drawdown.peak_equity)}                                                         icon="🏔️" accent="#22c55e" />
                <KpiTile label="Trough Equity"        value={fmtMoney(drawdown.trough_equity)}                                                       icon="🕳️" accent="#f87171" />
                <KpiTile label="Accounts in Drawdown" value={drawdown.accounts_in_drawdown}                                                          icon="👥" accent="#f59e0b" />
                <KpiTile label="Near Limit"           value={drawdown.accounts_near_limit}                                                           icon="⚠️" accent={drawdown.accounts_near_limit > 0 ? '#ef4444' : '#22c55e'} />
              </div>

              {/* Drawdown distribution */}
              {drawdown.drawdown_distribution && drawdown.drawdown_distribution.length > 0 && (
                <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 12 }}>Drawdown Distribution</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {drawdown.drawdown_distribution.map(d => {
                      const maxCount = Math.max(...drawdown.drawdown_distribution.map(x => x.count), 1);
                      const pct = (d.count / maxCount) * 100;
                      const color = d.bucket.includes('>10') ? '#ef4444' : d.bucket.includes('5-10') ? '#f59e0b' : '#22c55e';
                      return (
                        <div key={d.bucket} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div style={{ width: 80, fontSize: 11, color: '#64748b', flexShrink: 0 }}>{d.bucket}</div>
                          <div style={{ flex: 1, background: '#1e293b', borderRadius: 4, height: 16, overflow: 'hidden' }}>
                            <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s' }} />
                          </div>
                          <div style={{ width: 32, fontSize: 11, color: '#94a3b8', textAlign: 'right', flexShrink: 0 }}>{d.count}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>
              No drawdown data available.
            </div>
          )}
        </SectionCard>
      )}

      <ActionBanner message={msg} ok={msgOk} />
    </div>
  );
};

export default RiskManagementSection;
