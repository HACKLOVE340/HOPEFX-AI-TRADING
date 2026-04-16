// superadmin/ReportingSection.tsx
// Report list, generate, download, delete — weekly + custom reports
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Select, Input,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { ReportRecord } from './types';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const TYPE_COLORS: Record<string, string> = {
  weekly:     '#60a5fa',
  monthly:    '#a78bfa',
  regulatory: '#fbbf24',
  custom:     '#94a3b8',
};

const ReportingSection: React.FC = () => {
  const [reports, setReports]   = useState<ReportRecord[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [genType, setGenType]   = useState('weekly');
  const [genPeriod, setGenPeriod] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await superadminApi.reportList();
      setReports(res.data.reports ?? res.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load reports');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const generate = async () => {
    setBusy('generate'); setMsg('');
    try {
      const period = genPeriod || new Date().toISOString().slice(0, 10);
      await superadminApi.triggerReport(genType, period);
      setMsg(`${genType} report generation started for period ${period}`);
      setTimeout(load, 2000);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Generate failed');
    } finally { setBusy(null); }
  };

  const download = async (report: ReportRecord) => {
    setBusy(report.report_id); setMsg('');
    try {
      const res = await superadminApi.downloadReport(report.report_id);
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url; a.download = report.report_id; a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Download failed');
    } finally { setBusy(null); }
  };

  const deleteReport = async (reportId: string) => {
    setBusy(reportId); setMsg('');
    try {
      await superadminApi.deleteReport(reportId);
      setReports(prev => prev.filter(r => r.report_id !== reportId));
      setMsg('Report deleted');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Delete failed');
    } finally { setBusy(null); setDeleteConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const completed = reports.filter(r => r.status === 'completed').length;
  const generating = reports.filter(r => r.status === 'generating').length;
  const totalSizeKb = reports.reduce((s, r) => s + (r.size_kb ?? 0), 0);

  return (
    <>
      <SAStyles />
      {deleteConfirm && (
        <ConfirmDialog
          title="Delete Report"
          message="This report file will be permanently deleted."
          confirmLabel="Delete"
          danger
          onConfirm={() => deleteReport(deleteConfirm)}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}

      {msg && (
        <div style={{
          background: msg.includes('fail') || msg.includes('error') ? 'rgba(248,113,113,0.1)' : 'rgba(74,222,128,0.1)',
          border: `1px solid ${msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80'}`,
          borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13,
          color: msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80',
          display: 'flex', justifyContent: 'space-between',
        }}>
          {msg}
          <button onClick={() => setMsg('')} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Total Reports" value={reports.length} icon="📊" accent="#60a5fa" />
        <KpiTile label="Completed" value={completed} icon="✅" accent="#22c55e" />
        <KpiTile label="Generating" value={generating} icon="⏳" accent={generating > 0 ? '#fbbf24' : '#475569'} />
        <KpiTile label="Total Size" value={`${(totalSizeKb / 1024).toFixed(1)} MB`} icon="💾" accent="#a78bfa" />
      </div>

      {/* Generate */}
      <SectionCard title="Generate Report" icon="📈" accent="#60a5fa"
        subtitle="Trigger on-demand report generation">
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ width: 180 }}>
            <Select
              label="Report type"
              value={genType}
              onChange={e => setGenType(e.target.value)}
              options={[
                { value: 'weekly',     label: 'Weekly Performance' },
                { value: 'monthly',    label: 'Monthly Summary' },
                { value: 'regulatory', label: 'Regulatory (CFTC)' },
                { value: 'risk',       label: 'Risk Analytics' },
                { value: 'financial',  label: 'Financial P&L' },
              ]}
            />
          </div>
          <div style={{ width: 180 }}>
            <Input
              label="Period (YYYY-MM-DD or range)"
              placeholder={new Date().toISOString().slice(0, 10)}
              value={genPeriod}
              onChange={e => setGenPeriod(e.target.value)}
            />
          </div>
          <ActionBtn
            label="Generate Report"
            onClick={generate}
            loading={busy === 'generate'}
            accent="#60a5fa"
          />
        </div>
      </SectionCard>

      {/* Report list */}
      <SectionCard title="Generated Reports" icon="📋" accent="#a78bfa" noPad
        actions={
          <ActionBtn label="Refresh" onClick={load} accent="#475569" size="sm" />
        }>
        {reports.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>
            No reports generated yet. Use the form above to generate your first report.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Report', 'Type', 'Status', 'Generated', 'Size', 'Actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reports.map(r => (
                <tr key={r.report_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 16px' }}>
                    <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace', color: '#f8fafc' }}>{r.report_id}</div>
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{r.period}</div>
                  </td>
                  <td style={{ padding: '10px 16px' }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                      background: `${TYPE_COLORS[r.type] ?? '#94a3b8'}22`,
                      color: TYPE_COLORS[r.type] ?? '#94a3b8',
                      border: `1px solid ${TYPE_COLORS[r.type] ?? '#94a3b8'}44`,
                    }}>
                      {r.type.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: '10px 16px' }}><StatusBadge status={r.status} /></td>
                  <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(r.generated_at)}</td>
                  <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>
                    {r.size_kb ? `${r.size_kb.toFixed(1)} KB` : '—'}
                  </td>
                  <td style={{ padding: '10px 16px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {r.status === 'completed' && (
                        <ActionBtn
                          label="Download"
                          onClick={() => download(r)}
                          loading={busy === r.report_id}
                          accent="#22c55e"
                          size="sm"
                        />
                      )}
                      <ActionBtn
                        label="Delete"
                        onClick={() => setDeleteConfirm(r.report_id)}
                        accent="#f87171"
                        size="sm"
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </>
  );
};

export default ReportingSection;
