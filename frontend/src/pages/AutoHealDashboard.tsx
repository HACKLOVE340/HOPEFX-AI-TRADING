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
import { Link } from 'react-router-dom';
import { securityHealingApi } from '../hooks/useApi';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/Badge';
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

// ── Drift detail modal ────────────────────────────────────────────────────────

const DriftDetailModal: React.FC<{ event: DriftEvent; onClose: () => void }> = ({ event, onClose }) => {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: '#0d1421', border: '1px solid #334155', borderRadius: 12, padding: 24, maxWidth: 560, width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>⚠️ Drift Event</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>✕</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { label: 'File Path', value: event.path, mono: true },
            { label: 'Change Type', value: event.type, mono: false },
            { label: 'Detected At', value: new Date(event.ts).toLocaleString(), mono: false },
          ].map(({ label, value, mono }) => (
            <div key={label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 13, color: '#e2e8f0', fontFamily: mono ? 'monospace' : 'inherit', wordBreak: 'break-all' }}>{value}</div>
            </div>
          ))}
          {(event.expected || event.actual) && (
            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Hash Comparison</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: '#22c55e', marginBottom: 2 }}>Expected</div>
                  <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-all' }}>{event.expected ?? '—'}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 2 }}>Actual</div>
                  <div style={{ fontSize: 11, color: '#f87171', fontFamily: 'monospace', wordBreak: 'break-all' }}>{event.actual ?? '—'}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Baseline drift gauge ──────────────────────────────────────────────────────

const BaselineDriftGauge: React.FC<{ driftCount: number; baselineFiles: number }> = ({ driftCount, baselineFiles }) => {
  const pct = baselineFiles > 0 ? Math.min((driftCount / baselineFiles) * 100, 100) : 0;
  const color = pct === 0 ? '#22c55e' : pct < 5 ? '#f59e0b' : '#ef4444';
  const label = pct === 0 ? 'Clean' : pct < 5 ? 'Minor Drift' : 'High Drift';

  return (
    <div style={{ padding: '12px 16px', background: '#0f172a', border: `1px solid ${color}30`, borderRadius: 8, marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color }}>Baseline Integrity — {label}</span>
        <span style={{ fontSize: 12, fontFamily: 'monospace', color }}>
          {driftCount} / {baselineFiles} files drifted ({pct.toFixed(1)}%)
        </span>
      </div>
      <div style={{ height: 8, background: '#1e293b', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4, transition: 'width 0.6s ease' }} />
      </div>
      {/* Type breakdown mini-bars */}
    </div>
  );
};

const DriftTable: React.FC<{ events: DriftEvent[]; loading: boolean; baselineFiles: number }> = ({ events, loading, baselineFiles }) => {
  const [selected, setSelected] = useState<DriftEvent | null>(null);

  // Group by type for summary
  const typeCounts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.type] = (acc[e.type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div style={panelStyle}>
      {selected && <DriftDetailModal event={selected} onClose={() => setSelected(null)} />}
      <div style={panelHeaderStyle}>
        <span style={panelTitleStyle}>File Integrity Drift</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {Object.entries(typeCounts).map(([type, count]) => (
            <span key={type} style={{ ...typeBadgeStyle(type), fontSize: 10 }}>{type}: {count}</span>
          ))}
          <span style={panelCountStyle}>{events.length}</span>
        </div>
      </div>
      {!loading && baselineFiles > 0 && (
        <div style={{ padding: '12px 16px 0' }}>
          <BaselineDriftGauge driftCount={events.length} baselineFiles={baselineFiles} />
        </div>
      )}
      {loading ? (
        <div style={emptyStyle}>Loading…</div>
      ) : events.length === 0 ? (
        <div style={emptyStyle}>✅ No drift detected — all files match baseline</div>
      ) : (
        <div style={tableWrapStyle}>
          {events.slice(0, 30).map((e, i) => (
            <div key={i} style={{ ...tableRowStyle, cursor: 'pointer' }}
              onClick={() => setSelected(e)}
              onMouseEnter={el => { (el.currentTarget as HTMLDivElement).style.background = '#111827'; }}
              onMouseLeave={el => { (el.currentTarget as HTMLDivElement).style.background = 'transparent'; }}>
              <span style={typeBadgeStyle(e.type)}>{e.type}</span>
              <span style={{ ...monoStyle, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.path}</span>
              <span style={timeStyle}>{new Date(e.ts).toLocaleTimeString()}</span>
              <span style={{ fontSize: 11, color: '#3b82f6', marginLeft: 6 }}>›</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

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
      setError('Failed to load auto-heal data — backend may be offline');
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
    <div style={pageStyle}>
      <PageHeader
        title="Auto-Heal & Antivirus"
        icon="🩺"
        subtitle="Code integrity monitor · Self-healing engine · Malware scanner"
        breadcrumbs={[
          { label: 'Home',        href: '/home' },
          { label: 'Admin Panel', href: '/admin' },
          { label: 'Auto-Heal' },
        ]}
        badge={
          highThreats > 0
            ? <Badge variant="danger" style={{ fontSize: 11 }}>{highThreats} Active Threat{highThreats !== 1 ? 's' : ''}</Badge>
            : healStatus?.running
            ? <Badge variant="info" style={{ fontSize: 11 }}>● Healing Active</Badge>
            : <Badge variant="success" style={{ fontSize: 11 }}>● Healthy</Badge>
        }
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to="/security"
              style={{ padding: '6px 14px', background: 'rgba(248,113,113,0.12)', border: '1px solid rgba(248,113,113,0.35)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              🛡 Security
            </Link>
            <Link to="/audit"
              style={{ padding: '6px 14px', background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              📋 Audit Log
            </Link>
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
        <DriftTable events={drift} loading={loading} baselineFiles={healStatus?.baseline_files ?? 0} />
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

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { icon: '🛡️', label: 'Security Dashboard',  desc: 'Threats, IPs, lockdown controls',  to: '/security' },
            { icon: '🔍', label: 'Audit Log',            desc: 'Full event trail with filters',    to: '/audit' },
            { icon: '🔧', label: 'Admin Panel',          desc: 'Platform overview & KPIs',         to: '/admin' },
            { icon: '⚡', label: 'Super Admin',          desc: 'Master control panel',             to: '/superadmin' },
            { icon: '🔬', label: 'System Reliability',   desc: 'OTel tracing & self-test suite',   to: '/system-reliability' },
            { icon: '🟢', label: 'System Status',        desc: 'Component health & uptime',        to: '/status' },
          ].map(({ icon, label, desc, to }) => (
            <Link
              key={to}
              to={to}
              style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
            >
              <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
            </Link>
          ))}
        </div>
      </div>
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
