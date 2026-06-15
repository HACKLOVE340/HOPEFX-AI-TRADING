/**
 * Strategy Builder — no-code strategy creation from templates.
 *
 * Wires to the roadmap no-code router (template-driven):
 *   GET  /api/nocode/templates
 *   GET  /api/nocode/node-types
 *   POST /api/nocode/deploy   { template_id, parameters, symbol, timeframe }
 *
 * Pick a template, tune its parameters + symbol/timeframe, and deploy it as a
 * live dynamic strategy. The node-type catalogue is shown for reference.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { nocodeApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface Template {
  id: string; name: string; category?: string; description?: string;
  complexity?: string; parameters?: Record<string, number | string | boolean>;
}
interface NodeType { id: string; name: string; params?: string[] }

const SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'ETHUSD'];
const TIMEFRAMES = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1'];
const COMPLEXITY_COLOR: Record<string, string> = { beginner: '#4ade80', intermediate: '#fbbf24', advanced: '#f87171' };

const StrategyBuilder: React.FC = () => {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [nodeTypes, setNodeTypes] = useState<Record<string, NodeType[]>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const [selected, setSelected] = useState<Template | null>(null);
  const [params, setParams] = useState<Record<string, number | string | boolean>>({});
  const [symbol, setSymbol] = useState('XAUUSD');
  const [timeframe, setTimeframe] = useState('M15');
  const [deploying, setDeploying] = useState(false);
  const [deployMsg, setDeployMsg] = useState('');
  const [showCatalog, setShowCatalog] = useState(false);
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    setErr('');
    const [t, n] = await Promise.allSettled([nocodeApi.templates(), nocodeApi.nodeTypes()]);
    if (!mountedRef.current) return;
    if (t.status === 'fulfilled') setTemplates(t.value.data?.templates ?? []);
    else setErr(extractApiError(t.reason, 'Failed to load strategy templates.'));
    if (n.status === 'fulfilled') setNodeTypes(n.value.data?.node_types ?? {});
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => { mountedRef.current = false; };
  }, [load]);

  const pick = (t: Template) => {
    setSelected(t);
    setParams({ ...(t.parameters ?? {}) });
    setDeployMsg('');
  };

  const deploy = async () => {
    if (!selected) return;
    setDeploying(true); setDeployMsg('');
    try {
      const r = await nocodeApi.deploy({ template_id: selected.id, parameters: params, symbol, timeframe });
      setDeployMsg(r.data?.message ?? `Deployed ${r.data?.strategy_name ?? selected.name}.`);
    } catch (e) {
      setDeployMsg(extractApiError(e, 'Deployment failed.'));
    } finally {
      if (mountedRef.current) setDeploying(false);
    }
  };

  const labelStyle: React.CSSProperties = { fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 4 };
  const inputStyle: React.CSSProperties = { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, boxSizing: 'border-box' };

  return (
    <div style={{ padding: 20, maxWidth: 1100, margin: '0 auto', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>🧩 Strategy Builder</h1>
        <button onClick={() => setShowCatalog((v) => !v)} style={{ padding: '6px 14px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
          {showCatalog ? 'Hide' : 'Show'} node catalogue
        </button>
      </div>

      {loading && <div style={{ color: '#64748b', padding: 20 }}>Loading templates…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>{err}</div>
      )}

      {showCatalog && (
        <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 14, marginBottom: 20 }}>
          {Object.entries(nodeTypes).map(([group, items]) => (
            <div key={group} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{group.replace(/_/g, ' ')}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {items.map((it) => (
                  <span key={it.id} title={(it.params ?? []).join(', ')} style={{ fontSize: 12, padding: '3px 9px', background: '#0f172a', border: '1px solid #334155', borderRadius: 6 }}>{it.name}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 280px), 1fr))', gap: 12, marginBottom: 20 }}>
          {templates.length === 0 && !err && (
            <div style={{ color: '#64748b' }}>No templates available.</div>
          )}
          {templates.map((t) => (
            <button key={t.id} onClick={() => pick(t)} style={{ textAlign: 'left', cursor: 'pointer', background: selected?.id === t.id ? '#1c2438' : '#1e293b', border: `1px solid ${selected?.id === t.id ? '#3b82f6' : '#334155'}`, borderRadius: 10, padding: '14px 16px', color: 'inherit' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontWeight: 700 }}>{t.name}</span>
                {t.complexity && <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', color: COMPLEXITY_COLOR[t.complexity] ?? '#94a3b8' }}>{t.complexity}</span>}
              </div>
              {t.category && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{t.category}</div>}
              {t.description && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>{t.description}</div>}
            </button>
          ))}
        </div>
      )}

      {/* Configure & deploy the selected template */}
      {selected && (
        <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 20 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 14px' }}>Configure “{selected.name}”</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 14 }}>
            <label>
              <span style={labelStyle}>Symbol</span>
              <select value={symbol} onChange={(e) => setSymbol(e.target.value)} style={inputStyle}>
                {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label>
              <span style={labelStyle}>Timeframe</span>
              <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} style={inputStyle}>
                {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </label>
            {Object.entries(params).map(([key, val]) => (
              <label key={key}>
                <span style={labelStyle}>{key.replace(/_/g, ' ')}</span>
                <input
                  value={String(val)}
                  type={typeof val === 'number' ? 'number' : 'text'}
                  step="any"
                  onChange={(e) => setParams((p) => ({ ...p, [key]: typeof val === 'number' ? Number(e.target.value) : e.target.value }))}
                  style={inputStyle}
                />
              </label>
            ))}
          </div>

          {deployMsg && (
            <div style={{ padding: '10px 14px', background: '#0c1a2e', border: '1px solid #1e3a5f', borderRadius: 8, color: '#60a5fa', marginBottom: 12, fontSize: 13 }}>{deployMsg}</div>
          )}

          <button onClick={deploy} disabled={deploying} style={{ padding: '10px 20px', background: deploying ? '#1e3a5f' : '#2563eb', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 700, cursor: deploying ? 'default' : 'pointer' }}>
            {deploying ? 'Deploying…' : '🚀 Deploy Strategy'}
          </button>
        </div>
      )}
    </div>
  );
};

export default StrategyBuilder;
