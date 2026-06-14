/**
 * Transparency — AI decision audit & explainability.
 *
 * Wires to the roadmap transparency router:
 *   GET /api/transparency/stats
 *   GET /api/transparency/decisions
 *   GET /api/transparency/audit-log
 */
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
  win: '#4ade80', loss: '#f87171', pending: '#fbbf24', skipped: '#64748b',
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
    { label: 'Win rate', value: stats?.win_rate != null ? `${stats.win_rate.toFixed(1)}%` : '—' },
    { label: 'Avg confidence', value: stats?.avg_confidence != null ? `${(stats.avg_confidence * (stats.avg_confidence <= 1 ? 100 : 1)).toFixed(0)}%` : '—' },
    { label: 'Avg exec', value: stats?.avg_execution_ms != null ? `${stats.avg_execution_ms.toFixed(0)}ms` : '—' },
    { label: 'Skip rate', value: stats?.skip_rate != null ? `${stats.skip_rate.toFixed(1)}%` : '—' },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: '0 auto', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>🔍 Transparency</h1>
        <button onClick={load} style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>↻ Refresh</button>
      </div>

      {loading && <div style={{ color: '#64748b', padding: 20 }}>Loading decisions…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>{err}</div>
      )}

      {!loading && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{t.value}</div>
              </div>
            ))}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Recent Decisions</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12, marginBottom: 20 }}>
            {decisions.length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No decisions recorded yet.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {decisions.map((d, i) => (
                  <div key={d.trade_id ?? i} style={{ padding: '10px 12px', background: '#0f172a', borderRadius: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                      <span style={{ fontWeight: 700 }}>{d.symbol ?? '—'}</span>
                      <span style={{ fontSize: 12, color: d.direction === 'short' || d.direction === 'sell' ? '#f87171' : '#4ade80', fontWeight: 600 }}>{(d.direction ?? '').toUpperCase()}</span>
                      {d.confidence != null && <span style={{ fontSize: 12, color: '#94a3b8' }}>{(d.confidence <= 1 ? d.confidence * 100 : d.confidence).toFixed(0)}% conf</span>}
                      {d.outcome && <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: OUTCOME_COLOR[d.outcome.toLowerCase()] ?? '#94a3b8' }}>{d.outcome}</span>}
                    </div>
                    {d.reasoning && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{d.reasoning}</div>}
                    {d.timestamp && <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{d.timestamp}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Audit Log</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12 }}>
            {audit.length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No audit entries.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {audit.map((e, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, padding: '6px 10px', background: '#0f172a', borderRadius: 6, fontSize: 12 }}>
                    <span style={{ fontWeight: 600 }}>{e.action_type ?? 'event'}</span>
                    <span style={{ color: '#475569' }}>{e.timestamp ?? ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default Transparency;
