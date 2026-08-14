/**
 * ML-Ops Dashboard — continuous-learning pipeline status & controls.
 *
 * Wires to the roadmap MLOps router:
 *   GET  /api/mlops/health
 *   GET  /api/mlops/shadow
 *   GET  /api/mlops/retrain/history
 *   POST /api/mlops/retrain
 *   POST /api/mlops/promote/{id}
 * Admin/ops surface — gated at the route level.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { mlOpsApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface Health {
  running?: boolean; retraining_state?: string; can_retrain?: boolean;
  drift_history_count?: number; latest_drift?: { score?: number; drift_type?: string; is_drifted?: boolean } | null;
  shadow_models?: Record<string, unknown>;
}

const MLDashboard: React.FC = () => {
  const [health, setHealth] = useState<Health | null>(null);
  const [shadows, setShadows] = useState<Record<string, Record<string, unknown>>>({});
  const [history, setHistory] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [failedParts, setFailedParts] = useState<string[]>([]);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    setErr('');
    const [h, s, r] = await Promise.allSettled([mlOpsApi.health(), mlOpsApi.shadow(), mlOpsApi.retrainHistory()]);
    if (!mountedRef.current) return;

    // Each request is reported on its own. The banner used to require all three
    // to reject, so a dead health endpoint with shadow and history up produced
    // no banner at all — `health` stayed null and every health-derived tile
    // rendered a dash or "Stable" as though that were the answer.
    const failed: string[] = [];
    let firstReason: unknown = null;

    if (h.status === 'fulfilled') {
      setHealth(h.value.data ?? null);
    } else {
      // Clear rather than keep: stale values under a live-looking tile are the
      // thing to avoid. A dash is honest, the last known state is not.
      setHealth(null);
      failed.push('pipeline health');
      firstReason ??= h.reason;
    }

    if (s.status === 'fulfilled') {
      setShadows(s.value.data?.shadows ?? {});
    } else {
      setShadows({});
      failed.push('shadow deployments');
      firstReason ??= s.reason;
    }

    if (r.status === 'fulfilled') {
      setHistory(r.value.data?.history ?? []);
    } else {
      setHistory([]);
      failed.push('retrain history');
      firstReason ??= r.reason;
    }

    setFailedParts(failed);
    // Headline stays the server's message (or the stable fallback); the detail
    // line below names which parts are affected. Keeping them separate avoids
    // repeating the part list when the server had nothing to say.
    setErr(failed.length ? extractApiError(firstReason, 'Failed to load ML-Ops data.') : '');
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => { mountedRef.current = false; };
  }, [load]);

  const retrain = async () => {
    setBusy('retrain'); setMsg('');
    try {
      const r = await mlOpsApi.triggerRetrain('manual (dashboard)');
      setMsg(r.data?.message ?? 'Retrain triggered.');
      await load();
    } catch (e) { setMsg(extractApiError(e, 'Retrain failed.')); }
    finally { if (mountedRef.current) setBusy(''); }
  };

  const promote = async (versionId: string) => {
    setBusy(`promote:${versionId}`); setMsg('');
    try {
      const r = await mlOpsApi.promote(versionId);
      setMsg(r.data?.message ?? 'Model promoted.');
      await load();
    } catch (e) { setMsg(extractApiError(e, 'Promotion failed.')); }
    finally { if (mountedRef.current) setBusy(''); }
  };

  /**
   * "Stable" has to be earned.
   *
   * This read `health?.latest_drift?.is_drifted ? '⚠️ Drifted' : 'Stable'`,
   * which reports Stable in two states where nothing is known:
   *
   *   - the request failed, so `health` is null and `?.` short-circuits — the
   *     page tells an operator drift is stable while unable to reach the
   *     pipeline at all;
   *   - the pipeline replied honestly with `drift_history_count: 0,
   *     latest_drift: null` (its current live state — no drift check has ever
   *     run) and the absence was rendered as a clean result.
   *
   * Absence of a drift signal is not absence of drift. Same failure the
   * inference engine's drift guard was just fixed for, on the surface an
   * operator actually reads.
   */
  const driftValue = (): string => {
    if (!health) return '—';
    if (health.latest_drift?.is_drifted) return '⚠️ Drifted';
    if (!health.drift_history_count) return 'No checks yet';
    return 'Stable';
  };

  const tiles = [
    { label: 'Pipeline', value: health?.running == null ? '—' : health.running ? 'Running' : 'Stopped' },
    { label: 'Retrain state', value: health?.retraining_state ?? '—' },
    { label: 'Drift checks', value: health?.drift_history_count != null ? String(health.drift_history_count) : '—' },
    { label: 'Drift', value: driftValue() },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 1100, margin: '0 auto', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>🤖 ML-Ops</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={load} style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>↻ Refresh</button>
          <button onClick={retrain} disabled={busy === 'retrain' || health?.can_retrain === false}
            style={{ padding: '6px 14px', background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.4)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 700, cursor: busy === 'retrain' ? 'default' : 'pointer', opacity: health?.can_retrain === false ? 0.5 : 1 }}>
            {busy === 'retrain' ? 'Retraining…' : 'Trigger Retrain'}
          </button>
        </div>
      </div>

      {msg && <div style={{ padding: '10px 14px', background: '#0c1a2e', border: '1px solid #1e3a5f', borderRadius: 8, color: '#60a5fa', marginBottom: 16 }}>{msg}</div>}
      {loading && <div style={{ color: '#64748b', padding: 20 }}>Loading pipeline…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>
          <div style={{ fontWeight: 700, marginBottom: failedParts.length ? 4 : 0 }}>{err}</div>
          {/* Name the parts. A partial outage used to render no banner at all,
              and the tiles it fed simply went blank with no explanation. */}
          {failedParts.length > 0 && (
            <div style={{ fontSize: 12, opacity: 0.85 }}>
              Could not load: {failedParts.join(', ')}. Tiles below show “—” for anything unavailable.
            </div>
          )}
        </div>
      )}

      {!loading && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{t.value}</div>
              </div>
            ))}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Shadow Models</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12, marginBottom: 20 }}>
            {Object.keys(shadows).length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No shadow deployments.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {Object.entries(shadows).map(([id]) => (
                  <div key={id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, padding: '8px 10px', background: '#0f172a', borderRadius: 8 }}>
                    <span style={{ fontWeight: 600, fontFamily: 'monospace', fontSize: 12 }}>{id}</span>
                    <button onClick={() => promote(id)} disabled={busy === `promote:${id}`}
                      style={{ padding: '4px 12px', background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.4)', borderRadius: 6, color: '#4ade80', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}>
                      {busy === `promote:${id}` ? 'Promoting…' : 'Promote'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', margin: '0 0 10px' }}>Retrain / Promotion History</h2>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 12 }}>
            {history.length === 0 ? (
              <div style={{ color: '#64748b', padding: 8 }}>No retrain history yet.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {history.map((h, i) => (
                  <div key={i} style={{ padding: '6px 10px', background: '#0f172a', borderRadius: 6, fontSize: 12, fontFamily: 'monospace', color: '#94a3b8', wordBreak: 'break-all' }}>
                    {typeof h === 'string' ? h : JSON.stringify(h)}
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

export default MLDashboard;
