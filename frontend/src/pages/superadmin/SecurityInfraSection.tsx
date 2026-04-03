// superadmin/SecurityInfraSection.tsx
// SelfHealer integrity monitor, Antivirus scanner, HSM Vault key management
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, ActionBtn, KpiTile, ErrorState, LoadingRows,
  ConfirmDialog, SAStyles,
} from './ui';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

interface SelfHealerStatus {
  status: string;
  tracked_files: number;
  last_scan: string | null;
  violations: { file: string; reason: string; detected_at: string }[];
  patches_applied: number;
  quarantined: string[];
}

interface AVStatus {
  status: string;
  last_scan: string | null;
  threats_found: number;
  files_scanned: number;
  clamav_available: boolean;
  yara_rules_loaded: number;
}

interface HSMStatus {
  hsm_type: string;
  initialized: boolean;
  key_count: number;
  keys: { key_id: string; created_at: string; size_bytes: number; active: boolean }[];
}

interface InfraLogEntry {
  component: string;
  event: string;
  severity: string;
  timestamp: string;
}

const STATUS_COLOR = (s: string) =>
  s === 'running' || s === 'healthy' ? '#4ade80' :
  s === 'unknown' ? '#fbbf24' : '#f87171';

const SecurityInfraSection: React.FC = () => {
  const [healer, setHealer]   = useState<SelfHealerStatus | null>(null);
  const [av, setAv]           = useState<AVStatus | null>(null);
  const [hsm, setHsm]         = useState<HSMStatus | null>(null);
  const [infraLog, setInfraLog] = useState<InfraLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');
  const [busy, setBusy]       = useState<string | null>(null);
  const [msg, setMsg]         = useState('');
  const [rotateConfirm, setRotateConfirm] = useState<string | null>(null);
  const [tab, setTab]         = useState<'healer' | 'av' | 'hsm' | 'log'>('healer');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [hRes, aRes, hsmRes, lRes] = await Promise.all([
        superadminApi.selfHealerStatus(),
        superadminApi.antivirusStatus(),
        superadminApi.hsmStatus(),
        superadminApi.securityInfraLog(),
      ]);
      setHealer(hRes.data);
      setAv(aRes.data);
      setHsm(hsmRes.data);
      setInfraLog(lRes.data.entries ?? []);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load security infrastructure data');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const triggerScan = async (type: 'integrity' | 'av') => {
    setBusy(type); setMsg('');
    try {
      if (type === 'integrity') {
        await superadminApi.triggerIntegrityScan();
        setMsg('File integrity scan started');
      } else {
        await superadminApi.triggerAvScan();
        setMsg('Antivirus scan started');
      }
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Scan trigger failed');
    } finally { setBusy(null); }
  };

  const rotateKey = async (keyId: string) => {
    setBusy(keyId); setMsg('');
    try {
      await superadminApi.hsmRotateKey(keyId);
      setMsg(`Key ${keyId} rotated successfully`);
      await load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Key rotation failed');
    } finally { setBusy(null); setRotateConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  return (
    <>
      <SAStyles />
      {rotateConfirm && (
        <ConfirmDialog
          title="Rotate HSM Key"
          message={`Rotate key "${rotateConfirm}"? All services using this key will need to re-fetch the new key material.`}
          confirmLabel="Rotate Key"
          danger
          onConfirm={() => rotateKey(rotateConfirm)}
          onCancel={() => setRotateConfirm(null)}
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
        <KpiTile label="Self-Healer" value={healer?.status ?? 'unknown'} icon="🔧" accent={STATUS_COLOR(healer?.status ?? '')} />
        <KpiTile label="Tracked Files" value={healer?.tracked_files ?? 0} icon="📁" accent="#60a5fa" />
        <KpiTile label="AV Threats" value={av?.threats_found ?? 0} icon="🦠" accent={av?.threats_found ? '#f87171' : '#22c55e'} />
        <KpiTile label="HSM Keys" value={hsm?.key_count ?? 0} icon="🔑" accent="#a78bfa" />
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {(['healer', 'av', 'hsm', 'log'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b',
            padding: '7px 14px', fontSize: 13, cursor: 'pointer',
          }}>
            {{ healer: 'Self-Healer', av: 'Antivirus', hsm: 'HSM Vault', log: 'Infra Log' }[t]}
          </button>
        ))}
      </div>

      {tab === 'healer' && healer && (
        <>
          <SectionCard title="File Integrity Monitor" icon="🔧" accent="#22c55e"
            subtitle="SHA-256 hash-chain integrity monitoring with auto-patch and rollback"
            actions={
              <ActionBtn label="Run Scan Now" onClick={() => triggerScan('integrity')} loading={busy === 'integrity'} accent="#22c55e" size="sm" />
            }>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
              {[
                { label: 'Status',          value: healer.status,                    color: STATUS_COLOR(healer.status) },
                { label: 'Tracked Files',   value: healer.tracked_files,             color: '#60a5fa' },
                { label: 'Last Scan',       value: fmtDate(healer.last_scan),        color: '#94a3b8' },
                { label: 'Patches Applied', value: healer.patches_applied,           color: '#a78bfa' },
                { label: 'Quarantined',     value: healer.quarantined?.length ?? 0,  color: healer.quarantined?.length ? '#f87171' : '#22c55e' },
                { label: 'Violations',      value: healer.violations?.length ?? 0,   color: healer.violations?.length ? '#f87171' : '#22c55e' },
              ].map(item => (
                <div key={item.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px' }}>
                  <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: item.color, marginTop: 4 }}>{String(item.value)}</div>
                </div>
              ))}
            </div>
            {healer.violations?.length > 0 && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#f87171', marginBottom: 8 }}>⚠️ Integrity Violations</div>
                {healer.violations.map((v, i) => (
                  <div key={i} style={{ background: 'rgba(248,113,113,0.05)', border: '1px solid #7f1d1d', borderRadius: 6, padding: '8px 12px', marginBottom: 6 }}>
                    <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#f87171' }}>{v.file}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{v.reason} · {fmtDate(v.detected_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </>
      )}

      {tab === 'av' && av && (
        <SectionCard title="Antivirus Scanner" icon="🦠" accent="#f97316"
          subtitle="YARA rules + ClamAV + entropy analysis + suspicious pattern detection"
          actions={
            <ActionBtn label="Run Full Scan" onClick={() => triggerScan('av')} loading={busy === 'av'} accent="#f97316" size="sm" />
          }>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {[
              { label: 'Status',          value: av.status,                                    color: STATUS_COLOR(av.status) },
              { label: 'Last Scan',       value: fmtDate(av.last_scan),                        color: '#94a3b8' },
              { label: 'Files Scanned',   value: av.files_scanned.toLocaleString(),            color: '#60a5fa' },
              { label: 'Threats Found',   value: av.threats_found,                             color: av.threats_found ? '#f87171' : '#22c55e' },
              { label: 'ClamAV',          value: av.clamav_available ? 'Available' : 'N/A',   color: av.clamav_available ? '#22c55e' : '#64748b' },
              { label: 'YARA Rules',      value: av.yara_rules_loaded,                         color: '#a78bfa' },
            ].map(item => (
              <div key={item.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px' }}>
                <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: item.color, marginTop: 4 }}>{String(item.value)}</div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {tab === 'hsm' && hsm && (
        <SectionCard title="HSM Vault — Key Management" icon="🔑" accent="#a78bfa"
          subtitle={`${hsm.hsm_type.toUpperCase()} HSM · ${hsm.initialized ? 'Initialized' : 'Not initialized'}`}>
          {hsm.keys.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No keys in vault</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Key ID', 'Created', 'Size', 'Active', 'Actions'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: '#64748b', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hsm.keys.map(k => (
                  <tr key={k.key_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 12, color: '#a78bfa' }}>{k.key_id}</td>
                    <td style={{ padding: '10px 16px', color: '#64748b', fontSize: 12 }}>{fmtDate(k.created_at)}</td>
                    <td style={{ padding: '10px 16px', color: '#94a3b8', fontSize: 12 }}>{k.size_bytes} B</td>
                    <td style={{ padding: '10px 16px' }}>
                      <span style={{ color: k.active ? '#4ade80' : '#f87171', fontSize: 12, fontWeight: 700 }}>
                        {k.active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      <ActionBtn
                        label="Rotate"
                        onClick={() => setRotateConfirm(k.key_id)}
                        loading={busy === k.key_id}
                        accent="#fbbf24"
                        size="sm"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </SectionCard>
      )}

      {tab === 'log' && (
        <SectionCard title="Security Infrastructure Log" icon="📋" accent="#64748b">
          {infraLog.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No log entries</div>
          ) : (
            infraLog.slice(0, 100).map((entry, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid #0f172a', alignItems: 'flex-start' }}>
                <div style={{
                  width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
                  background: entry.severity === 'critical' ? '#f87171' : entry.severity === 'warning' ? '#fbbf24' : '#4ade80',
                }} />
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8' }}>[{entry.component}]</span>
                  {' '}
                  <span style={{ fontSize: 12, color: '#cbd5e1' }}>{entry.event}</span>
                </div>
                <div style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{fmtDate(entry.timestamp)}</div>
              </div>
            ))
          )}
        </SectionCard>
      )}
    </>
  );
};

export default SecurityInfraSection;
