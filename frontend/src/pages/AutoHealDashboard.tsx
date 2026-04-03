/**
 * pages/AutoHealDashboard.tsx
 * Route: /auto-heal
 *
 * Unified self-healing and antivirus operations centre:
 *   - SelfHealer: file integrity drift, patch history, baseline rebuild
 *   - AntivirusScanner: threat list, on-demand scan, quarantine
 *   - FixApprovalQueue: LLM-generated code fix review
 */

import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../hooks/useApi';
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
  const { data } = await api.get<HealStatus>('/security/heal/status');
  return data;
}

async function fetchDrift(limit = 50): Promise<DriftEvent[]> {
  const { data } = await api.get<DriftEvent[]>(`/security/heal/drift?limit=${limit}`);
  return data ?? [];
}

async function fetchPatches(limit = 50): Promise<PatchRecord[]> {
  const { data } = await api.get<PatchRecord[]>(`/security/heal/patches?limit=${limit}`);
  return data ?? [];
}

async function triggerScan(): Promise<void> {
  await api.post('/security/heal/scan/now');
}

async function rebuildBaseline(): Promise<void> {
  await api.post('/security/heal/baseline/rebuild');
}

async function fetchAvStatus(): Promise<AvStatus> {
  const { data } = await api.get<AvStatus>('/security/av/status');
  return data;
}

async function fetchThreats(): Promise<Threat[]> {
  const { data } = await api.get<Threat[]>('/security/av/threats');
  return data ?? [];
}

async function triggerAvScan(): Promise<void> {
  await api.post('/security/av/scan');
}

async function quarantineThreat(threatId: string): Promise<void> {
  await api.post('/security/av/quarantine', { threat_id: threatId });
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

const PatchTable: React.FC<{ patches: PatchRecord[]; loading: boolean }> = ({ patches, loading }) => {
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <div style={panelStyle}>
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
            <div key={i}>
              <div
                style={{ ...tableRowStyle, cursor: 'pointer' }}
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <span style={successBadgeStyle(p.success)}>{p.success ? '✅ applied' : '❌ failed'}</span>
                <span style={monoStyle}>{p.file}</span>
                <span style={timeStyle}>{new Date(p.applied_at).toLocaleTimeString()}</span>
              </div>
              {expanded === i && p.diff && (
                <pre style={diffStyle}>{p.diff}</pre>
              )}
              {expanded === i && !p.diff && (
                <div style={{ padding: '6px 16px', color: '#94a3b8', fontSize: 11 }}>{p.message}</div>
              )}
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
  const [healStatus, setHealStatus] = useState<HealStatus | null>(null);
  const [drift, setDrift] = useState<DriftEvent[]>([]);
  const [patches, setPatches] = useState<PatchRecord[]>([]);
  const [avStatus, setAvStatus] = useState<AvStatus | null>(null);
  const [threats, setThreats] = useState<Threat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [avScanning, setAvScanning] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [quarantining, setQuarantining] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [hs, dr, pt, avs, th] = await Promise.allSettled([
        fetchHealStatus(),
        fetchDrift(),
        fetchPatches(),
        fetchAvStatus(),
        fetchThreats(),
      ]);
      if (hs.status === 'fulfilled') setHealStatus(hs.value);
      if (dr.status === 'fulfilled') setDrift(dr.value);
      if (pt.status === 'fulfilled') setPatches(pt.value);
      if (avs.status === 'fulfilled') setAvStatus(avs.value);
      if (th.status === 'fulfilled') setThreats(th.value);
      setError(null);
    } catch {
      setError('Failed to load auto-heal data — backend may be offline');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 20_000);
    return () => clearInterval(id);
  }, [loadAll]);

  const handleScan = async () => {
    setScanning(true);
    try { await triggerScan(); await loadAll(); } catch { setError('Scan trigger failed'); }
    finally { setScanning(false); }
  };

  const handleAvScan = async () => {
    setAvScanning(true);
    try { await triggerAvScan(); await loadAll(); } catch { setError('AV scan trigger failed'); }
    finally { setAvScanning(false); }
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
    <div style={pageStyle}>
      <PageHeader
        title="Auto-Heal & Antivirus"
        subtitle="Code integrity monitor · Self-healing engine · Malware scanner"
      />

      {error && <div style={errorBannerStyle}>{error}</div>}

      {/* Action bar */}
      <div style={actionBarStyle}>
        <button style={actionBtnStyle} onClick={handleScan} disabled={scanning}>
          {scanning ? 'Scanning…' : '🔍 Integrity Scan'}
        </button>
        <button style={actionBtnStyle} onClick={handleRebuild} disabled={rebuilding}>
          {rebuilding ? 'Rebuilding…' : '📐 Rebuild Baseline'}
        </button>
        <button style={{ ...actionBtnStyle, background: '#7c3aed' }} onClick={handleAvScan} disabled={avScanning}>
          {avScanning ? 'Scanning…' : '🛡️ AV Full Scan'}
        </button>
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
