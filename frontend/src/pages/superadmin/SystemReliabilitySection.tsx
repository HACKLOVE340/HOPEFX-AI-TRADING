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
  const [activeTab, setActiveTab] = useState<'components' | 'traces' | 'selftest' | 'env' | 'metrics'>('components');
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
    { id: 'components', label: '🔌 Components' },
    { id: 'traces',     label: '🔍 Traces' },
    { id: 'selftest',   label: '🧪 Self-Test' },
    { id: 'env',        label: '🌍 Env Audit' },
    { id: 'metrics',    label: '📊 Metrics' },
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
