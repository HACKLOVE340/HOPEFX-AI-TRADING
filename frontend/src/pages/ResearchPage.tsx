/**
 * Research page — AI-powered market research notebooks.
 *
 * Wires to:
 *   GET  /api/research/notebooks        — list notebooks
 *   POST /api/research/notebooks        — create notebook
 *   GET  /api/research/notebooks/{id}   — get notebook
 *   POST /api/research/notebooks/{id}/run — execute notebook
 *   GET  /api/research/templates        — available templates
 *
 * Requires: enterprise plan
 */

import { PageShell } from '../components/system/PageShell';
import React, { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { RelatedPages } from '../components';
import {
  Sparkles, FlaskConical, Cpu, LineChart,
  Microscope,
} from 'lucide-react';
import { researchApi } from '../hooks/useApi';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Notebook {
  notebook_id: string;
  title: string;
  description: string;
  status: 'draft' | 'running' | 'completed' | 'error';
  template: string;
  symbol: string;
  timeframe: string;
  created_at: string;
  updated_at: string;
  results?: NotebookResults;
}

interface NotebookResults {
  summary: string;
  signals: Signal[];
  charts: ChartData[];
  metrics: Record<string, number>;
  generated_at: string;
}

interface Signal {
  type: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  description: string;
}

interface ChartData {
  title: string;
  type: string;
  data: unknown;
}

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  required_inputs: string[];
}

// researchApi is imported from hooks/useApi

// ── Sub-components ────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  draft:     'var(--text-muted)',
  running:   '#f59e0b',
  completed: '#22c55e',
  error:     '#ef4444',
};

const DIRECTION_COLORS: Record<string, string> = {
  bullish: '#22c55e',
  bearish: '#ef4444',
  neutral: 'var(--text-dim)',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: `${STATUS_COLORS[status] ?? 'var(--text-muted)'}22`,
      color: STATUS_COLORS[status] ?? 'var(--text-muted)',
      border: `1px solid ${STATUS_COLORS[status] ?? 'var(--text-muted)'}44`,
      textTransform: 'uppercase',
    }}>
      {status}
    </span>
  );
}

function SignalCard({ signal }: { signal: Signal }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
      padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: 12,
    }}>
      <div style={{
        width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
        background: DIRECTION_COLORS[signal.direction] ?? 'var(--text-dim)',
      }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text)' }}>{signal.type}</span>
          <span style={{ fontSize: 11, color: DIRECTION_COLORS[signal.direction] ?? 'var(--text-dim)', fontWeight: 600 }}>
            {signal.direction.toUpperCase()}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
            {Number.isFinite(signal.confidence) ? (signal.confidence * 100).toFixed(0) : '—'}% confidence
          </span>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-dim)', margin: 0 }}>{signal.description}</p>
      </div>
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (!entries.length) return null;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
      {entries.map(([key, val]) => (
        <div key={key} style={{
          background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'capitalize' }}>
            {key.replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
            {typeof val === 'number' ? (Number.isFinite(val) ? val.toFixed(2) : '—') : val}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Create notebook modal ─────────────────────────────────────────────────────

interface CreateModalProps {
  templates: Template[];
  onClose: () => void;
  onCreate: (data: { title: string; template: string; symbol: string; timeframe: string; description: string }) => void;
  creating: boolean;
}

function CreateModal({ templates, onClose, onCreate, creating }: CreateModalProps) {
  const [title, setTitle]         = useState('');
  const [template, setTemplate]   = useState(templates[0]?.id ?? '');
  const [symbol, setSymbol]       = useState('XAUUSD');
  const [timeframe, setTimeframe] = useState('H1');
  const [description, setDesc]    = useState('');

  const TIMEFRAMES = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1'];
  const SYMBOLS    = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'ETHUSD', 'US30', 'NAS100'];

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }}>
      <div style={{
        background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 12,
        padding: 24, width: '100%', maxWidth: 480,
      }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
          New Research Notebook
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Title
            <input value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. XAUUSD Weekly Analysis"
              style={{ display: 'block', width: '100%', marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border-strong)',
                borderRadius: 6, padding: '8px 10px', color: 'var(--text)', fontSize: 'var(--fs-body)', boxSizing: 'border-box' }} />
          </label>
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Template
            <select value={template} onChange={e => setTemplate(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border-strong)',
                borderRadius: 6, padding: '8px 10px', color: 'var(--text)', fontSize: 'var(--fs-body)'}}>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              Symbol
              <select value={symbol} onChange={e => setSymbol(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border-strong)',
                  borderRadius: 6, padding: '8px 10px', color: 'var(--text)', fontSize: 'var(--fs-body)'}}>
                {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              Timeframe
              <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border-strong)',
                  borderRadius: 6, padding: '8px 10px', color: 'var(--text)', fontSize: 'var(--fs-body)'}}>
                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </label>
          </div>
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Description (optional)
            <textarea value={description} onChange={e => setDesc(e.target.value)} rows={2}
              style={{ display: 'block', width: '100%', marginTop: 4, background: 'var(--surface)', border: '1px solid var(--border-strong)',
                borderRadius: 6, padding: '8px 10px', color: 'var(--text)', fontSize: 'var(--fs-body)', resize: 'vertical', boxSizing: 'border-box' }} />
          </label>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button onClick={() => onCreate({ title, template, symbol, timeframe, description })}
            disabled={!title.trim() || !template || creating}
            style={{ flex: 1, padding: '9px 0', background: '#8b5cf6', color: '#fff', border: 'none',
              borderRadius: 6, fontSize: 'var(--fs-body)', fontWeight: 600, cursor: creating ? 'not-allowed' : 'pointer',
              opacity: (!title.trim() || !template || creating) ? 0.5 : 1 }}>
            {creating ? 'Creating…' : 'Create Notebook'}
          </button>
          <button onClick={onClose}
            style={{ padding: '9px 16px', background: 'var(--surface-hover)', color: 'var(--text-dim)', border: 'none',
              borderRadius: 6, fontSize: 'var(--fs-body)', cursor: 'pointer' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const ResearchPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [selected, setSelected]   = useState<Notebook | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data: nbData, isLoading: nbLoading } = useQuery({
    queryKey: ['research-notebooks'],
    queryFn: () => researchApi.listNotebooks().then(r => r.data as { notebooks: Notebook[]; total: number }),
    refetchInterval: 10_000,
  });

  const { data: tplData } = useQuery({
    queryKey: ['research-templates'],
    queryFn: () => researchApi.getTemplates().then(r => r.data as { templates: Template[] }),
  });

  const createMut = useMutation({
    mutationFn: (body: { title: string; template: string; symbol: string; timeframe: string; description: string }) =>
      researchApi.createNotebook(body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['research-notebooks'] }); setShowCreate(false); },
  });

  const runMut = useMutation({
    mutationFn: (id: string) => researchApi.runNotebook(id),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['research-notebooks'] });
      setSelected(res.data as Notebook);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => researchApi.deleteNotebook(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['research-notebooks'] }); setSelected(null); },
  });

  const notebooks = nbData?.notebooks ?? [];
  const templates = tplData?.templates ?? [];

  const handleCreate = useCallback((data: { title: string; template: string; symbol: string; timeframe: string; description: string }) => {
    createMut.mutate(data);
  }, [createMut]);

  return (
    <PageShell
      width="wide" title="Research"
      subtitle="AI-powered market analysis notebooks — enterprise tier"
      actions={<><button onClick={() => setShowCreate(true)}
          style={{ padding: '9px 18px', background: '#8b5cf6', color: '#fff', border: 'none',
            borderRadius: 8, fontSize: 'var(--fs-body)', fontWeight: 600, cursor: 'pointer' }}>
          + New Notebook
        </button></>}
    >
      {/* Header */}


      <div style={{ display: 'grid', gridTemplateColumns: selected ? '320px 1fr' : '1fr', gap: 20 }}>
        {/* Notebook list */}
        <div>
          {nbLoading && (
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--fs-body)', padding: 20, textAlign: 'center' }}>Loading notebooks…</div>
          )}
          {!nbLoading && notebooks.length === 0 && (
            <div style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 12,
              padding: 40, textAlign: 'center' }}>
              <Microscope size={30} strokeWidth={1.5} aria-hidden style={{ marginBottom: 12, color: 'var(--text-faint)' }} />
              <div style={{ fontSize: 14, color: 'var(--text-dim)', marginBottom: 8 }}>No research notebooks yet</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>Create one to start AI-powered market analysis</div>
              <button onClick={() => navigate('/ai-strategy')}
                style={{ padding: '7px 18px', background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.4)', borderRadius: 8, color: 'var(--gain)', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer' }}>
                🤖 AI Strategy
              </button>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {notebooks.map(nb => (
              <div key={nb.notebook_id}
                onClick={() => setSelected(nb)}
                style={{
                  background: selected?.notebook_id === nb.notebook_id ? '#1e3a5f' : 'var(--raised)',
                  border: `1px solid ${selected?.notebook_id === nb.notebook_id ? '#3b82f6' : '#334155'}`,
                  borderRadius: 10, padding: '14px 16px', cursor: 'pointer',
                  transition: 'border-color 0.15s',
                }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text)' }}>{nb.title}</span>
                  <StatusBadge status={nb.status} />
                </div>
                <div style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>{nb.symbol}</span>
                  <span>·</span>
                  <span>{nb.timeframe}</span>
                  <span>·</span>
                  <span>{nb.template}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Notebook detail */}
        {selected && (
          <div style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 12, padding: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>{selected.title}</h2>
                <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                  <span>{selected.symbol}</span><span>·</span>
                  <span>{selected.timeframe}</span><span>·</span>
                  <StatusBadge status={selected.status} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => runMut.mutate(selected.notebook_id)}
                  disabled={runMut.isPending || selected.status === 'running'}
                  style={{ padding: '7px 14px', background: '#22c55e', color: '#fff', border: 'none',
                    borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                    opacity: (runMut.isPending || selected.status === 'running') ? 0.5 : 1 }}>
                  {selected.status === 'running' ? '⏳ Running…' : '▶ Run'}
                </button>
                <button
                  onClick={() => deleteMut.mutate(selected.notebook_id)}
                  disabled={deleteMut.isPending}
                  style={{ padding: '7px 14px', background: '#ef444422', color: '#ef4444', border: '1px solid #ef444444',
                    borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>
                  Delete
                </button>
                <button onClick={() => setSelected(null)}
                  style={{ padding: '7px 10px', background: 'var(--surface-hover)', color: 'var(--text-dim)', border: 'none',
                    borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>
                  ✕
                </button>
              </div>
            </div>

            {selected.description && (
              <p style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)', marginBottom: 20 }}>{selected.description}</p>
            )}

            {selected.results ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                {/* Summary */}
                <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Summary
                  </div>
                  <p style={{ margin: 0, fontSize: 'var(--fs-body)', color: 'var(--text-dim)', lineHeight: 1.6 }}>{selected.results.summary}</p>
                </div>

                {/* Metrics */}
                {Object.keys(selected.results.metrics).length > 0 && (
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Metrics
                    </div>
                    <MetricsGrid metrics={selected.results.metrics} />
                  </div>
                )}

                {/* Signals */}
                {selected.results.signals.length > 0 && (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Signals ({selected.results.signals.length})
                      </div>
                      <button
                        onClick={() => navigate('/ai-strategy', { state: { signals: selected.results?.signals ?? [], source: 'research', title: selected.title } })}
                        style={{
                          padding: '4px 12px', borderRadius: 5, cursor: 'pointer',
                          background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)',
                          color: 'var(--ai-model)', fontSize: 11, fontWeight: 700, fontFamily: 'inherit',
                        }}
                        title="Use these research signals to generate a trading strategy"
                      >
                        <Cpu size={14} strokeWidth={2} aria-hidden /> Convert to strategy
                      </button>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selected.results.signals.map((s, i) => <SignalCard key={i} signal={s} />)}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: 11, color: 'var(--text-faint)', textAlign: 'right' }}>
                  Generated {new Date(selected.results.generated_at).toLocaleString()}
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: 'var(--fs-body)'}}>
                {selected.status === 'running'
                  ? '⏳ Analysis in progress…'
                  : 'Click ▶ Run to execute this notebook'}
              </div>
            )}
          </div>
        )}
      </div>

      {showCreate && (
        <CreateModal
          templates={templates}
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
          creating={createMut.isPending}
        />
      )}
      <RelatedPages
        links={[
          { to: '/intelligence', label: 'AI intelligence', hint: 'Model health and attribution', icon: Sparkles },
          { to: '/backtest', label: 'Backtest', hint: 'Test a research idea', icon: FlaskConical },
          { to: '/ai-strategy', label: 'AI strategy', hint: 'Turn research into a strategy', icon: Cpu },
          { to: '/correlation', label: 'Correlation', hint: 'Cross-asset relationships', icon: LineChart },
        ]}
      />

    </PageShell>
  );
};

export default ResearchPage;
