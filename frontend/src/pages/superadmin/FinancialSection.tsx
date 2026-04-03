// superadmin/FinancialSection.tsx — revenue, subscriptions, payments, affiliates
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { RevenueStats } from './types';
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

const fmtMoney = (n: number, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(n);

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const FinancialSection: React.FC = () => {
  const [revenue, setRevenue]   = useState<RevenueStats | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
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
      const [revRes, payRes] = await Promise.all([
        superadminApi.revenueStats(period),
        superadminApi.paymentHistory({ period }),
      ]);
      setRevenue(revRes.data);
      setPayments(payRes.data.payments ?? payRes.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load financial data');
    } finally { setLoading(false); }
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const doRefund = async () => {
    if (!refundTarget) return;
    setBusy(true); setMsg('');
    try {
      await superadminApi.refundPayment(refundTarget.payment_id, refundReason);
      setMsg(`Refund issued for ${refundTarget.username} — ${fmtMoney(refundTarget.amount, refundTarget.currency)}`);
      setRefundTarget(null);
      setRefundReason('');
      load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Refund failed');
    } finally { setBusy(false); }
  };

  if (loading) return <><SAStyles /><LoadingRows rows={8} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />

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

      {/* Period selector */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
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
      </div>

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

          {/* Plan breakdown */}
          <SectionCard title="Revenue by Plan" icon="💳" accent="#8b5cf6">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
              {Object.entries(revenue.plan_breakdown).map(([plan, amount]) => (
                <div key={plan} style={{
                  background: '#1e293b', borderRadius: 8, padding: '14px 16px',
                  borderLeft: `3px solid ${PLAN_COLORS[plan as Plan] ?? '#475569'}`,
                }}>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>
                    {PLAN_LABELS[plan as Plan] ?? plan}
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: PLAN_COLORS[plan as Plan] ?? '#94a3b8' }}>
                    {fmtMoney(amount, revenue.currency)}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}

      {/* Payments table */}
      <SectionCard title="Payment History" icon="🧾" accent="#3b82f6"
        subtitle={`${payments.length} transactions`}
        actions={<ActionBtn label="Export CSV" onClick={() => superadminApi.paymentHistory({ period, format: 'csv' })} icon="⬇️" size="sm" />}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User', 'Amount', 'Plan', 'Provider', 'Status', 'Date', ''].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {payments.map(p => (
                <tr key={p.payment_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{p.username}</td>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: '#4ade80' }}>
                    {fmtMoney(p.amount, p.currency)}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[p.plan as Plan] ?? '#94a3b8' }}>
                      {PLAN_LABELS[p.plan as Plan] ?? p.plan}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{p.provider}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700,
                      color: p.status === 'completed' ? '#4ade80' : p.status === 'refunded' ? '#f87171' : '#fbbf24',
                    }}>
                      {p.status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(p.created_at)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    {p.status === 'completed' && (
                      <ActionBtn
                        label="Refund"
                        onClick={() => setRefundTarget(p)}
                        variant="danger" size="sm"
                      />
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

      {/* Refund reason input (shown when refundTarget is set but before confirm) */}
      {refundTarget && (
        <div style={{ marginTop: 12 }}>
          <Input
            label="Refund Reason"
            value={refundReason}
            onChange={e => setRefundReason(e.target.value)}
            placeholder="Reason for refund…"
          />
        </div>
      )}

      {msg && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginTop: 8,
          background: msg.includes('failed') || msg.includes('Failed') ? '#450a0a' : '#052e16',
          color: msg.includes('failed') || msg.includes('Failed') ? '#f87171' : '#4ade80',
          fontSize: 13, fontWeight: 600,
        }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default FinancialSection;
