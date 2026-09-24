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
import { AlertTriangle, Bug, CheckCircle2, ClipboardList, Folder, KeyRound, RefreshCw, Shield, Wrench, XCircle } from 'lucide-react';
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
  threats_found?: number;
  files_scanned?: number;
  /** Neither of these was ever sent, so the panel showed "N/A" and the literal
      word "undefined". security/antivirus.py knows both; the endpoint reports
      them now. */
  clamav_available?: boolean;
  yara_rules_loaded?: number;
  engines_detail?: string;
}

/**
 * GET /superadmin/security-infra/hsm.
 *
 * Every field here was optimistic. The endpoint returned `type`, `status`,
 * `keys_managed`, `fips_compliant` and `provider`; this declared `hsm_type`,
 * `initialized`, `key_count` and `keys`. TypeScript accepted it because the
 * response is read untyped, so `hsm.hsm_type.toUpperCase()` threw and took the
 * whole Sec. Infra section down with it.
 *
 * The backend now returns both spellings. The fields stay optional so a shape
 * mismatch degrades a label instead of crashing a page.
 */
interface HSMStatus {
  hsm_type?: string;
  type?: string;
  initialized?: boolean;
  key_count?: number;
  keys_managed?: number;
  keys?: { key_id: string; created_at: string; size_bytes: number; active: boolean }[];
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
        setMsgOk(true);
        setMsg('File integrity scan started');
      } else {
        await superadminApi.triggerAvScan();
        setMsgOk(true);
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
        <KpiTile label="Self-Healer" value={healer?.status ?? 'unknown'} icon={<Wrench size={18} aria-hidden />} accent={STATUS_COLOR(healer?.status ?? '')} />
        <KpiTile label="Tracked Files" value={healer?.tracked_files ?? 0} icon={<Folder size={18} aria-hidden />} accent="#60a5fa" />
        <KpiTile label="AV Threats" value={av?.threats_found ?? 0} icon={<Bug size={18} aria-hidden />} accent={av?.threats_found ? '#f87171' : '#22c55e'} />
        <KpiTile label="HSM Keys" value={hsm?.key_count ?? 0} icon={<KeyRound size={18} aria-hidden />} accent="#a78bfa" />
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {(['healer', 'av', 'hsm', 'log', 'threat'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? 'var(--raised)' : 'transparent',
            border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`,
            borderRadius: 8, color: tab === t ? 'var(--text-strong)' : 'var(--text-muted)',
            padding: '7px 14px', fontSize: 'var(--fs-body)', cursor: 'pointer',
          }}>
            {{ healer: 'Self-Healer', av: 'Antivirus', hsm: 'HSM Vault', log: 'Infra Log', threat: 'Threat Intel' }[t]}
          </button>
        ))}
      </div>

      {tab === 'healer' && healer && (
        <>
          <SectionCard title="File Integrity Monitor" icon={<Wrench size={18} aria-hidden />} accent="#22c55e"
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
                <div key={item.label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px' }}>
                  <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: item.color, marginTop: 4 }}>{String(item.value)}</div>
                </div>
              ))}
            </div>
            {healer.violations?.length > 0 && (
              <div>
                <div style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--loss)', marginBottom: 8 }}><AlertTriangle size="1em" aria-hidden /> Integrity Violations</div>
                {healer.violations.map((v, i) => (
                  <div key={i} style={{ background: 'rgba(248,113,113,0.05)', border: '1px solid #7f1d1d', borderRadius: 6, padding: '8px 12px', marginBottom: 6 }}>
                    <div style={{ fontSize: 'var(--fs-body)', fontFamily: 'monospace', color: 'var(--loss)' }}>{v.file}</div>
                    <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-dim)', marginTop: 2 }}>{v.reason} · {fmtDate(v.detected_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </>
      )}

      {tab === 'av' && av && (
        <SectionCard title="Antivirus Scanner" icon={<Bug size={18} aria-hidden />} accent="#f97316"
          subtitle="YARA rules + ClamAV + entropy analysis + suspicious pattern detection"
          actions={
            <ActionBtn label="Run Full Scan" onClick={() => triggerScan('av')} loading={busy === 'av'} accent="#f97316" size="sm" />
          }>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {[
              { label: 'Status',          value: av.status,                                    color: STATUS_COLOR(av.status) },
              { label: 'Last Scan',       value: fmtDate(av.last_scan),                        color: '#94a3b8' },
              { label: 'Files Scanned',   value: (av.files_scanned ?? 0).toLocaleString(),     color: '#60a5fa' },
              { label: 'Threats Found',   value: av.threats_found ?? 0,                        color: av.threats_found ? '#f87171' : '#22c55e' },
              { label: 'ClamAV',          value: av.clamav_available ? 'Available' : 'N/A',   color: av.clamav_available ? '#22c55e' : '#64748b' },
              /* Rendered the literal string "undefined": the API never sent
                 yara_rules_loaded, and `String(undefined)` is "undefined". It
                 sends it now; the fallback keeps a missing field readable
                 rather than turning it into a word the user has to interpret. */
              { label: 'YARA Rules',      value: av.yara_rules_loaded ?? '—',                   color: '#a78bfa' },
            ].map(item => (
              <div key={item.label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px' }}>
                <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: item.color, marginTop: 4 }}>{String(item.value)}</div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {tab === 'hsm' && hsm && (
        <SectionCard title="HSM Vault — Key Management" icon={<KeyRound size={18} aria-hidden />} accent="#a78bfa"
          /* `hsm.hsm_type.toUpperCase()` crashed the entire section with
             "undefined is not an object": the API's field is `type`, not
             `hsm_type`, and `keys` was never sent at all. The backend now
             returns both spellings, but an unguarded read is what turned a
             field-name mismatch into a whole page that would not load — so the
             optional chaining stays regardless. */
          subtitle={`${(hsm.hsm_type ?? hsm.type ?? 'unknown').toUpperCase()} HSM · ${hsm.initialized ? 'Initialized' : 'Not initialized'}`}>
          {(hsm.keys?.length ?? 0) === 0 ? (
            <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 24 }}>No keys in vault</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--fs-body)'}}>
              <thead>
                <tr>
                  {['Key ID', 'Created', 'Size', 'Active', 'Actions'].map(h => (
                    <th key={h} style={{ textAlign: 'left', padding: '10px 16px', color: 'var(--text-muted)', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(hsm.keys ?? []).map(k => (
                  <tr key={k.key_id} className="sa-row" style={{ borderBottom: '1px solid var(--hairline)' }}>
                    <td style={{ padding: '10px 16px', fontFamily: 'monospace', fontSize: 'var(--fs-body)', color: 'var(--ai-model)' }}>{k.key_id}</td>
                    <td style={{ padding: '10px 16px', color: 'var(--text-muted)', fontSize: 'var(--fs-body)'}}>{fmtDate(k.created_at)}</td>
                    <td style={{ padding: '10px 16px', color: 'var(--text-dim)', fontSize: 'var(--fs-body)'}}>{k.size_bytes} B</td>
                    <td style={{ padding: '10px 16px' }}>
                      <span style={{ color: k.active ? 'var(--gain)' : 'var(--loss)', fontSize: 'var(--fs-body)', fontWeight: 700 }}>
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
        <SectionCard title="Security Infrastructure Log" icon={<ClipboardList size={18} aria-hidden />} accent="#64748b">
          {infraLog.length === 0 ? (
            <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 24 }}>No log entries</div>
          ) : (
            infraLog.slice(0, 100).map((entry, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--hairline)', alignItems: 'flex-start' }}>
                <div style={{
                  width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
                  background: entry.severity === 'critical' ? 'var(--loss)' : entry.severity === 'warning' ? 'var(--warn)' : 'var(--gain)',
                }} />
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text-dim)' }}>[{entry.component}]</span>
                  {' '}
                  <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)' }}>{entry.event}</span>
                </div>
                <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', flexShrink: 0 }}>{fmtDate(entry.timestamp)}</div>
              </div>
            ))
          )}
        </SectionCard>
      )}

      {/* ── TAB: Threat Intelligence ── */}
      {tab === 'threat' && (
        <SectionCard title="Threat Intelligence" icon={<Shield size={18} aria-hidden />} accent="#ef4444"
          subtitle="Live IOC feed — blocked IPs, malicious domains, hash signatures"
          actions={<ActionBtn label="Refresh" onClick={() => {
            setThreatLoading(true);
            superadminApi.threatIntel()
              .then(r => setThreatIntel(r.data.indicators ?? r.data.threats ?? r.data ?? []))
              .catch(() => setThreatIntel([]))
              .finally(() => setThreatLoading(false));
          }} loading={threatLoading} icon={<RefreshCw size={18} aria-hidden />} size="sm" />}>
          {threatLoading ? (
            <LoadingRows rows={4} />
          ) : threatIntel.length === 0 ? (
            <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 24 }}>No threat indicators loaded.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--fs-body)'}}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Type', 'Indicator', 'Severity', 'Source', 'First Seen', 'Last Seen', 'Blocked'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 'var(--fs-label)', fontWeight: 600, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {threatIntel.map((ti, i) => {
                    const sevColor = ti.severity === 'critical' ? '#f87171' : ti.severity === 'high' ? '#f97316' : ti.severity === 'medium' ? '#fbbf24' : '#94a3b8';
                    return (
                      <tr key={i} className="sa-row" style={{ borderBottom: '1px solid var(--hairline)' }}>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 'var(--fs-micro)', fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: 'var(--raised)', color: 'var(--link)', textTransform: 'uppercase' }}>{ti.type}</span>
                        </td>
                        <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 'var(--fs-body)', color: 'var(--text-strong)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={ti.value}>{ti.value}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 'var(--fs-label)', fontWeight: 700, color: sevColor }}>{ti.severity.toUpperCase()}</span>
                        </td>
                        <td style={{ padding: '8px 12px', fontSize: 'var(--fs-label)', color: 'var(--text-muted)' }}>{ti.source}</td>
                        <td style={{ padding: '8px 12px', fontSize: 'var(--fs-label)', color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDate(ti.first_seen)}</td>
                        <td style={{ padding: '8px 12px', fontSize: 'var(--fs-label)', color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDate(ti.last_seen)}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{ fontSize: 'var(--fs-label)', fontWeight: 700, color: ti.blocked ? 'var(--gain)' : 'var(--loss)' }}>{ti.blocked ? <><CheckCircle2 size="1em" aria-hidden="true" /> Yes</> : <><XCircle size="1em" aria-hidden="true" /> No</>}</span>
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
