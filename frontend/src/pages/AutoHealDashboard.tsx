/**
 * pages/AutoHealDashboard.tsx
 * Route: /auto-heal
 *
 * Unified self-healing and antivirus operations centre:
 *   - SelfHealer: file integrity drift, patch history, baseline rebuild
 *   - AntivirusScanner: threat list, on-demand scan, quarantine
 *   - FixApprovalQueue: LLM-generated code fix review
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { securityHealingApi } from '../hooks/useApi';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { FixApprovalQueue } from '../components/FixApprovalQueue';

// ── Types ─────────────────────────────────────────────────────────────────────

interface HealStatus {
  running: boolean;
  baseline_files: number;
  drift_events: number;
  patches_applied: number;
  patches_failed: number;
  last_scan: string | null;
}

interface DriftEvent {
  path: string;
  type: string;
  ts: string;
  expected?: string;
  actual?: string;
}

interface PatchRecord {
  endpoint: string;
  file: string;
  success: boolean;
  message: string;
  diff: string;
  applied_at: string;
}

interface AvStatus {
  running: boolean;
  yara_enabled: boolean;
  clamd_enabled: boolean;
  total_threats: number;
  last_scan: {
    scanned_files: number;
    new_threats: number;
    scan_duration_s: number;
    completed_at: string;
  } | null;
}

interface Threat {
  id: string;
  path: string;
  threat_type: string;
  severity: string;
  detail: string;
  detected_at: string;
  sha256: string;
  quarantined: boolean;
  quarantine_path: string | null;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchHealStatus(): Promise<HealStatus> {
  const { data } = await securityHealingApi.healStatus() as { data: HealStatus };
  return data;
}

async function fetchDrift(limit = 50): Promise<DriftEvent[]> {
  const res = await securityHealingApi.drift() as { data: DriftEvent[] | { events?: DriftEvent[] } };
  return (Array.isArray(res.data) ? res.data : (res.data as { events?: DriftEvent[] }).events) ?? [];
}

async function fetchPatches(limit = 50): Promise<PatchRecord[]> {
  const res = await securityHealingApi.patches() as { data: PatchRecord[] | { patches?: PatchRecord[] } };
  return (Array.isArray(res.data) ? res.data : (res.data as { patches?: PatchRecord[] }).patches) ?? [];
}

async function triggerScan(): Promise<void> {
  await securityHealingApi.scanNow();
}

async function rebuildBaseline(): Promise<void> {
  await securityHealingApi.rebuildBaseline();
}

async function fetchAvStatus(): Promise<AvStatus> {
  const { data } = await securityHealingApi.avStatus() as { data: AvStatus };
  return data;
}

async function fetchThreats(): Promise<Threat[]> {
  const res = await securityHealingApi.avThreats() as { data: Threat[] | { threats?: Threat[] } };
  return (Array.isArray(res.data) ? res.data : (res.data as { threats?: Threat[] }).threats) ?? [];
}

async function triggerAvScan(): Promise<void> {
  await securityHealingApi.avScan();
}

async function quarantineThreat(threatId: string): Promise<void> {
  await securityHealingApi.avQuarantine({ threat_id: threatId });
}

// ── Sub-components ────────────────────────────────────────────────────────────

const DriftTable: React.FC<{ events: DriftEvent[]; loading: boolean }> = ({ events, loading }) => (
  <div style={panelStyle}>
    <div style={panelHeaderStyle}>
      <span style={panelTitleStyle}>File Integrity Drift</span>
      <span style={panelCountStyle}>{events.length}</span>
    </div>
    {loading ? (
      <div style={emptyStyle}>Loading…</div>
    ) : events.length === 0 ? (
      <div style={emptyStyle}>No drift detected — all files match baseline</div>
    ) : (
      <div style={tableWrapStyle}>
        {events.slice(0, 30).map((e, i) => (
          <div key={i} style={tableRowStyle}>
            <span style={typeBadgeStyle(e.type)}>{e.type}</span>
            <span style={monoStyle}>{e.path}</span>
            <span style={timeStyle}>{new Date(e.ts).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    )}
  </div>
);

// ── Diff viewer modal ─────────────────────────────────────────────────────────

const DiffModal: React.FC<{ patch: PatchRecord; onClose: () => void }> = ({ patch, onClose }) => (
  <div
    style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
    onClick={onClose}
  >
    <div
      style={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 12, maxWidth: 860, width: '100%', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
      onClick={e => e.stopPropagation()}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 20px', borderBottom: '1px solid #1e2d3d' }}>
        <div>
          <div style={{ fontWeight: 700, color: '#f1f5f9', fontSize: 14 }}>Patch Diff — {patch.file}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            {patch.endpoint} · {new Date(patch.applied_at).toLocaleString()}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, background: patch.success ? '#14532d' : '#450a0a', color: patch.success ? '#4ade80' : '#f87171' }}>
            {patch.success ? '✅ Applied' : '❌ Failed'}
          </span>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}>×</button>
        </div>
      </div>
      <div style={{ overflowY: 'auto', padding: '16px 20px', flex: 1 }}>
        {patch.message && (
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, padding: '8px 12px', fontSize: 13, color: '#94a3b8', marginBottom: 12 }}>
            {patch.message}
          </div>
        )}
        {patch.diff ? (
          <pre style={{ ...diffStyle, margin: 0, maxHeight: 'none' }}>
            {patch.diff.split('\n').map((line, i) => (
              <span key={i} style={{
                display: 'block',
                color: line.startsWith('+') ? '#4ade80' : line.startsWith('-') ? '#f87171' : line.startsWith('@@') ? '#60a5fa' : '#94a3b8',
                background: line.startsWith('+') ? 'rgba(74,222,128,0.05)' : line.startsWith('-') ? 'rgba(248,113,113,0.05)' : 'transparent',
              }}>
                {line}
              </span>
            ))}
          </pre>
        ) : (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>No diff available for this patch.</div>
        )}
      </div>
    </div>
  </div>
);

const PatchTable: React.FC<{ patches: PatchRecord[]; loading: boolean }> = ({ patches, loading }) => {
  const [diffPatch, setDiffPatch] = useState<PatchRecord | null>(null);
  return (
    <div style={panelStyle}>
      {diffPatch && <DiffModal patch={diffPatch} onClose={() => setDiffPatch(null)} />}
      <div style={panelHeaderStyle}>
        <span style={panelTitleStyle}>Patch History</span>
        <span style={panelCountStyle}>{patches.length}</span>
      </div>
      {loading ? (
        <div style={emptyStyle}>Loading…</div>
      ) : patches.length === 0 ? (
        <div style={emptyStyle}>No patches applied yet</div>
      ) : (
        <div style={tableWrapStyle}>
          {patches.slice(0, 20).map((p, i) => (
            <div key={i} style={{ ...tableRowStyle, cursor: 'pointer' }} onClick={() => setDiffPatch(p)}>
              <span style={successBadgeStyle(p.success)}>{p.success ? '✅ applied' : '❌ failed'}</span>
              <span style={monoStyle}>{p.file}</span>
              <span style={{ ...timeStyle, marginLeft: 'auto' }}>{new Date(p.applied_at).toLocaleTimeString()}</span>
              <span style={{ fontSize: 11, color: '#3b82f6', marginLeft: 8 }}>View diff →</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ThreatTable: React.FC<{
  threats: Threat[];
  loading: boolean;
  onQuarantine: (id: string) => void;
  quarantining: string | null;
}> = ({ threats, loading, onQuarantine, quarantining }) => (
  <div style={panelStyle}>
    <div style={panelHeaderStyle}>
      <span style={panelTitleStyle}>Detected Threats</span>
      <span style={panelCountStyle}>{threats.length}</span>
    </div>
    {loading ? (
      <div style={emptyStyle}>Loading…</div>
    ) : threats.length === 0 ? (
      <div style={emptyStyle}>No threats detected</div>
    ) : (
      <div style={tableWrapStyle}>
        {threats.slice(0, 30).map((t) => (
          <div key={t.id} style={tableRowStyle}>
            <span style={severityBadgeStyle(t.severity)}>{t.severity}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={monoStyle}>{t.path}</div>
              <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 2 }}>{t.detail}</div>
            </div>
            {!t.quarantined ? (
              <button
                style={quarantineBtnStyle}
                onClick={() => onQuarantine(t.id)}
                disabled={quarantining === t.id}
              >
                {quarantining === t.id ? '…' : 'Quarantine'}
              </button>
            ) : (
              <span style={quarantinedBadgeStyle}>quarantined</span>
            )}
          </div>
        ))}
      </div>
    )}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const AutoHealDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [healStatus, setHealStatus] = useState<HealStatus | null>(null);
  const [drift, setDrift] = useState<DriftEvent[]>([]);
  const [patches, setPatches] = useState<PatchRecord[]>([]);
  const [avStatus, setAvStatus] = useState<AvStatus | null>(null);
  const [threats, setThreats] = useState<Threat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning]         = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [avScanning, setAvScanning]     = useState(false);
  const [avProgress, setAvProgress]     = useState(0);
  const [rebuilding, setRebuilding]     = useState(false);
  const [quarantining, setQuarantining] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [hs, dr, pt, avs, th] = await Promise.allSettled([
        fetchHealStatus(),
        fetchDrift(),
        fetchPatches(),
        fetchAvStatus(),
        fetchThreats(),
      ]);
      if (!mountedRef.current) return;
      if (hs.status === 'fulfilled') setHealStatus(hs.value);
      if (dr.status === 'fulfilled') setDrift(dr.value);
      if (pt.status === 'fulfilled') setPatches(pt.value);
      if (avs.status === 'fulfilled') setAvStatus(avs.value);
      if (th.status === 'fulfilled') setThreats(th.value);
      setError(null);
    } catch {
      if (!mountedRef.current) return;
      setError('Failed to load auto-heal data. Retrying in 20 s…');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 20_000);
    return () => clearInterval(id);
  }, [loadAll]);

  const handleScan = async () => {
    setScanning(true);
    setScanProgress(0);
    // Simulate progress while scan runs (real progress from WS if available)
    const interval = setInterval(() => setScanProgress(p => Math.min(p + 8, 90)), 400);
    try {
      await triggerScan();
      setScanProgress(100);
      await loadAll();
    } catch { setError('Scan trigger failed'); }
    finally { clearInterval(interval); setScanning(false); setTimeout(() => setScanProgress(0), 1500); }
  };

  const handleAvScan = async () => {
    setAvScanning(true);
    setAvProgress(0);
    const interval = setInterval(() => setAvProgress(p => Math.min(p + 5, 90)), 600);
    try {
      await triggerAvScan();
      setAvProgress(100);
      await loadAll();
    } catch { setError('AV scan trigger failed'); }
    finally { clearInterval(interval); setAvScanning(false); setTimeout(() => setAvProgress(0), 1500); }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    try { await rebuildBaseline(); await loadAll(); } catch { setError('Baseline rebuild failed'); }
    finally { setRebuilding(false); }
  };

  const handleQuarantine = async (id: string) => {
    setQuarantining(id);
    try { await quarantineThreat(id); await loadAll(); } catch { setError('Quarantine failed'); }
    finally { setQuarantining(null); }
  };

  const criticalThreats = threats.filter(t => t.severity === 'critical' && !t.quarantined).length;
  const highThreats = threats.filter(t => t.severity === 'high' && !t.quarantined).length;

  return (
    <div className="page-content">
      <PageHeader
        title="Auto-Heal & Antivirus"
        subtitle="Code integrity monitor · Self-healing engine · Malware scanner"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate('/security')}
              style={{ padding: '6px 14px', background: 'rgba(248,113,113,0.12)', border: '1px solid rgba(248,113,113,0.35)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              🛡 Security
            </button>
            <button onClick={() => navigate('/')}
              style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              📊 Dashboard
            </button>
          </div>
        }
      />

      {error && <div style={errorBannerStyle}>{error}</div>}

      {/* Action bar */}
      <div style={actionBarStyle}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button style={actionBtnStyle} onClick={handleScan} disabled={scanning}>
            {scanning ? `🔍 Scanning… ${scanProgress}%` : '🔍 Integrity Scan'}
          </button>
          {scanning && (
            <div style={{ width: '100%', background: '#1e293b', borderRadius: 4, height: 4, overflow: 'hidden' }}>
              <div style={{ width: `${scanProgress}%`, height: '100%', background: '#3b82f6', borderRadius: 4, transition: 'width 0.3s ease' }} />
            </div>
          )}
        </div>
        <button style={actionBtnStyle} onClick={handleRebuild} disabled={rebuilding}>
          {rebuilding ? 'Rebuilding…' : '📐 Rebuild Baseline'}
        </button>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button style={{ ...actionBtnStyle, background: '#7c3aed' }} onClick={handleAvScan} disabled={avScanning}>
            {avScanning ? `🛡️ AV Scan… ${avProgress}%` : '🛡️ AV Full Scan'}
          </button>
          {avScanning && (
            <div style={{ width: '100%', background: '#1e293b', borderRadius: 4, height: 4, overflow: 'hidden' }}>
              <div style={{ width: `${avProgress}%`, height: '100%', background: '#7c3aed', borderRadius: 4, transition: 'width 0.3s ease' }} />
            </div>
          )}
        </div>
      </div>

      {/* KPI strip — SelfHealer */}
      <div style={sectionLabelStyle}>Self-Healer</div>
      <div style={kpiGridStyle}>
        <MetricCard
          label="Baseline Files"
          value={healStatus?.baseline_files ?? '—'}
          icon="📁"
          loading={loading}
        />
        <MetricCard
          label="Drift Events"
          value={healStatus?.drift_events ?? '—'}
          delta={healStatus && healStatus.drift_events > 0 ? 'Files changed unexpectedly' : undefined}
          deltaPositive={false}
          icon="⚠️"
          loading={loading}
        />
        <MetricCard
          label="Patches Applied"
          value={healStatus?.patches_applied ?? '—'}
          deltaPositive={true}
          icon="🩹"
          loading={loading}
        />
        <MetricCard
          label="Patches Failed"
          value={healStatus?.patches_failed ?? '—'}
          deltaPositive={false}
          icon="❌"
          loading={loading}
        />
      </div>

      {/* KPI strip — Antivirus */}
      <div style={sectionLabelStyle}>Antivirus</div>
      <div style={kpiGridStyle}>
        <MetricCard
          label="Total Threats"
          value={avStatus?.total_threats ?? '—'}
          delta={criticalThreats > 0 ? `${criticalThreats} critical` : undefined}
          deltaPositive={false}
          icon="🦠"
          loading={loading}
        />
        <MetricCard
          label="Critical"
          value={criticalThreats}
          deltaPositive={criticalThreats === 0}
          icon="🚨"
          loading={loading}
        />
        <MetricCard
          label="High"
          value={highThreats}
          deltaPositive={highThreats === 0}
          icon="⚡"
          loading={loading}
        />
        <MetricCard
          label="YARA"
          value={avStatus?.yara_enabled ? 'ON' : 'OFF'}
          delta={avStatus?.clamd_enabled ? 'ClamAV ON' : 'ClamAV OFF'}
          deltaPositive={avStatus?.yara_enabled ?? false}
          icon="🔬"
          loading={loading}
        />
      </div>

      {/* Main grid */}
      <div style={mainGridStyle}>
        <DriftTable events={drift} loading={loading} />
        <PatchTable patches={patches} loading={loading} />
      </div>

      <ThreatTable
        threats={threats}
        loading={loading}
        onQuarantine={handleQuarantine}
        quarantining={quarantining}
      />

      {/* LLM fix approval queue */}
      <div style={sectionLabelStyle}>LLM Fix Approval Queue</div>
      <FixApprovalQueue />
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 16,
  padding: '20px 24px', maxWidth: 1400, margin: '0 auto',
};

const errorBannerStyle: React.CSSProperties = {
  background: '#f9731622', border: '1px solid #f97316',
  borderRadius: 8, color: '#fdba74', fontSize: 12, padding: '10px 16px',
};

const actionBarStyle: React.CSSProperties = {
  display: 'flex', gap: 10, flexWrap: 'wrap',
};

const actionBtnStyle: React.CSSProperties = {
  background: '#1d4ed8', border: 'none', borderRadius: 6,
  color: '#fff', cursor: 'pointer', fontSize: 12,
  fontWeight: 700, padding: '8px 16px',
};

const sectionLabelStyle: React.CSSProperties = {
  color: '#64748b', fontSize: 11, fontWeight: 700,
  letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: 4,
};

const kpiGridStyle: React.CSSProperties = {
  display: 'grid', gap: 12,
  gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
};

const mainGridStyle: React.CSSProperties = {
  display: 'grid', gap: 16,
  gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
};

const panelStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10, display: 'flex', flexDirection: 'column', overflow: 'hidden',
};

const panelHeaderStyle: React.CSSProperties = {
  alignItems: 'center', borderBottom: '1px solid var(--border, #334155)',
  display: 'flex', justifyContent: 'space-between', padding: '12px 16px',
};

const panelTitleStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)', fontSize: 13, fontWeight: 700,
};

const panelCountStyle: React.CSSProperties = {
  background: '#334155', borderRadius: 10, color: '#94a3b8',
  fontSize: 11, fontWeight: 700, padding: '2px 8px',
};

const emptyStyle: React.CSSProperties = {
  color: '#64748b', fontSize: 12, padding: '20px 16px', textAlign: 'center',
};

const tableWrapStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', maxHeight: 320, overflowY: 'auto',
};

const tableRowStyle: React.CSSProperties = {
  alignItems: 'center', borderBottom: '1px solid #1e293b',
  display: 'flex', gap: 10, padding: '8px 16px',
};

const monoStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)', fontFamily: 'monospace',
  fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
};

const timeStyle: React.CSSProperties = {
  color: '#64748b', fontSize: 11, flexShrink: 0,
};

const diffStyle: React.CSSProperties = {
  background: '#0f172a', color: '#94a3b8', fontFamily: 'monospace',
  fontSize: 10, margin: 0, maxHeight: 200, overflowY: 'auto',
  padding: '8px 16px', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
};

const DRIFT_COLOURS: Record<string, string> = {
  modified: '#f97316', deleted: '#ef4444', new_file: '#22c55e',
};

function typeBadgeStyle(type: string): React.CSSProperties {
  const c = DRIFT_COLOURS[type] ?? '#94a3b8';
  return {
    background: c + '22', border: `1px solid ${c}`, borderRadius: 10,
    color: c, fontSize: 10, fontWeight: 700, padding: '2px 7px',
    flexShrink: 0, textTransform: 'capitalize',
  };
}

function successBadgeStyle(ok: boolean): React.CSSProperties {
  const c = ok ? '#22c55e' : '#ef4444';
  return {
    background: c + '22', border: `1px solid ${c}`, borderRadius: 10,
    color: c, fontSize: 10, fontWeight: 700, padding: '2px 7px', flexShrink: 0,
  };
}

const SEVERITY_COLOURS: Record<string, string> = {
  critical: '#dc2626', high: '#f97316', medium: '#facc15', low: '#22c55e',
};

function severityBadgeStyle(sev: string): React.CSSProperties {
  const c = SEVERITY_COLOURS[sev] ?? '#94a3b8';
  return {
    background: c + '22', border: `1px solid ${c}`, borderRadius: 10,
    color: c, fontSize: 10, fontWeight: 700, padding: '2px 7px',
    flexShrink: 0, textTransform: 'capitalize',
  };
}

const quarantineBtnStyle: React.CSSProperties = {
  background: '#7c3aed22', border: '1px solid #7c3aed', borderRadius: 6,
  color: '#a78bfa', cursor: 'pointer', fontSize: 11,
  fontWeight: 700, padding: '3px 10px', flexShrink: 0,
};

const quarantinedBadgeStyle: React.CSSProperties = {
  background: '#33415522', border: '1px solid #475569', borderRadius: 10,
  color: '#64748b', fontSize: 10, fontWeight: 700, padding: '2px 7px', flexShrink: 0,
};

export default AutoHealDashboard;
