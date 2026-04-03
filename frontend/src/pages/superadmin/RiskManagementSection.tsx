// superadmin/RiskManagementSection.tsx
// Circuit breakers, VaR/ES, stress tests, drawdown, prop firm enforcement
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, StatusBadge, ActionBtn, KpiTile,
  ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { CircuitBreakerState, VaRMetrics, StressTestResult } from './types';

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

const RiskManagementSection: React.FC = () => {
  const [breakers, setBreakers]   = useState<CircuitBreakerState[]>([]);
  const [varMetrics, setVarMetrics] = useState<VaRMetrics | null>(null);
  const [stressTests, setStressTests] = useState<StressTestResult[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [busy, setBusy]           = useState<string | null>(null);
  const [msg, setMsg]             = useState('');
  const [confirm, setConfirm]     = useState<{ name: string; action: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [cbRes, varRes, stRes] = await Promise.all([
        superadminApi.circuitBreakers(),
        superadminApi.varMetrics(),
        superadminApi.stressTestResults(),
      ]);
      setBreakers(cbRes.data.breakers ?? cbRes.data);
      setVarMetrics(varRes.data);
      setStressTests(stRes.data.results ?? stRes.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load risk data');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const resetBreaker = async (name: string) => {
    setBusy(`reset-${name}`); setMsg('');
    try {
      await superadminApi.resetCircuitBreaker(name);
      setMsg(`Circuit breaker "${name}" reset to CLOSED`);
      load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Reset failed');
    } finally { setBusy(null); setConfirm(null); }
  };

  const runStressTest = async (scenario: string) => {
    setBusy(`stress-${scenario}`); setMsg('');
    try {
      await superadminApi.runStressTest(scenario);
      setMsg(`Stress test "${scenario}" queued — results will appear shortly`);
      setTimeout(load, 3000);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Stress test failed');
    } finally { setBusy(null); }
  };

  const openBreakers = breakers.filter(b => b.state === 'open').length;

  if (loading) return <><SAStyles /><LoadingRows rows={8} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {confirm && (
        <ConfirmDialog
          title={`Reset Circuit Breaker: ${confirm.name}`}
          message="This will force the circuit breaker back to CLOSED state, allowing traffic through. Only do this after confirming the underlying issue is resolved."
          confirmLabel="Reset to Closed"
          variant="warning"
          onConfirm={() => resetBreaker(confirm.name)}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* VaR KPIs */}
      {varMetrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
          <KpiTile label="VaR 95%"          value={fmtMoney(varMetrics.var_95, varMetrics.currency)}           icon="📉" accent="#ef4444" />
          <KpiTile label="VaR 99%"          value={fmtMoney(varMetrics.var_99, varMetrics.currency)}           icon="📉" accent="#dc2626" />
          <KpiTile label="Expected Shortfall" value={fmtMoney(varMetrics.expected_shortfall, varMetrics.currency)} icon="⚠️" accent="#f59e0b" />
          <KpiTile label="Max Drawdown"     value={fmtPct(varMetrics.max_drawdown)}                            icon="📊" accent="#f87171" />
          <KpiTile label="Current Drawdown" value={fmtPct(varMetrics.current_drawdown)}                        icon="📊" accent={varMetrics.current_drawdown > 5 ? '#ef4444' : '#22c55e'} />
          <KpiTile label="Sharpe Ratio"     value={varMetrics.sharpe_ratio.toFixed(2)}                         icon="⭐" accent="#3b82f6" />
          <KpiTile label="Sortino Ratio"    value={varMetrics.sortino_ratio.toFixed(2)}                        icon="⭐" accent="#8b5cf6" />
          <KpiTile label="Portfolio Value"  value={fmtMoney(varMetrics.portfolio_value, varMetrics.currency)}  icon="💼" accent="#22c55e" />
        </div>
      )}

      {/* Circuit Breakers */}
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
                    { label: 'Failures',      value: b.failure_count },
                    { label: 'Threshold',     value: b.threshold },
                    { label: 'Last Failure',  value: fmtDate(b.last_failure) },
                    { label: 'Last Success',  value: fmtDate(b.last_success) },
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
              </div>
            );
          })}
          {breakers.length === 0 && <div style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>No circuit breakers registered.</div>}
        </div>
      </SectionCard>

      {/* Stress Tests */}
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
                    <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{t.scenario}</td>
                    <td style={{ padding: '10px 12px', fontWeight: 700, color: t.pnl_impact < 0 ? '#f87171' : '#4ade80' }}>{fmtMoney(t.pnl_impact)}</td>
                    <td style={{ padding: '10px 12px', color: t.pnl_pct < 0 ? '#f87171' : '#4ade80' }}>{fmtPct(t.pnl_pct)}</td>
                    <td style={{ padding: '10px 12px', color: '#f87171' }}>{fmtMoney(t.max_loss)}</td>
                    <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{fmtPct(t.probability * 100)}</td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(t.run_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {msg && (
        <div style={{ padding: '12px 16px', borderRadius: 8, marginTop: 4, background: msg.includes('failed') ? '#450a0a' : '#052e16', color: msg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 13, fontWeight: 600 }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default RiskManagementSection;
