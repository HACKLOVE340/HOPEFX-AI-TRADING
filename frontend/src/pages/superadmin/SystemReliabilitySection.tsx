// SystemReliabilitySection.tsx — Super Admin only
import React, { useState, useEffect, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { Card, SectionHeader, Button, StatusBadge } from '../settings/ui';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Component {
  name: string;
  label: string;
  status: string;
  latency_ms: number;
  detail: string;
  extra: Record<string, unknown>;
  checked_at: string;
}

interface ReliabilityStatus {
  overall: string;
  components: Component[];
  checked_at: string;
  total_components: number;
  ok_count: number;
  warning_count: number;
  error_count: number;
  probe_duration_ms: number;
}

interface SelfTestResult {
  passed: number;
  failed: number;
  total: number;
  results: Array<{ test: string; passed: boolean; status: string; detail: string; duration_ms: number }>;
  duration_ms: number;
  ran_at: string;
}

interface TraceSpan {
  trace_id: string;
  span_id: string;
  name: string;
  timestamp: string;
  duration_ms: number;
  status_code: number;
  path: string;
  method: string;
}

// ── Status colour helper ──────────────────────────────────────────────────────

function statusColor(s: string): string {
  if (s === 'ok') return '#22c55e';
  if (s === 'warning') return '#f59e0b';
  if (s === 'degraded') return '#f97316';
  return '#ef4444';
}

function statusBg(s: string): string {
  if (s === 'ok') return '#052e16';
  if (s === 'warning') return '#451a03';
  if (s === 'degraded') return '#431407';
  return '#450a0a';
}

function statusIcon(s: string): string {
  if (s === 'ok') return '✅';
  if (s === 'warning') return '⚠️';
  return '❌';
}

// ── Component card ────────────────────────────────────────────────────────────

const ComponentCard: React.FC<{
  comp: Component;
  onProbe: (name: string) => void;
  probing: boolean;
}> = ({ comp, onProbe, probing }) => (
  <div style={{
    background: statusBg(comp.status),
    border: `1px solid ${statusColor(comp.status)}33`,
    borderRadius: 10,
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ fontWeight: 700, fontSize: 13, color: '#f1f5f9' }}>
        {statusIcon(comp.status)} {comp.label}
      </span>
      <span style={{
        fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
        background: statusColor(comp.status) + '22', color: statusColor(comp.status),
        border: `1px solid ${statusColor(comp.status)}44`,
        textTransform: 'uppercase',
      }}>{comp.status}</span>
    </div>
    <div style={{ fontSize: 12, color: '#94a3b8' }}>{comp.detail}</div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
      <span style={{ fontSize: 11, color: '#64748b' }}>{comp.latency_ms}ms</span>
      <button
        onClick={() => onProbe(comp.name)}
        disabled={probing}
        style={{
          fontSize: 11, padding: '3px 10px', borderRadius: 6, border: '1px solid #334155',
          background: '#1e293b', color: '#94a3b8', cursor: probing ? 'not-allowed' : 'pointer',
        }}
      >{probing ? '…' : 'Re-probe'}</button>
    </div>
  </div>
);

// ── Trace row ─────────────────────────────────────────────────────────────────

const TraceRow: React.FC<{ span: TraceSpan }> = ({ span }) => (
  <div style={{
    display: 'grid', gridTemplateColumns: '1fr 80px 60px 80px',
    gap: 8, padding: '8px 12px', borderBottom: '1px solid #1e293b',
    fontSize: 12, color: '#94a3b8',
  }}>
    <span style={{ color: '#e2e8f0', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
      {span.name}
    </span>
    <span style={{ color: span.status_code >= 400 ? '#ef4444' : '#22c55e' }}>{span.status_code}</span>
    <span>{span.duration_ms}ms</span>
    <span style={{ color: '#475569', fontSize: 10 }}>{new Date(span.timestamp).toLocaleTimeString()}</span>
  </div>
);

// ── Diagnostics Panel ─────────────────────────────────────────────────────────

const DiagnosticsPanel: React.FC = () => {
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [report, setReport]   = useState<Record<string, unknown> | null>(null);
  const [checks, setChecks]   = useState<Array<{ name: string; description: string }>>([]);
  const [remLog, setRemLog]   = useState<Array<Record<string, unknown>>>([]);
  const [running, setRunning] = useState(false);
  const [remediating, setRemediating] = useState(false);
  const [runningCheck, setRunningCheck] = useState<string | null>(null);
  const [checkResult, setCheckResult] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg]         = useState('');
  const [tab, setTab]         = useState<'summary' | 'report' | 'checks' | 'remediation'>('summary');

  const load = useCallback(async () => {
    try {
      const [s, c, r] = await Promise.allSettled([
        superadminApi.diagnosticsSummary(),
        superadminApi.diagnosticsChecks(),
        superadminApi.diagnosticsRemediationLog(20),
      ]);
      if (s.status === 'fulfilled') setSummary(s.value.data);
      if (c.status === 'fulfilled') setChecks(c.value.data.checks ?? []);
      if (r.status === 'fulfilled') setRemLog(r.value.data.entries ?? []);
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runFull = async () => {
    setRunning(true); setMsg('');
    try {
      await superadminApi.diagnosticsRun();
      setMsg('Diagnostic run started — fetching results in 5s…');
      setTimeout(async () => {
        const res = await superadminApi.diagnosticsReport();
        setReport(res.data);
        load();
        setMsg('');
      }, 5000);
    } catch { setMsg('Failed to start diagnostic run'); }
    finally { setRunning(false); }
  };

  const remediate = async () => {
    setRemediating(true); setMsg('');
    try {
      const res = await superadminApi.diagnosticsRemediate();
      setMsg(`Remediation complete — ${res.data.actions_taken} action(s) taken`);
      load();
    } catch { setMsg('Remediation failed'); }
    finally { setRemediating(false); }
  };

  const runCheck = async (name: string) => {
    setRunningCheck(name); setCheckResult(null);
    try {
      const res = await superadminApi.diagnosticsRunCheck(name);
      setCheckResult(res.data);
    } catch { /* non-fatal */ }
    finally { setRunningCheck(null); }
  };

  const score = summary ? Number(summary.health_score ?? 0) : null;
  const scoreColor = score === null ? '#94a3b8' : score >= 90 ? '#22c55e' : score >= 70 ? '#f59e0b' : '#ef4444';

  const DTABS = [
    { id: 'summary',     label: '📊 Summary' },
    { id: 'report',      label: '📋 Report' },
    { id: 'checks',      label: '🔍 Run Check' },
    { id: 'remediation', label: '🔧 Remediation Log' },
  ] as const;

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
        <SectionHeader icon="🔬" title="Platform Diagnostics Engine" />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button onClick={runFull} disabled={running} size="sm">{running ? 'Running…' : '▶ Run All Checks'}</Button>
          <Button onClick={remediate} disabled={remediating} variant="secondary" size="sm">{remediating ? 'Remediating…' : '🔧 Auto-Remediate'}</Button>
          <Button onClick={load} variant="secondary" size="sm">↻</Button>
        </div>
      </div>

      {msg && <div style={{ padding: '8px 12px', borderRadius: 6, background: '#1e293b', color: '#94a3b8', fontSize: 13, marginBottom: 12 }}>{msg}</div>}

      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {DTABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t.id ? 700 : 500,
            background: tab === t.id ? '#1e3a5f' : '#1e293b',
            color: tab === t.id ? '#60a5fa' : '#94a3b8',
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'summary' && summary && (
        <>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
            {[
              { label: 'Health Score', value: score !== null ? `${score}%` : '—', color: scoreColor },
              { label: 'Total Checks', value: String(summary.total_checks ?? 0), color: '#94a3b8' },
              { label: 'OK', value: String((summary.counts as Record<string,number>)?.ok ?? 0), color: '#22c55e' },
              { label: 'Warnings', value: String((summary.counts as Record<string,number>)?.warning ?? 0), color: '#f59e0b' },
              { label: 'Errors', value: String((summary.counts as Record<string,number>)?.error ?? 0), color: '#ef4444' },
              { label: 'Critical', value: String((summary.counts as Record<string,number>)?.critical ?? 0), color: '#dc2626' },
              { label: 'Healer Running', value: summary.healer_running ? 'YES' : 'NO', color: summary.healer_running ? '#22c55e' : '#ef4444' },
              { label: 'Drift Events', value: String(summary.healer_drift_events ?? 0), color: '#f59e0b' },
              { label: 'Patches Applied', value: String(summary.healer_patches_applied ?? 0), color: '#60a5fa' },
            ].map(m => (
              <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 16px', textAlign: 'center', minWidth: 80 }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 10, color: '#475569', marginTop: 2, textTransform: 'uppercase' }}>{m.label}</div>
              </div>
            ))}
          </div>
          {Array.isArray(summary.top_issues) && summary.top_issues.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: 8 }}>Top Issues</div>
              {(summary.top_issues as Array<Record<string,string>>).map((issue, i) => (
                <div key={i} style={{ padding: '10px 14px', borderRadius: 8, background: '#450a0a', border: '1px solid #dc262633', marginBottom: 6 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: '#fca5a5' }}>{issue.check_name}</div>
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{issue.message}</div>
                  {issue.remediation && <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>Fix: {issue.remediation}</div>}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === 'report' && (
        <>
          {!report && <div style={{ color: '#64748b', fontSize: 13, padding: '16px 0' }}>No report loaded. Run diagnostics first.</div>}
          {report && (
            <>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>Completed: {String(report.completed_at ?? 'N/A')}</div>
              {(report.results as Array<Record<string,string>> ?? []).map((r, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '8px 12px', borderRadius: 6, marginBottom: 4,
                  background: r.status === 'ok' ? '#052e16' : r.status === 'warning' ? '#451a03' : '#450a0a',
                  border: `1px solid ${r.status === 'ok' ? '#16a34a33' : r.status === 'warning' ? '#d9770633' : '#dc262633'}`,
                }}>
                  <div>
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{r.check_name}</span>
                    <div style={{ fontSize: 12, color: '#94a3b8' }}>{r.message}</div>
                    {r.remediation && <div style={{ fontSize: 11, color: '#64748b' }}>Fix: {r.remediation}</div>}
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', flexShrink: 0, marginLeft: 12,
                    color: r.status === 'ok' ? '#22c55e' : r.status === 'warning' ? '#f59e0b' : '#ef4444' }}>
                    {r.status}
                  </span>
                </div>
              ))}
            </>
          )}
        </>
      )}

      {tab === 'checks' && (
        <>
          <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12 }}>Run a single diagnostic check and see results immediately.</div>
          {checkResult && (
            <div style={{ padding: '12px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #334155', marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#60a5fa', marginBottom: 8 }}>Result: {String(checkResult.check_name)}</div>
              {(checkResult.results as Array<Record<string,string>> ?? []).map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, color: r.status === 'ok' ? '#22c55e' : r.status === 'warning' ? '#f59e0b' : '#ef4444' }}>[{r.status}]</span>
                  {' '}{r.message}
                </div>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {checks.map(c => (
              <div key={c.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9', fontFamily: 'monospace' }}>{c.name}</div>
                  <div style={{ fontSize: 12, color: '#64748b' }}>{c.description}</div>
                </div>
                <Button onClick={() => runCheck(c.name)} disabled={runningCheck === c.name} size="sm" variant="secondary">
                  {runningCheck === c.name ? '…' : '▶ Run'}
                </Button>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === 'remediation' && (
        <>
          <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12 }}>Auto-remediation actions taken by the diagnostics engine.</div>
          {remLog.length === 0 && <div style={{ color: '#475569', fontSize: 13 }}>No remediation actions recorded yet.</div>}
          {remLog.map((entry, i) => (
            <div key={i} style={{ padding: '10px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b', marginBottom: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{String(entry.action ?? entry.type ?? 'action')}</span>
                <span style={{ fontSize: 11, color: '#475569' }}>{String(entry.timestamp ?? entry.taken_at ?? '')}</span>
              </div>
              {entry.detail != null && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{String(entry.detail)}</div>}
              {entry.check_name != null && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>Check: {String(entry.check_name)}</div>}
            </div>
          ))}
        </>
      )}
    </Card>
  );
};

// ── Routes Panel ──────────────────────────────────────────────────────────────

const RoutesPanel: React.FC = () => {
  const [routes, setRoutes] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter]   = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await superadminApi.reliabilityRoutes();
      setRoutes(res.data.routes ?? res.data ?? []);
    } catch { /* non-fatal */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = routes.filter(r =>
    !filter || String(r.path ?? '').toLowerCase().includes(filter.toLowerCase()) ||
    String(r.methods ?? '').toLowerCase().includes(filter.toLowerCase())
  );

  const methodColor = (m: string) => {
    const upper = m.toUpperCase();
    if (upper === 'GET')    return '#22c55e';
    if (upper === 'POST')   return '#3b82f6';
    if (upper === 'PUT' || upper === 'PATCH') return '#f59e0b';
    if (upper === 'DELETE') return '#ef4444';
    return '#94a3b8';
  };

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <SectionHeader icon="🗺️" title="API Route Inventory" />
        <Button onClick={load} disabled={loading} variant="secondary" size="sm">{loading ? '…' : '↻'}</Button>
      </div>
      <div style={{ marginBottom: 12 }}>
        <input
          type="text" value={filter} onChange={e => setFilter(e.target.value)}
          placeholder="Filter by path or method…"
          style={{ width: '100%', padding: '8px 12px', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, boxSizing: 'border-box' }}
        />
      </div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>{filtered.length} routes{filter ? ` matching "${filter}"` : ''}</div>
      <div style={{ maxHeight: 500, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {filtered.map((r, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', borderRadius: 6, background: '#0f172a', border: '1px solid #1e293b' }}>
            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
              {(Array.isArray(r.methods) ? r.methods : [String(r.methods ?? 'GET')]).map((m: string) => (
                <span key={m} style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: methodColor(m) + '22', color: methodColor(m), border: `1px solid ${methodColor(m)}44` }}>
                  {m}
                </span>
              ))}
            </div>
            <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#e2e8f0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {String(r.path ?? '')}
            </span>
            {r.tags != null && (
              <span style={{ fontSize: 10, color: '#475569', flexShrink: 0 }}>{String(r.tags)}</span>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
};

// ── Validate Panel ────────────────────────────────────────────────────────────

const ValidatePanel: React.FC = () => {
  const [key, setKey]           = useState('');
  const [expected, setExpected] = useState('');
  const [result, setResult]     = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading]   = useState(false);
  const [toggleKey, setToggleKey]       = useState('');
  const [toggleExpected, setToggleExpected] = useState('');
  const [toggleResult, setToggleResult] = useState<Record<string, unknown> | null>(null);
  const [toggleLoading, setToggleLoading] = useState(false);

  const validate = async () => {
    if (!key.trim()) return;
    setLoading(true); setResult(null);
    try {
      const res = await superadminApi.reliabilityValidate(key.trim());
      setResult(res.data);
    } catch { /* non-fatal */ }
    finally { setLoading(false); }
  };

  const validateToggle = async () => {
    if (!toggleKey.trim()) return;
    setToggleLoading(true); setToggleResult(null);
    try {
      let parsed: unknown = toggleExpected;
      try { parsed = JSON.parse(toggleExpected); } catch { /* keep as string */ }
      const res = await superadminApi.reliabilityValidateToggle(toggleKey.trim(), parsed);
      setToggleResult(res.data);
    } catch { /* non-fatal */ }
    finally { setToggleLoading(false); }
  };

  const layerColor = (layer: Record<string, unknown>) => {
    if (layer.error) return '#ef4444';
    if (layer.match) return '#22c55e';
    if (layer.found) return '#f59e0b';
    return '#64748b';
  };

  return (
    <>
      <Card>
        <SectionHeader icon="✅" title="Setting Persistence Validator" />
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
          Verify that a config key is correctly persisted across Redis, config store, and app state.
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>Config Key</label>
            <input type="text" value={key} onChange={e => setKey(e.target.value)} placeholder="e.g. maintenance_mode"
              style={{ width: '100%', padding: '8px 12px', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, boxSizing: 'border-box' }} />
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <Button onClick={validate} disabled={loading || !key.trim()} size="sm">{loading ? '…' : '🔍 Validate'}</Button>
          </div>
        </div>
        {result && (
          <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: '#f1f5f9' }}>Key: <code style={{ color: '#60a5fa' }}>{String(result.key)}</code></span>
              <span style={{ fontSize: 12, fontWeight: 700, color: result.consistent ? '#22c55e' : '#ef4444' }}>
                {result.consistent ? '✅ Consistent' : '❌ Inconsistent'}
              </span>
            </div>
            {Object.entries(result.layers as Record<string, Record<string, unknown>> ?? {}).map(([layer, info]) => (
              <div key={layer} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', borderRadius: 6, background: '#1e293b', marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>{layer}</span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {info.error ? (
                    <span style={{ fontSize: 11, color: '#ef4444' }}>Error: {String(info.error)}</span>
                  ) : (
                    <>
                      <span style={{ fontSize: 11, color: info.found ? '#22c55e' : '#64748b' }}>{info.found ? 'Found' : 'Not found'}</span>
                      {info.found && <span style={{ fontSize: 11, color: layerColor(info) }}>{info.match ? '✓ Match' : '✗ Mismatch'}</span>}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SectionHeader icon="🔄" title="Toggle End-to-End Validator" />
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
          After changing a toggle or setting, verify the new value is correctly persisted end-to-end.
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>Config Key</label>
            <input type="text" value={toggleKey} onChange={e => setToggleKey(e.target.value)} placeholder="e.g. maintenance_mode"
              style={{ width: '100%', padding: '8px 12px', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, boxSizing: 'border-box' }} />
          </div>
          <div style={{ flex: 1, minWidth: 120 }}>
            <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>Expected Value</label>
            <input type="text" value={toggleExpected} onChange={e => setToggleExpected(e.target.value)} placeholder="true / false / 42"
              style={{ width: '100%', padding: '8px 12px', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 13, boxSizing: 'border-box' }} />
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <Button onClick={validateToggle} disabled={toggleLoading || !toggleKey.trim()} size="sm">{toggleLoading ? '…' : '✅ Verify'}</Button>
          </div>
        </div>
        {toggleResult && (
          <div style={{ background: '#0f172a', border: `1px solid ${toggleResult.consistent ? '#16a34a' : '#dc2626'}44`, borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ fontWeight: 700, fontSize: 13, color: toggleResult.consistent ? '#22c55e' : '#ef4444', marginBottom: 8 }}>
              {toggleResult.consistent ? '✅ Value persisted correctly across all layers' : '❌ Inconsistency detected — value may not have saved'}
            </div>
            {Object.entries(toggleResult.layers as Record<string, Record<string, unknown>> ?? {}).map(([layer, info]) => (
              <div key={layer} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 10px', borderRadius: 6, background: '#1e293b', marginBottom: 4 }}>
                <span style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>{layer}</span>
                <span style={{ fontSize: 11, color: info.match ? '#22c55e' : info.error ? '#ef4444' : '#f59e0b' }}>
                  {info.error ? `Error: ${String(info.error)}` : info.match ? `✓ ${JSON.stringify(info.value)}` : `✗ got ${JSON.stringify(info.value)}`}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const SystemReliabilitySection: React.FC = () => {
  const [status, setStatus] = useState<ReliabilityStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [probingComp, setProbingComp] = useState<string | null>(null);
  const [selfTest, setSelfTest] = useState<SelfTestResult | null>(null);
  const [selfTestRunning, setSelfTestRunning] = useState(false);
  const [traces, setTraces] = useState<TraceSpan[]>([]);
  const [tracesLoading, setTracesLoading] = useState(false);
  const [traceTestRunning, setTraceTestRunning] = useState(false);
  const [traceTestResult, setTraceTestResult] = useState<Record<string, unknown> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [envAudit, setEnvAudit] = useState<Record<string, unknown> | null>(null);
  const [activeTab, setActiveTab] = useState<'components' | 'traces' | 'selftest' | 'env' | 'metrics' | 'diagnostics' | 'routes' | 'validate'>('components');
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await superadminApi.reliabilityStatus();
      setStatus(res.data);
      setLastRefresh(new Date().toLocaleTimeString());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch reliability status');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTraces = useCallback(async () => {
    setTracesLoading(true);
    try {
      const res = await superadminApi.reliabilityTraces(50);
      setTraces(res.data.spans || []);
    } catch {
      // non-fatal
    } finally {
      setTracesLoading(false);
    }
  }, []);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await superadminApi.reliabilityMetrics();
      setMetrics(res.data);
    } catch {
      // non-fatal
    }
  }, []);

  const fetchEnv = useCallback(async () => {
    try {
      const res = await superadminApi.reliabilityEnv();
      setEnvAudit(res.data);
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchTraces();
    fetchMetrics();
    fetchEnv();
    const interval = setInterval(() => {
      fetchStatus();
      fetchTraces();
      fetchMetrics();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus, fetchTraces, fetchMetrics]);

  const handleProbe = async (component: string) => {
    setProbingComp(component);
    try {
      const res = await superadminApi.reliabilityProbe(component);
      setStatus((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          components: prev.components.map((c) =>
            c.name === component
              ? { ...c, status: res.data.status, latency_ms: res.data.latency_ms, detail: res.data.detail }
              : c
          ),
        };
      });
    } catch {
      // non-fatal
    } finally {
      setProbingComp(null);
    }
  };

  const handleSelfTest = async () => {
    setSelfTestRunning(true);
    setSelfTest(null);
    try {
      const res = await superadminApi.reliabilitySelfTest();
      setSelfTest(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Self-test failed');
    } finally {
      setSelfTestRunning(false);
    }
  };

  const handleTraceTest = async () => {
    setTraceTestRunning(true);
    setTraceTestResult(null);
    try {
      const res = await superadminApi.reliabilityTraceTest();
      setTraceTestResult(res.data);
      await fetchTraces();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Trace test failed');
    } finally {
      setTraceTestRunning(false);
    }
  };

  const TABS = [
    { id: 'components',  label: '🔌 Components' },
    { id: 'traces',      label: '🔍 Traces' },
    { id: 'selftest',    label: '🧪 Self-Test' },
    { id: 'diagnostics', label: '🔬 Diagnostics' },
    { id: 'routes',      label: '🗺️ Routes' },
    { id: 'validate',    label: '✅ Validate' },
    { id: 'env',         label: '🌍 Env Audit' },
    { id: 'metrics',     label: '📊 Metrics' },
  ] as const;

  const overall = status?.overall ?? 'unknown';

  return (
    <div style={{ color: '#f1f5f9', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Header */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <SectionHeader icon="🔬" title="System Reliability Dashboard" />
            <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
              Real-time connectivity status for every platform component. Auto-refreshes every 30s.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {lastRefresh && <span style={{ fontSize: 11, color: '#475569' }}>Last: {lastRefresh}</span>}
            <div style={{
              padding: '6px 16px', borderRadius: 8, fontWeight: 700, fontSize: 13,
              background: statusBg(overall), color: statusColor(overall),
              border: `1px solid ${statusColor(overall)}44`,
            }}>
              {statusIcon(overall)} {overall.toUpperCase()}
            </div>
            <Button onClick={fetchStatus} disabled={loading} variant="secondary">
              {loading ? 'Refreshing…' : '↻ Refresh'}
            </Button>
          </div>
        </div>

        {/* Summary counters */}
        {status && (
          <div style={{ display: 'flex', gap: 16, marginTop: 16, flexWrap: 'wrap' }}>
            {[
              { label: 'Total', value: status.total_components, color: '#94a3b8' },
              { label: 'Healthy', value: status.ok_count, color: '#22c55e' },
              { label: 'Warning', value: status.warning_count, color: '#f59e0b' },
              { label: 'Error', value: status.error_count, color: '#ef4444' },
              { label: 'Probe Time', value: `${status.probe_duration_ms}ms`, color: '#60a5fa' },
            ].map((m) => (
              <div key={m.label} style={{
                background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
                padding: '10px 16px', textAlign: 'center', minWidth: 80,
              }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{m.label}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {error && (
        <div style={{ background: '#450a0a', border: '1px solid #dc2626', borderRadius: 8, padding: '10px 16px', marginBottom: 12, fontSize: 13, color: '#fca5a5' }}>
          ❌ {error}
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding: '7px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
            fontSize: 12, fontWeight: activeTab === t.id ? 700 : 500,
            background: activeTab === t.id ? '#1e3a5f' : '#1e293b',
            color: activeTab === t.id ? '#60a5fa' : '#94a3b8',
          }}>{t.label}</button>
        ))}
      </div>

      {/* Components tab */}
      {activeTab === 'components' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {loading && !status && (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#64748b', padding: 32 }}>
              Loading component status…
            </div>
          )}
          {status?.components.map((comp) => (
            <ComponentCard
              key={comp.name}
              comp={comp}
              onProbe={handleProbe}
              probing={probingComp === comp.name}
            />
          ))}
        </div>
      )}

      {/* Traces tab */}
      {activeTab === 'traces' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <SectionHeader icon="🔍" title="Recent OTel Spans" />
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={handleTraceTest} disabled={traceTestRunning} variant="secondary">
                {traceTestRunning ? 'Emitting…' : '⚡ Emit Test Trace'}
              </Button>
              <Button onClick={fetchTraces} disabled={tracesLoading} variant="secondary">
                {tracesLoading ? '…' : '↻'}
              </Button>
            </div>
          </div>
          {traceTestResult && (
            <div style={{ background: '#052e16', border: '1px solid #16a34a', borderRadius: 8, padding: '10px 14px', marginBottom: 12, fontSize: 12 }}>
              ✅ Test trace emitted — trace_id: <code style={{ color: '#86efac' }}>{String(traceTestResult.trace_id)}</code>
              {' | '}DB: <strong>{String((traceTestResult.probes as Record<string,string>)?.database)}</strong>
              {' | '}Redis: <strong>{String((traceTestResult.probes as Record<string,string>)?.redis)}</strong>
              {' | '}Broker: <strong>{String((traceTestResult.probes as Record<string,string>)?.broker)}</strong>
            </div>
          )}
          <div style={{ background: '#0f172a', borderRadius: 8, overflow: 'hidden', border: '1px solid #1e293b' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 80px 60px 80px',
              gap: 8, padding: '8px 12px', borderBottom: '1px solid #334155',
              fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
            }}>
              <span>Span Name</span><span>Status</span><span>Duration</span><span>Time</span>
            </div>
            {traces.length === 0 && (
              <div style={{ padding: '24px', textAlign: 'center', color: '#475569', fontSize: 13 }}>
                No spans recorded yet. Emit a test trace or make API calls.
              </div>
            )}
            {traces.map((span, i) => <TraceRow key={i} span={span} />)}
          </div>
        </Card>
      )}

      {/* Self-test tab */}
      {activeTab === 'selftest' && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <SectionHeader icon="🧪" title="End-to-End Self-Test Suite" />
            <Button onClick={handleSelfTest} disabled={selfTestRunning}>
              {selfTestRunning ? 'Running tests…' : '▶ Run All Tests'}
            </Button>
          </div>
          {selfTest && (
            <>
              <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
                {[
                  { label: 'Passed', value: selfTest.passed, color: '#22c55e' },
                  { label: 'Failed', value: selfTest.failed, color: '#ef4444' },
                  { label: 'Total', value: selfTest.total, color: '#94a3b8' },
                  { label: 'Duration', value: `${selfTest.duration_ms}ms`, color: '#60a5fa' },
                ].map((m) => (
                  <div key={m.label} style={{
                    background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
                    padding: '10px 16px', textAlign: 'center',
                  }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: m.color }}>{m.value}</div>
                    <div style={{ fontSize: 11, color: '#475569' }}>{m.label}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {selfTest.results.map((r) => (
                  <div key={r.test} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 14px', borderRadius: 8,
                    background: r.passed ? '#052e16' : '#450a0a',
                    border: `1px solid ${r.passed ? '#16a34a' : '#dc2626'}33`,
                  }}>
                    <div>
                      <span style={{ fontWeight: 600, fontSize: 13, color: '#f1f5f9' }}>
                        {r.passed ? '✅' : '❌'} {r.test}
                      </span>
                      <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{r.detail}</div>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                      <div style={{ fontSize: 11, color: statusColor(r.status), fontWeight: 700 }}>{r.status}</div>
                      <div style={{ fontSize: 11, color: '#475569' }}>{r.duration_ms}ms</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
          {!selfTest && !selfTestRunning && (
            <div style={{ textAlign: 'center', color: '#475569', padding: '32px 0', fontSize: 13 }}>
              Click "Run All Tests" to execute the full end-to-end connectivity suite.
            </div>
          )}
        </Card>
      )}

      {/* Env audit tab */}
      {activeTab === 'env' && (
        <Card>
          <SectionHeader icon="🌍" title="Environment Variable Audit" />
          <p style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
            Shows presence/absence of environment variables. Values are never exposed.
          </p>
          {envAudit && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {Object.entries(envAudit.groups as Record<string, Record<string, { set: boolean; required: boolean }>>).map(([group, vars]) => (
                <div key={group}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
                    {group}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {Object.entries(vars).map(([key, info]) => (
                      <div key={key} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '8px 12px', borderRadius: 6,
                        background: info.set ? '#052e16' : (info.required ? '#450a0a' : '#1e293b'),
                        border: `1px solid ${info.set ? '#16a34a33' : (info.required ? '#dc262633' : '#334155')}`,
                      }}>
                        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#e2e8f0' }}>{key}</span>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          {info.required && (
                            <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: '#1e3a5f', color: '#60a5fa' }}>REQUIRED</span>
                          )}
                          <span style={{ fontSize: 12, fontWeight: 700, color: info.set ? '#22c55e' : '#ef4444' }}>
                            {info.set ? '✓ SET' : '✗ MISSING'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Diagnostics tab */}
      {activeTab === 'diagnostics' && (
        <DiagnosticsPanel />
      )}

      {/* Routes tab */}
      {activeTab === 'routes' && (
        <RoutesPanel />
      )}

      {/* Validate tab */}
      {activeTab === 'validate' && (
        <ValidatePanel />
      )}

      {/* Metrics tab */}
      {activeTab === 'metrics' && (
        <Card>
          <SectionHeader icon="📊" title="System Metrics" />
          {metrics && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginTop: 12 }}>
              {Object.entries(metrics.system as Record<string, number> ?? {}).map(([key, val]) => (
                <div key={key} style={{
                  background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 16px',
                }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: '#60a5fa' }}>
                    {typeof val === 'number' ? (key.includes('pct') ? `${val}%` : val) : String(val)}
                  </div>
                  <div style={{ fontSize: 11, color: '#475569', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {key.replace(/_/g, ' ')}
                  </div>
                </div>
              ))}
              {Object.entries(metrics.redis as Record<string, number> ?? {}).map(([key, val]) => (
                <div key={`redis_${key}`} style={{
                  background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 16px',
                }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: '#a78bfa' }}>
                    {typeof val === 'number' ? val.toLocaleString() : String(val)}
                  </div>
                  <div style={{ fontSize: 11, color: '#475569', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Redis: {key.replace(/_/g, ' ')}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 16 }}>
            <Button onClick={fetchMetrics} variant="secondary">↻ Refresh Metrics</Button>
          </div>
        </Card>
      )}
    </div>
  );
};

export default SystemReliabilitySection;
