// superadmin/FinancialSection.tsx — revenue, subscriptions, payments,
//   chargebacks, tax reports, reconciliation, affiliates
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, Select, Input, StatusBadge,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { RevenueStats, SubscriptionStats, Chargeback, TaxReport, ReconciliationRecord, AffiliateStats } from './types';
import { PLAN_COLORS, PLAN_LABELS } from '../../lib/subscription';
import type { Plan } from '../../lib/subscription';

interface Payment {
  payment_id: string;
  user_id: string;
  username: string;
  amount: number;
  currency: string;
  plan: string;
  status: string;
  provider: string;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtMoney = (n: number, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n);

const fmtMoney2 = (n: number, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const fmtDateShort = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';

function apiErr(e: unknown, fallback: string): string {
  if (e && typeof e === 'object') {
    const r = (e as Record<string, unknown>)['response'] as Record<string, unknown> | undefined;
    const d = r?.['data'] as Record<string, unknown> | undefined;
    if (typeof d?.['detail'] === 'string') return d['detail'];
    if (typeof d?.['message'] === 'string') return d['message'];
  }
  return fallback;
}

// ── Inline Flash ──────────────────────────────────────────────────────────────

const Flash: React.FC<{ msg: string; onClear: () => void }> = ({ msg, onClear }) => {
  const isErr = /fail|error/i.test(msg);
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '11px 16px', borderRadius: 8, marginBottom: 12,
      background: isErr ? '#450a0a' : '#052e16',
      color: isErr ? '#f87171' : '#4ade80',
      fontSize: 13, fontWeight: 600, border: `1px solid ${isErr ? '#dc262633' : '#16a34a33'}`,
    }}>
      <span>{msg}</span>
      <button onClick={onClear} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: 16, marginLeft: 12 }}>×</button>
    </div>
  );
};

// ── Chargeback status colours ─────────────────────────────────────────────────

const CB_COLOR: Record<string, string> = {
  open:              '#fbbf24',
  won:               '#4ade80',
  lost:              '#f87171',
  pending_evidence:  '#60a5fa',
};

// ── Tax-report status colours ─────────────────────────────────────────────────

const TAX_COLOR: Record<string, string> = {
  draft:   '#64748b',
  filed:   '#60a5fa',
  paid:    '#4ade80',
  overdue: '#f87171',
};

// ── Reconciliation status colours ─────────────────────────────────────────────

const RECON_COLOR: Record<string, string> = {
  matched:     '#4ade80',
  discrepancy: '#f87171',
  pending:     '#fbbf24',
  resolved:    '#94a3b8',
};

// ─────────────────────────────────────────────────────────────────────────────
// Sub-panels
// ─────────────────────────────────────────────────────────────────────────────

// ── Chargebacks panel ─────────────────────────────────────────────────────────

const ChargebacksPanel: React.FC = () => {
  const [items, setItems]   = useState<Chargeback[]>([]);
  const [loading, setLoad]  = useState(true);
  const [error, setError]   = useState('');
  const [msg, setMsg]       = useState('');
  const [statusFilter, setSF] = useState('all');
  const [busy, setBusy]     = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoad(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (statusFilter !== 'all') params['status'] = statusFilter;
      const res = await superadminApi.chargebacks(params);
      setItems(res.data.chargebacks ?? res.data ?? []);
    } catch (e) { setError(apiErr(e, 'Failed to load chargebacks')); }
    finally { setLoad(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const update = async (id: string, status: string) => {
    setBusy(id);
    try {
      await superadminApi.updateChargeback(id, { status });
      setMsg(`Chargeback ${id.slice(-6)} → ${status}`);
      load();
    } catch (e) { setMsg(apiErr(e, 'Update failed')); }
    finally { setBusy(null); }
  };

  const openCount  = items.filter(c => c.status === 'open').length;
  const totalAtRisk = items.filter(c => ['open','pending_evidence'].includes(c.status))
                          .reduce((s, c) => s + c.amount, 0);

  return (
    <SectionCard
      title="Chargebacks"
      icon="🔄"
      accent="#f97316"
      subtitle={`${items.length} total · ${openCount} open · ${fmtMoney(totalAtRisk)} at risk`}
      actions={
        <Select
          value={statusFilter}
          onChange={e => setSF(e.target.value)}
          options={[
            { value: 'all',              label: 'All' },
            { value: 'open',             label: 'Open' },
            { value: 'pending_evidence', label: 'Pending Evidence' },
            { value: 'won',              label: 'Won' },
            { value: 'lost',             label: 'Lost' },
          ]}
          style={{ width: 170 }}
        />
      }
    >
      {msg && <Flash msg={msg} onClear={() => setMsg('')} />}
      {loading ? <LoadingRows rows={4} /> : error ? <ErrorState message={error} onRetry={load} /> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User','Amount','Provider','Reason','Status','Opened','Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map(c => (
                <tr key={c.chargeback_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{c.username}</td>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: '#fb923c' }}>{fmtMoney2(c.amount, c.currency)}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{c.provider}</td>
                  <td style={{ padding: '10px 12px', color: '#cbd5e1', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.reason}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: CB_COLOR[c.status] ?? '#94a3b8', background: `${CB_COLOR[c.status] ?? '#475569'}22`, borderRadius: 4, padding: '2px 8px' }}>
                      {c.status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDateShort(c.opened_at)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    {c.status === 'open' || c.status === 'pending_evidence' ? (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <ActionBtn label="Won"  onClick={() => update(c.chargeback_id, 'won')}  variant="success" size="sm" loading={busy === c.chargeback_id} />
                        <ActionBtn label="Lost" onClick={() => update(c.chargeback_id, 'lost')} variant="danger"  size="sm" loading={busy === c.chargeback_id} />
                      </div>
                    ) : (
                      <StatusBadge status={c.status === 'won' ? 'resolved' : c.status} size="sm" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div style={{ textAlign: 'center', padding: 28, color: '#475569', fontSize: 13 }}>No chargebacks found.</div>
          )}
        </div>
      )}
    </SectionCard>
  );
};

// ── Tax Reports panel ─────────────────────────────────────────────────────────

const TaxReportsPanel: React.FC = () => {
  const [reports, setReports] = useState<TaxReport[]>([]);
  const [loading, setLoad]    = useState(true);
  const [error, setError]     = useState('');
  const [msg, setMsg]         = useState('');
  const [busy, setBusy]       = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newPeriod, setNewPeriod]  = useState('');
  const [newJurisdiction, setNewJurisdiction] = useState('');

  const load = useCallback(async () => {
    setLoad(true); setError('');
    try {
      const res = await superadminApi.taxReports();
      setReports(res.data.reports ?? res.data ?? []);
    } catch (e) { setError(apiErr(e, 'Failed to load tax reports')); }
    finally { setLoad(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const markStatus = async (id: string, status: string) => {
    setBusy(id);
    try {
      await superadminApi.updateTaxReport(id, { status });
      setMsg(`Report ${id.slice(-6)} → ${status}`);
      load();
    } catch (e) { setMsg(apiErr(e, 'Update failed')); }
    finally { setBusy(null); }
  };

  const create = async () => {
    if (!newPeriod || !newJurisdiction) return;
    setBusy('create');
    try {
      await superadminApi.createTaxReport({ period: newPeriod, jurisdiction: newJurisdiction });
      setMsg('Tax report created');
      setCreating(false); setNewPeriod(''); setNewJurisdiction('');
      load();
    } catch (e) { setMsg(apiErr(e, 'Create failed')); }
    finally { setBusy(null); }
  };

  const overdueCount = reports.filter(r => r.status === 'overdue').length;
  const totalOwed    = reports.filter(r => r.status !== 'paid').reduce((s, r) => s + r.tax_owed, 0);

  return (
    <SectionCard
      title="Tax Reports"
      icon="📑"
      accent="#60a5fa"
      subtitle={`${reports.length} reports · ${overdueCount} overdue · ${fmtMoney(totalOwed)} total owed`}
      actions={
        <ActionBtn label="+ New Report" onClick={() => setCreating(v => !v)} variant="primary" size="sm" />
      }
    >
      {msg && <Flash msg={msg} onClear={() => setMsg('')} />}
      {creating && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginBottom: 16, padding: '14px 16px', background: '#0f1f35', borderRadius: 8, border: '1px solid #1e3a5f' }}>
          <Input label="Period (e.g. 2025-Q1)" value={newPeriod} onChange={e => setNewPeriod(e.target.value)} placeholder="2025-Q1" />
          <Input label="Jurisdiction" value={newJurisdiction} onChange={e => setNewJurisdiction(e.target.value)} placeholder="US-Federal" />
          <ActionBtn label="Create" onClick={create} variant="primary" loading={busy === 'create'} />
          <ActionBtn label="Cancel" onClick={() => setCreating(false)} variant="ghost" />
        </div>
      )}
      {loading ? <LoadingRows rows={4} /> : error ? <ErrorState message={error} onRetry={load} /> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Period','Jurisdiction','Revenue','Taxable','Rate','Tax Owed','Due Date','Status','Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reports.map(r => (
                <tr key={r.report_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{r.period}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{r.jurisdiction}</td>
                  <td style={{ padding: '10px 12px', color: '#e2e8f0' }}>{fmtMoney(r.total_revenue, r.currency)}</td>
                  <td style={{ padding: '10px 12px', color: '#e2e8f0' }}>{fmtMoney(r.taxable_amount, r.currency)}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{r.tax_rate_pct.toFixed(1)}%</td>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: r.status === 'overdue' ? '#f87171' : '#fbbf24' }}>{fmtMoney(r.tax_owed, r.currency)}</td>
                  <td style={{ padding: '10px 12px', color: r.status === 'overdue' ? '#f87171' : '#64748b', fontSize: 12 }}>{fmtDateShort(r.due_date)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: TAX_COLOR[r.status] ?? '#94a3b8', background: `${TAX_COLOR[r.status] ?? '#475569'}22`, borderRadius: 4, padding: '2px 8px' }}>
                      {r.status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 5 }}>
                      {r.status === 'draft' && (
                        <ActionBtn label="File"  onClick={() => markStatus(r.report_id, 'filed')} variant="primary"  size="sm" loading={busy === r.report_id} />
                      )}
                      {r.status === 'filed' && (
                        <ActionBtn label="Mark Paid" onClick={() => markStatus(r.report_id, 'paid')} variant="success" size="sm" loading={busy === r.report_id} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {reports.length === 0 && (
            <div style={{ textAlign: 'center', padding: 28, color: '#475569', fontSize: 13 }}>No tax reports yet.</div>
          )}
        </div>
      )}
    </SectionCard>
  );
};

// ── Reconciliation panel ──────────────────────────────────────────────────────

const ReconciliationPanel: React.FC = () => {
  const [records, setRecords] = useState<ReconciliationRecord[]>([]);
  const [loading, setLoad]    = useState(true);
  const [error, setError]     = useState('');
  const [msg, setMsg]         = useState('');
  const [busy, setBusy]       = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [provider, setProvider] = useState('all');
  const [notes, setNotes]     = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoad(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (provider !== 'all') params['provider'] = provider;
      const res = await superadminApi.reconciliationRecords(params);
      setRecords(res.data.records ?? res.data ?? []);
    } catch (e) { setError(apiErr(e, 'Failed to load reconciliation records')); }
    finally { setLoad(false); }
  }, [provider]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const runRecon = async () => {
    setRunBusy(true);
    try {
      await superadminApi.runReconciliation({ provider: provider !== 'all' ? provider : undefined });
      setMsg('Reconciliation run started — results will appear shortly');
      setTimeout(load, 3000);
    } catch (e) { setMsg(apiErr(e, 'Reconciliation run failed')); }
    finally { setRunBusy(false); }
  };

  const resolve = async (id: string) => {
    setBusy(id);
    try {
      await superadminApi.resolveReconciliation(id, notes[id]);
      setMsg(`Record ${id.slice(-6)} resolved`);
      load();
    } catch (e) { setMsg(apiErr(e, 'Resolve failed')); }
    finally { setBusy(null); }
  };

  const discrepancies = records.filter(r => r.status === 'discrepancy');
  const totalDiscrepancy = discrepancies.reduce((s, r) => s + Math.abs(r.discrepancy), 0);
  const providers = [...new Set(records.map(r => r.provider))];

  return (
    <SectionCard
      title="Payment Reconciliation"
      icon="⚖️"
      accent="#a78bfa"
      subtitle={`${records.length} records · ${discrepancies.length} discrepancies · ${fmtMoney(totalDiscrepancy)} variance`}
      actions={
        <div style={{ display: 'flex', gap: 8 }}>
          <Select
            value={provider}
            onChange={e => setProvider(e.target.value)}
            options={[{ value: 'all', label: 'All Providers' }, ...providers.map(p => ({ value: p, label: p }))]}
            style={{ width: 160 }}
          />
          <ActionBtn label="Run Reconciliation" onClick={runRecon} variant="primary" size="sm" loading={runBusy} icon="▶" />
        </div>
      }
    >
      {msg && <Flash msg={msg} onClear={() => setMsg('')} />}
      {loading ? <LoadingRows rows={4} /> : error ? <ErrorState message={error} onRetry={load} /> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Period','Provider','Expected','Actual','Discrepancy','Status','Created','Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map(r => (
                <tr key={r.recon_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{r.period}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{r.provider}</td>
                  <td style={{ padding: '10px 12px', color: '#e2e8f0' }}>{fmtMoney(r.expected_amount, r.currency)}</td>
                  <td style={{ padding: '10px 12px', color: '#e2e8f0' }}>{fmtMoney(r.actual_amount, r.currency)}</td>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: r.discrepancy === 0 ? '#4ade80' : r.discrepancy > 0 ? '#4ade80' : '#f87171' }}>
                    {r.discrepancy > 0 ? '+' : ''}{fmtMoney(r.discrepancy, r.currency)}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: RECON_COLOR[r.status] ?? '#94a3b8', background: `${RECON_COLOR[r.status] ?? '#475569'}22`, borderRadius: 4, padding: '2px 8px' }}>
                      {r.status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDateShort(r.created_at)}</td>
                  <td style={{ padding: '10px 12px', minWidth: 220 }}>
                    {r.status === 'discrepancy' && (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input
                          placeholder="Resolution notes…"
                          value={notes[r.recon_id] ?? ''}
                          onChange={e => setNotes(n => ({ ...n, [r.recon_id]: e.target.value }))}
                          style={{ flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', padding: '4px 8px', fontSize: 12 }}
                        />
                        <ActionBtn label="Resolve" onClick={() => resolve(r.recon_id)} variant="success" size="sm" loading={busy === r.recon_id} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {records.length === 0 && (
            <div style={{ textAlign: 'center', padding: 28, color: '#475569', fontSize: 13 }}>No reconciliation records. Click "Run Reconciliation" to generate.</div>
          )}
        </div>
      )}
    </SectionCard>
  );
};

// ── Affiliate panel ───────────────────────────────────────────────────────────

const AffiliatePanel: React.FC = () => {
  const [stats, setStats] = useState<AffiliateStats | null>(null);
  const [loading, setLoad] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoad(true); setError('');
    try {
      const res = await superadminApi.affiliateStats();
      setStats(res.data);
    } catch (e) { setError(apiErr(e, 'Failed to load affiliate data')); }
    finally { setLoad(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  if (loading) return <SectionCard title="Affiliate Programme" icon="🤝" accent="#22c55e"><LoadingRows rows={4} /></SectionCard>;
  if (error)   return <SectionCard title="Affiliate Programme" icon="🤝" accent="#22c55e"><ErrorState message={error} onRetry={load} /></SectionCard>;
  if (!stats)  return null;

  return (
    <SectionCard title="Affiliate Programme" icon="🤝" accent="#22c55e"
      subtitle={`${stats.active_affiliates} active / ${stats.total_affiliates} total affiliates`}>
      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Total Affiliates"    value={stats.total_affiliates}                                           icon="👥" accent="#22c55e" />
        <KpiTile label="Active Affiliates"   value={stats.active_affiliates}                                          icon="✅" accent="#4ade80" />
        <KpiTile label="Commissions Paid"    value={fmtMoney(stats.total_commissions_paid, stats.currency)}           icon="💸" accent="#f59e0b" />
        <KpiTile label="Commissions Pending" value={fmtMoney(stats.commissions_pending, stats.currency)}             icon="⏳" accent="#fbbf24" />
        <KpiTile label="Total Referrals"     value={stats.total_referrals}                                            icon="🔗" accent="#06b6d4" />
        <KpiTile label="Conversions MTD"     value={stats.conversions_mtd}                                            icon="🎯" accent="#8b5cf6" />
      </div>

      {/* Top affiliates */}
      {stats.top_affiliates && stats.top_affiliates.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
            Top Affiliates
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
                  {['#','Username','Referrals','Conversions','Earned','Pending'].map((h, i) => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: i === 0 ? 'center' : 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stats.top_affiliates.map((a, idx) => (
                  <tr key={a.affiliate_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: idx === 0 ? '#fbbf24' : idx === 1 ? '#94a3b8' : '#78350f', fontWeight: 700 }}>
                      {idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : idx + 1}
                    </td>
                    <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{a.username}</td>
                    <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{a.referrals.toLocaleString()}</td>
                    <td style={{ padding: '10px 12px', color: '#4ade80', fontWeight: 600 }}>{a.conversions.toLocaleString()}</td>
                    <td style={{ padding: '10px 12px', fontWeight: 700, color: '#f59e0b' }}>{fmtMoney(a.commission_earned, stats.currency)}</td>
                    <td style={{ padding: '10px 12px', color: '#fbbf24' }}>{fmtMoney(a.commission_pending, stats.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </SectionCard>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Financial tabs
// ─────────────────────────────────────────────────────────────────────────────

type FinTab = 'overview' | 'chargebacks' | 'tax' | 'reconciliation' | 'affiliates';

const FIN_TABS: { id: FinTab; label: string; icon: string }[] = [
  { id: 'overview',       label: 'Overview',        icon: '💰' },
  { id: 'chargebacks',    label: 'Chargebacks',     icon: '🔄' },
  { id: 'tax',            label: 'Tax Reports',     icon: '📑' },
  { id: 'reconciliation', label: 'Reconciliation',  icon: '⚖️' },
  { id: 'affiliates',     label: 'Affiliates',      icon: '🤝' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

const FinancialSection: React.FC = () => {
  const [activeTab, setActiveTab] = useState<FinTab>('overview');
  const [revenue, setRevenue]         = useState<RevenueStats | null>(null);
  const [subStats, setSubStats]       = useState<SubscriptionStats | null>(null);
  const [payments, setPayments]       = useState<Payment[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [period, setPeriod]     = useState('mtd');
  const [refundTarget, setRefundTarget] = useState<Payment | null>(null);
  const [refundReason, setRefundReason] = useState('');
  const [busy, setBusy]         = useState(false);
  const [msg, setMsg]           = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [revRes, payRes, subRes] = await Promise.all([
        superadminApi.revenueStats(period),
        superadminApi.paymentHistory({ period }),
        superadminApi.subscriptionStats(),
      ]);
      setRevenue(revRes.data);
      setPayments(payRes.data.payments ?? payRes.data);
      setSubStats(subRes.data);
    } catch (e) {
      setError(apiErr(e, 'Failed to load financial data'));
    } finally { setLoading(false); }
  }, [period]);

  useEffect(() => { if (activeTab === 'overview') load(); }, [load, activeTab]);

  const doRefund = async () => {
    if (!refundTarget) return;
    setBusy(true); setMsg('');
    try {
      await superadminApi.refundPayment(refundTarget.payment_id, refundReason);
      setMsg(`Refund issued for ${refundTarget.username} — ${fmtMoney(refundTarget.amount, refundTarget.currency)}`);
      setRefundTarget(null); setRefundReason('');
      load();
    } catch (e) { setMsg(apiErr(e, 'Refund failed')); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />

      {/* ── Confirm refund dialog ── */}
      {refundTarget && (
        <ConfirmDialog
          title={`Refund ${fmtMoney(refundTarget.amount, refundTarget.currency)}`}
          message={`Issue a refund to ${refundTarget.username} for payment ${refundTarget.payment_id}. Reason: "${refundReason || 'not specified'}". This action is irreversible.`}
          confirmLabel="Issue Refund"
          variant="danger"
          onConfirm={doRefund}
          onCancel={() => { setRefundTarget(null); setRefundReason(''); }}
        />
      )}

      {/* ── Tab bar ── */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: '#0a1628', border: '1px solid #1e293b', borderRadius: 10, padding: 6, overflowX: 'auto' }}>
        {FIN_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 7, border: 'none',
              background: activeTab === t.id ? '#0f1f35' : 'transparent',
              color: activeTab === t.id ? '#f1f5f9' : '#64748b',
              fontWeight: activeTab === t.id ? 600 : 400,
              fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap',
              outline: activeTab === t.id ? '1px solid #1e3a5f' : 'none',
              transition: 'background 0.12s, color 0.12s',
            }}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      {/* ── Overview tab ── */}
      {activeTab === 'overview' && (
        <>
          {/* Period selector + export */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <Select
              value={period}
              onChange={e => setPeriod(e.target.value)}
              options={[
                { value: 'today', label: 'Today' },
                { value: 'mtd',   label: 'Month to Date' },
                { value: 'ytd',   label: 'Year to Date' },
                { value: '30d',   label: 'Last 30 Days' },
                { value: '90d',   label: 'Last 90 Days' },
              ]}
              style={{ width: 180 }}
            />
            <ActionBtn label="Export CSV" onClick={() => superadminApi.paymentHistory({ period, format: 'csv' })} icon="⬇️" size="sm" />
          </div>

          {msg && <Flash msg={msg} onClear={() => setMsg('')} />}

          {loading ? <LoadingRows rows={8} /> : error ? <ErrorState message={error} onRetry={load} /> : (
            <>
              {/* Revenue KPIs */}
              {revenue && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
                    <KpiTile label="MRR"           value={fmtMoney(revenue.mrr, revenue.currency)}           icon="📈" accent="#22c55e" />
                    <KpiTile label="ARR"           value={fmtMoney(revenue.arr, revenue.currency)}           icon="🏆" accent="#3b82f6" />
                    <KpiTile label="Revenue Today" value={fmtMoney(revenue.revenue_today, revenue.currency)} icon="💰" accent="#f59e0b" />
                    <KpiTile label="Revenue MTD"   value={fmtMoney(revenue.revenue_mtd, revenue.currency)}   icon="📊" accent="#8b5cf6" />
                    <KpiTile label="New Subs MTD"  value={revenue.new_subs_mtd}                              icon="➕" accent="#06b6d4" />
                    <KpiTile label="Cancelled MTD" value={revenue.cancelled_mtd}                             icon="➖" accent="#ef4444" />
                    <KpiTile label="Churn Rate"    value={`${revenue.churn_rate_pct.toFixed(2)}%`}           icon="📉" accent="#f87171" />
                    <KpiTile label="Avg LTV"       value={fmtMoney(revenue.ltv_avg, revenue.currency)}       icon="⭐" accent="#fbbf24" />
                  </div>

                  {/* Subscription KPIs */}
                  {subStats && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
                      <KpiTile label="Active Subscriptions" value={subStats.total_active}    icon="✅" accent="#22c55e" />
                      <KpiTile label="Trials"               value={subStats.trial_count}     icon="🧪" accent="#06b6d4" />
                      <KpiTile label="Expiring Soon"        value={subStats.expiring_soon}   icon="⏳" accent="#f59e0b" />
                      <KpiTile label="Cancelled"            value={subStats.cancelled_count} icon="❌" accent="#ef4444" />
                    </div>
                  )}

                  <SectionCard title="Revenue by Plan" icon="💳" accent="#8b5cf6">
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
                      {Object.entries(revenue.plan_breakdown).map(([plan, amount]) => (
                        <div key={plan} style={{ background: '#1e293b', borderRadius: 8, padding: '14px 16px', borderLeft: `3px solid ${PLAN_COLORS[plan as Plan] ?? '#475569'}` }}>
                          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{PLAN_LABELS[plan as Plan] ?? plan}</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: PLAN_COLORS[plan as Plan] ?? '#94a3b8' }}>{fmtMoney(amount, revenue.currency)}</div>
                        </div>
                      ))}
                    </div>
                  </SectionCard>
                </>
              )}

              {/* Payments table */}
              <SectionCard title="Payment History" icon="🧾" accent="#3b82f6" subtitle={`${payments.length} transactions`}>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #1e293b' }}>
                        {['User','Amount','Plan','Provider','Status','Date',''].map(h => (
                          <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {payments.map(p => (
                        <tr key={p.payment_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                          <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{p.username}</td>
                          <td style={{ padding: '10px 12px', fontWeight: 700, color: '#4ade80' }}>{fmtMoney(p.amount, p.currency)}</td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[p.plan as Plan] ?? '#94a3b8' }}>{PLAN_LABELS[p.plan as Plan] ?? p.plan}</span>
                          </td>
                          <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{p.provider}</td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: p.status === 'completed' ? '#4ade80' : p.status === 'refunded' ? '#f87171' : '#fbbf24' }}>{p.status}</span>
                          </td>
                          <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(p.created_at)}</td>
                          <td style={{ padding: '10px 12px' }}>
                            {p.status === 'completed' && (
                              <>
                                {refundTarget?.payment_id === p.payment_id ? (
                                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                    <input
                                      placeholder="Reason…"
                                      value={refundReason}
                                      onChange={e => setRefundReason(e.target.value)}
                                      style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', padding: '4px 8px', fontSize: 12, width: 120 }}
                                    />
                                    <ActionBtn label="Confirm" onClick={doRefund} variant="danger" size="sm" loading={busy} />
                                    <ActionBtn label="✕" onClick={() => { setRefundTarget(null); setRefundReason(''); }} variant="ghost" size="sm" />
                                  </div>
                                ) : (
                                  <ActionBtn label="Refund" onClick={() => setRefundTarget(p)} variant="danger" size="sm" />
                                )}
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {payments.length === 0 && (
                    <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No payments found for this period.</div>
                  )}
                </div>
              </SectionCard>
            </>
          )}
        </>
      )}

      {activeTab === 'chargebacks'    && <ChargebacksPanel />}
      {activeTab === 'tax'            && <TaxReportsPanel />}
      {activeTab === 'reconciliation' && <ReconciliationPanel />}
      {activeTab === 'affiliates'     && <AffiliatePanel />}
    </div>
  );
};

export default FinancialSection;
