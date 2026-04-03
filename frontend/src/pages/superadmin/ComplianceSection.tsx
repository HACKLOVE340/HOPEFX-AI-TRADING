// superadmin/ComplianceSection.tsx
// KYC queue, AML alerts, sanctions screening, regulatory reporting
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, StatusBadge, SeverityBadge, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { KYCRecord, AMLAlert, SanctionsHit } from './types';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const KYC_STATUS_COLORS: Record<string, { color: string; bg: string }> = {
  unverified:   { color: '#64748b', bg: '#1e293b' },
  pending:      { color: '#fbbf24', bg: '#78350f' },
  submitted:    { color: '#60a5fa', bg: '#1e3a5f' },
  under_review: { color: '#c084fc', bg: '#2e1065' },
  approved:     { color: '#4ade80', bg: '#052e16' },
  rejected:     { color: '#f87171', bg: '#450a0a' },
};

const ComplianceSection: React.FC = () => {
  const [kyc, setKyc]           = useState<KYCRecord[]>([]);
  const [aml, setAml]           = useState<AMLAlert[]>([]);
  const [sanctions, setSanctions] = useState<SanctionsHit[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [kycFilter, setKycFilter] = useState('pending');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [confirm, setConfirm]   = useState<{ id: string; action: string; label: string } | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [kycRes, amlRes, sanRes] = await Promise.all([
        superadminApi.kycQueue({ status: kycFilter }),
        superadminApi.amlAlerts(),
        superadminApi.sanctionsHits(),
      ]);
      setKyc(kycRes.data.records ?? kycRes.data);
      setAml(amlRes.data.alerts ?? amlRes.data);
      setSanctions(sanRes.data.hits ?? sanRes.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load compliance data');
    } finally { setLoading(false); }
  }, [kycFilter]);

  useEffect(() => { load(); }, [load]);

  const kycAction = async (userId: string, action: 'approve' | 'reject', reason?: string) => {
    setBusy(`${action}-${userId}`); setMsg('');
    try {
      if (action === 'approve') await superadminApi.approveKYC(userId);
      else                      await superadminApi.rejectKYC(userId, reason ?? 'Does not meet requirements');
      setMsg(`KYC ${action}d for user ${userId}`);
      setConfirm(null); setRejectReason('');
      load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `KYC ${action} failed`);
    } finally { setBusy(null); }
  };

  const amlAction = async (alertId: string, status: string) => {
    setBusy(`aml-${alertId}`); setMsg('');
    try {
      await superadminApi.updateAMLAlert(alertId, status);
      setMsg(`AML alert ${alertId} marked as ${status}`);
      load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'AML update failed');
    } finally { setBusy(null); }
  };

  const sanctionAction = async (hitId: string, status: 'cleared' | 'confirmed') => {
    setBusy(`sanction-${hitId}`); setMsg('');
    try {
      await superadminApi.updateSanctionsHit(hitId, status);
      setMsg(`Sanctions hit ${hitId} marked as ${status}`);
      load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Sanctions update failed');
    } finally { setBusy(null); }
  };

  const pendingKyc    = kyc.filter(k => ['pending', 'submitted', 'under_review'].includes(k.kyc_status)).length;
  const openAml       = aml.filter(a => a.status === 'open').length;
  const pendingSanc   = sanctions.filter(s => s.status === 'pending').length;

  if (loading) return <><SAStyles /><LoadingRows rows={8} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {confirm && (
        <ConfirmDialog
          title={confirm.label}
          message={`This action is permanent and logged. ${confirm.action === 'reject' ? `Rejection reason: "${rejectReason || 'not specified'}"` : ''}`}
          confirmLabel={confirm.label}
          variant={confirm.action === 'reject' ? 'danger' : 'warning'}
          onConfirm={() => kycAction(confirm.id, confirm.action as 'approve' | 'reject', rejectReason)}
          onCancel={() => { setConfirm(null); setRejectReason(''); }}
        />
      )}

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="KYC Pending"      value={pendingKyc}  icon="📋" accent="#f59e0b" />
        <KpiTile label="AML Open Alerts"  value={openAml}     icon="🚨" accent="#ef4444" />
        <KpiTile label="Sanctions Hits"   value={pendingSanc} icon="⚠️" accent="#dc2626" />
        <KpiTile label="Total KYC"        value={kyc.length}  icon="🪪" accent="#3b82f6" />
      </div>

      {/* KYC Queue */}
      <SectionCard title="KYC Review Queue" icon="🪪" accent="#f59e0b"
        subtitle="Identity verification — dual-approval workflow"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Select value={kycFilter} onChange={e => setKycFilter(e.target.value)}
              options={[
                { value: '', label: 'All' }, { value: 'pending', label: 'Pending' },
                { value: 'submitted', label: 'Submitted' }, { value: 'under_review', label: 'Under Review' },
                { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' },
              ]} style={{ width: 150 }} />
            <ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />
          </div>
        }>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User', 'Status', 'Document', 'Country', 'Submitted', 'Reviewed', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {kyc.map(k => {
                const sc = KYC_STATUS_COLORS[k.kyc_status] ?? KYC_STATUS_COLORS.unverified;
                return (
                  <tr key={k.user_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{k.username}</div>
                      <div style={{ fontSize: 11, color: '#475569' }}>{k.email}</div>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: sc.color, background: sc.bg, border: `1px solid ${sc.color}33`, borderRadius: 4, padding: '2px 7px' }}>
                        {k.kyc_status.replace('_', ' ').toUpperCase()}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{k.document_type ?? '—'}</td>
                    <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{k.country ?? '—'}</td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(k.submitted_at)}</td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(k.reviewed_at)}</td>
                    <td style={{ padding: '10px 12px' }}>
                      {['pending', 'submitted', 'under_review'].includes(k.kyc_status) && (
                        <div style={{ display: 'flex', gap: 6 }}>
                          <ActionBtn label="Approve" onClick={() => setConfirm({ id: k.user_id, action: 'approve', label: `Approve KYC for ${k.username}` })} variant="success" size="sm" loading={busy === `approve-${k.user_id}`} />
                          <ActionBtn label="Reject"  onClick={() => setConfirm({ id: k.user_id, action: 'reject',  label: `Reject KYC for ${k.username}`  })} variant="danger"  size="sm" loading={busy === `reject-${k.user_id}`} />
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {kyc.length === 0 && <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No KYC records match the current filter.</div>}
        </div>
        {confirm?.action === 'reject' && (
          <div style={{ marginTop: 12 }}>
            <Input label="Rejection Reason" value={rejectReason} onChange={e => setRejectReason(e.target.value)} placeholder="Reason for rejection…" />
          </div>
        )}
      </SectionCard>

      {/* AML Alerts */}
      <SectionCard title="AML Alerts" icon="🚨" accent="#ef4444"
        subtitle="Anti-money laundering transaction monitoring">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User', 'Type', 'Severity', 'Amount', 'Description', 'Status', 'Date', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {aml.map(a => (
                <tr key={a.alert_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{a.username}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{a.alert_type}</td>
                  <td style={{ padding: '10px 12px' }}><SeverityBadge severity={a.severity} /></td>
                  <td style={{ padding: '10px 12px', fontWeight: 700, color: '#f87171' }}>{a.amount.toLocaleString()} {a.currency}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.description}</td>
                  <td style={{ padding: '10px 12px' }}><StatusBadge status={a.status} size="sm" /></td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(a.created_at)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    {a.status === 'open' && (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <ActionBtn label="Investigate" onClick={() => amlAction(a.alert_id, 'investigating')} variant="warning" size="sm" loading={busy === `aml-${a.alert_id}`} />
                        <ActionBtn label="Clear"       onClick={() => amlAction(a.alert_id, 'cleared')}       variant="success" size="sm" loading={busy === `aml-${a.alert_id}`} />
                      </div>
                    )}
                    {a.status === 'investigating' && (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <ActionBtn label="Clear"  onClick={() => amlAction(a.alert_id, 'cleared')}  variant="success" size="sm" loading={busy === `aml-${a.alert_id}`} />
                        <ActionBtn label="Report" onClick={() => amlAction(a.alert_id, 'reported')} variant="danger"  size="sm" loading={busy === `aml-${a.alert_id}`} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {aml.length === 0 && <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No AML alerts.</div>}
        </div>
      </SectionCard>

      {/* Sanctions */}
      <SectionCard title="Sanctions Screening" icon="🌐" accent="#dc2626"
        subtitle="OFAC / UN / EU sanctions list matches">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User', 'List', 'Match Score', 'Status', 'Date', 'Actions'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sanctions.map(s => (
                <tr key={s.hit_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{s.username}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{s.list_name}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ flex: 1, height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden', minWidth: 80 }}>
                        <div style={{ height: '100%', width: `${s.match_score * 100}%`, background: s.match_score > 0.8 ? '#ef4444' : s.match_score > 0.6 ? '#f59e0b' : '#22c55e', borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 700, color: s.match_score > 0.8 ? '#f87171' : '#fbbf24' }}>{(s.match_score * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px' }}><StatusBadge status={s.status} size="sm" /></td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(s.created_at)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    {s.status === 'pending' && (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <ActionBtn label="Clear"   onClick={() => sanctionAction(s.hit_id, 'cleared')}   variant="success" size="sm" loading={busy === `sanction-${s.hit_id}`} />
                        <ActionBtn label="Confirm" onClick={() => sanctionAction(s.hit_id, 'confirmed')} variant="danger"  size="sm" loading={busy === `sanction-${s.hit_id}`} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sanctions.length === 0 && <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No sanctions hits.</div>}
        </div>
      </SectionCard>

      {/* Regulatory Reporting */}
      <SectionCard title="Regulatory Reporting" icon="📜" accent="#8b5cf6"
        subtitle="CFTC / MiFID II / CAT filing status">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            { label: 'CFTC Report',    endpoint: 'cftc',   color: '#3b82f6' },
            { label: 'MiFID II',       endpoint: 'mifid2', color: '#8b5cf6' },
            { label: 'CAT Filing',     endpoint: 'cat',    color: '#06b6d4' },
            { label: 'Trade Report',   endpoint: 'trades', color: '#22c55e' },
          ].map(r => (
            <ActionBtn
              key={r.endpoint}
              label={`Generate ${r.label}`}
              onClick={() => superadminApi.generateRegulatoryReport(r.endpoint).then(() => setMsg(`${r.label} generation queued`)).catch(() => setMsg('Report generation failed'))}
              variant="primary"
              icon="📄"
            />
          ))}
        </div>
      </SectionCard>

      {msg && (
        <div style={{ padding: '12px 16px', borderRadius: 8, marginTop: 8, background: msg.includes('failed') ? '#450a0a' : '#052e16', color: msg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 13, fontWeight: 600 }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default ComplianceSection;
