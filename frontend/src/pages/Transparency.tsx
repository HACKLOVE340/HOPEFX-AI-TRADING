/**
 * Transparency — AI decision audit & explainability.
 *
 * Wires to the roadmap transparency router:
 *   GET /api/transparency/stats
 *   GET /api/transparency/decisions
 *   GET /api/transparency/audit-log
 */
import { ScanSearch } from 'lucide-react';
import { PageShell } from '../components/system/PageShell';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { transparencyApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface Stats {
  total_decisions?: number; win_rate?: number; avg_confidence?: number;
  avg_execution_ms?: number; skip_rate?: number; wins?: number; losses?: number;
}
interface Decision {
  trade_id?: string; symbol?: string; direction?: string; confidence?: number;
  outcome?: string; reasoning?: string; timestamp?: string;
}
interface AuditEntry {
  action_type?: string; actor?: string; details?: unknown; timestamp?: string;
}

const OUTCOME_COLOR: Record<string, string> = {
  win: 'var(--gain)', loss: 'var(--loss)', pending: 'var(--warn)', skipped: 'var(--text-muted)',
};

const Transparency: React.FC = () => {
  const [stats, setStats] = useState<Stats | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    setErr('');
    const [s, d, a] = await Promise.allSettled([
      transparencyApi.stats(),
      transparencyApi.decisions({ limit: 50 }),
      transparencyApi.auditLog({ limit: 50 }),
    ]);
    if (!mountedRef.current) return;
    if (s.status === 'fulfilled') setStats(s.value.data ?? null);
    if (d.status === 'fulfilled') setDecisions(d.value.data?.decisions ?? []);
    if (a.status === 'fulfilled') setAudit(a.value.data?.entries ?? []);
    if (s.status === 'rejected' && d.status === 'rejected' && a.status === 'rejected') {
      setErr(extractApiError(s.reason, 'Failed to load transparency data.'));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => { mountedRef.current = false; };
  }, [load]);

  const tiles = [
    { label: 'Decisions', value: stats?.total_decisions != null ? String(stats.total_decisions) : '—' },
    { label: 'Win rate', value: Number.isFinite(stats?.win_rate) ? `${(stats!.win_rate as number).toFixed(1)}%` : '—' },
    { label: 'Avg confidence', value: Number.isFinite(stats?.avg_confidence) ? `${((stats!.avg_confidence as number) * ((stats!.avg_confidence as number) <= 1 ? 100 : 1)).toFixed(0)}%` : '—' },
    { label: 'Avg exec', value: Number.isFinite(stats?.avg_execution_ms) ? `${(stats!.avg_execution_ms as number).toFixed(0)}ms` : '—' },
    { label: 'Skip rate', value: Number.isFinite(stats?.skip_rate) ? `${(stats!.skip_rate as number).toFixed(1)}%` : '—' },
  ];

  return (
    <PageShell
      title="Transparency"
      subtitle="Decisions the platform made, and the ones it refused."
      icon={ScanSearch}
      width="standard"
      actions={<button onClick={load} style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: 'var(--link)', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer' }}>↻ Refresh</button>}
    >

      {loading && <div style={{ color: 'var(--text-muted)', padding: 20 }}>Loading decisions…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>{err}</div>
      )}

      {!loading && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{t.value}</div>
              </div>
            ))}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-dim)', margin: '0 0 10px' }}>Recent Decisions</h2>
          <div style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 10, padding: 12, marginBottom: 20 }}>
            {decisions.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', padding: 8 }}>No decisions recorded yet.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {decisions.map((d, i) => (
                  <div key={d.trade_id ?? i} style={{ padding: '10px 12px', background: 'var(--surface)', borderRadius: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                      <span style={{ fontWeight: 700 }}>{d.symbol ?? '—'}</span>
                      <span style={{ fontSize: 'var(--fs-body)', color: d.direction === 'short' || d.direction === 'sell' ? 'var(--loss)' : 'var(--gain)', fontWeight: 600 }}>{(d.direction ?? '').toUpperCase()}</span>
                      {Number.isFinite(d.confidence) && <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)' }}>{(d.confidence! <= 1 ? d.confidence! * 100 : d.confidence!).toFixed(0)}% conf</span>}
                      {d.outcome && <span style={{ marginLeft: 'auto', fontSize: 'var(--fs-label)', fontWeight: 700, textTransform: 'uppercase', color: OUTCOME_COLOR[d.outcome.toLowerCase()] ?? 'var(--text-dim)' }}>{d.outcome}</span>}
                    </div>
                    {d.reasoning && <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)', marginTop: 4 }}>{d.reasoning}</div>}
                    {d.timestamp && <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', marginTop: 2 }}>{d.timestamp}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-dim)', margin: '0 0 10px' }}>Audit Log</h2>
          <div style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 10, padding: 12 }}>
            {audit.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', padding: 8 }}>No audit entries.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {audit.map((e, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, padding: '6px 10px', background: 'var(--surface)', borderRadius: 6, fontSize: 'var(--fs-body)'}}>
                    <span style={{ fontWeight: 600 }}>{e.action_type ?? 'event'}</span>
                    <span style={{ color: 'var(--text-faint)' }}>{e.timestamp ?? ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </PageShell>
  );
};

export default Transparency;
