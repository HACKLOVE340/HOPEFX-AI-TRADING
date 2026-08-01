// superadmin/SecurityInfraSection.tsx
// SelfHealer integrity monitor, Antivirus scanner, HSM Vault key management
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, KpiTile, ErrorState, LoadingRows,
  ConfirmDialog,
} from './ui';
import { extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

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

interface ThreatIndicator {
  type: string;
  value: string;
  severity: string;
  description: string;
  source: string;
  first_seen: string;
  last_seen: string;
  blocked: boolean;
}

const STATUS_COLOR = (s: string) =>
  s === 'running' || s === 'healthy' ? '#4ade80' :
  s === 'unknown' ? '#fbbf24' : '#f87171';

const SecurityInfraSection: React.FC = () => {
  const [healer, setHealer]     = useState<SelfHealerStatus | null>(null);
  const [av, setAv]             = useState<AVStatus | null>(null);
  const [hsm, setHsm]           = useState<HSMStatus | null>(null);
  const [infraLog, setInfraLog] = useState<InfraLogEntry[]>([]);
  const [threatIntel, setThreatIntel]   = useState<ThreatIndicator[]>([]);
  const [threatLoading, setThreatLoading] = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [msgOk, setMsgOk] = useState(true);
  const [rotateConfirm, setRotateConfirm] = useState<string | null>(null);
  const [tab, setTab]           = useState<'healer' | 'av' | 'hsm' | 'log' | 'threat'>('healer');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [hRes, aRes, hsmRes, lRes] = await Promise.all([
        superadminApi.selfHealerStatus(),
        superadminApi.antivirusStatus(),
        superadminApi.hsmStatus(),
        superadminApi.securityInfraLog(),
      ]);
      if (!mountedRef.current) return;
      // Normalise self-healer response — backend may return a subset of fields.
      const hd = hRes.data ?? {};
      setHealer({
        status:          hd.status          ?? 'unknown',
        tracked_files:   hd.tracked_files   ?? hd.files_tracked   ?? 0,
        last_scan:       hd.last_scan       ?? hd.last_run        ?? null,
        patches_applied: hd.patches_applied ?? hd.heals_today     ?? 0,
        quarantined:     Array.isArray(hd.quarantined) ? hd.quarantined : [],
        violations:      Array.isArray(hd.violations)  ? hd.violations  :
                         Array.isArray(hd.heal_log)    ? hd.heal_log.map((e: string) => ({ file: e, reason: 'healed', detected_at: '' })) : [],
      });
      setAv(aRes.data ?? null);
      setHsm(hsmRes.data ?? null);
      const logRaw = lRes.data.entries ?? lRes.data.events ?? lRes.data;
      setInfraLog(Array.isArray(logRaw) ? logRaw : []);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load security infrastructure data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 30 s — configuration and model data changes less frequently.
  usePolling(load, 30_000);

  // Lazy-load threat intel when tab selected
  useEffect(() => {
    if (tab !== 'threat') return;
    setThreatLoading(true);
    superadminApi.threatIntel()
      .then(r => setThreatIntel(r.data.indicators ?? r.data.threats ?? r.data ?? []))
      .catch(() => setThreatIntel([]))
      .finally(() => setThreatLoading(false));
  }, [tab]);

  const triggerScan = async (type: 'integrity' | 'av') => {
    setBusy(type); setMsg('');
    try {
      if (type === 'integrity') {
        await superadminApi.triggerIntegrityScan();
        setMsgOk(false);
        setMsg('File integrity scan started');
      } else {
        await superadminApi.triggerAvScan();
        setMsgOk(false);
        setMsg('Antivirus scan started');
      }
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Scan trigger failed'));
    } finally { setBusy(null); }
  };

  const rotateKey = async (keyId: string) => {
    setBusy(keyId); setMsg('');
    try {
      await superadminApi.hsmRotateKey(keyId);
      setMsgOk(true);
      setMsg(`Key ${keyId} rotated successfully`);
      await load();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Key rotation failed'));
    } finally { setBusy(null); setRotateConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  return (
    <>

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

      <ActionBanner message={msg} ok={msgOk} onDismiss={() => setMsg('')} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Self-Healer" value={healer?.status ?? 'unknown'} icon="🔧" accent={STATUS_COLOR(healer?.status ?? '')} />
        <KpiTile label="Tracked Files" value={healer?.tracked_files ?? 0} icon="📁" accent="#60a5fa" />
        <KpiTile label="AV Threats" value={av?.threats_found ?? 0} icon="🦠" accent={av?.threats_found ? '#f87171' : '#22c55e'} />
        <KpiTile label="HSM Keys" value={hsm?.key_count ?? 0} icon="🔑" accent="#a78bfa" />
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {(['healer', 'av', 'hsm', 'log', 'threat'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? '#1e293b' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? '#f8fafc' : '#64748b',
            padding: '7px 14px', fontSize: 13, cursor: 'pointer',
          }}>
            {{ healer: 'Self-Healer', av: 'Antivirus', hsm: 'HSM Vault', log: 'Infra Log', threat: 'Threat Intel' }[t]}
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

      {/* ── TAB: Threat Intelligence ── */}
      {tab === 'threat' && (
        <SectionCard title="Threat Intelligence" icon="🛡️" accent="#ef4444"
          subtitle="Live IOC feed — blocked IPs, malicious domains, hash signatures"
          actions={<ActionBtn label="Refresh" onClick={() => {
            setThreatLoading(true);
            superadminApi.threatIntel()
              .then(r => setThreatIntel(r.data.indicators ?? r.data.threats ?? r.data ?? []))
              .catch(() => setThreatIntel([]))
              .finally(() => setThreatLoading(false));
          }} loading={threatLoading} icon="🔄" size="sm" />}>
          {threatLoading ? (
            <LoadingRows rows={4} />
          ) : threatIntel.length === 0 ? (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No threat indicators loaded.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #1e293b' }}>
                    {['Type', 'Indicator', 'Severity', 'Source', 'First Seen', 'Last Seen', 'Blocked'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {threatIntel.map((ti, i) => {
                    const sevColor = ti.severity === 'critical' ? '#f87171' : ti.severity === 'high' ? '#f97316' : ti.severity === 'medium' ? '#fbbf24' : '#94a3b8';
                    return (
                      <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: '#1e293b', color: '#60a5fa', textTransform: 'uppercase' }}>{ti.type}</span>
                        </td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12, color: '#f1f5f9', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={ti.value}>{ti.value}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: sevColor }}>{ti.severity.toUpperCase()}</span>
                        </td>
                        <td style={{ padding: '8px 12px', fontSize: 11, color: '#64748b' }}>{ti.source}</td>
                        <td style={{ padding: '8px 12px', fontSize: 11, color: '#475569', whiteSpace: 'nowrap' }}>{fmtDate(ti.first_seen)}</td>
                        <td style={{ padding: '8px 12px', fontSize: 11, color: '#475569', whiteSpace: 'nowrap' }}>{fmtDate(ti.last_seen)}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: ti.blocked ? '#4ade80' : '#f87171' }}>{ti.blocked ? '✅ Yes' : '❌ No'}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}
    </>
  );
};

export default SecurityInfraSection;
