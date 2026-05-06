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

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
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
  draft:     '#64748b',
  running:   '#f59e0b',
  completed: '#22c55e',
  error:     '#ef4444',
};

const DIRECTION_COLORS: Record<string, string> = {
  bullish: '#22c55e',
  bearish: '#ef4444',
  neutral: '#94a3b8',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: `${STATUS_COLORS[status] ?? '#64748b'}22`,
      color: STATUS_COLORS[status] ?? '#64748b',
      border: `1px solid ${STATUS_COLORS[status] ?? '#64748b'}44`,
      textTransform: 'uppercase',
    }}>
      {status}
    </span>
  );
}

function SignalCard({ signal }: { signal: Signal }) {
  return (
    <div style={{
      background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
      padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: 12,
    }}>
      <div style={{
        width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
        background: DIRECTION_COLORS[signal.direction] ?? '#94a3b8',
      }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{signal.type}</span>
          <span style={{ fontSize: 11, color: DIRECTION_COLORS[signal.direction] ?? '#94a3b8', fontWeight: 600 }}>
            {signal.direction.toUpperCase()}
          </span>
          <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>
            {(signal.confidence * 100).toFixed(0)}% confidence
          </span>
        </div>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>{signal.description}</p>
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
          background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px',
        }}>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4, textTransform: 'capitalize' }}>
            {key.replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            {typeof val === 'number' ? val.toFixed(2) : String(val)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Execution status bar ──────────────────────────────────────────────────────

const EXEC_STEPS = ['Initialising', 'Fetching data', 'Running analysis', 'Generating signals', 'Finalising'];

function ExecutionStatus({ notebookId, onComplete }: { notebookId: string; onComplete: (nb: Notebook) => void }) {
  const [step, setStep]       = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());
  const qc = useQueryClient();

  // Tick elapsed time
  useEffect(() => {
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  // Advance visual step every ~2s
  useEffect(() => {
    const id = setInterval(() => setStep(s => Math.min(s + 1, EXEC_STEPS.length - 1)), 2000);
    return () => clearInterval(id);
  }, []);

  // Poll notebook status every 3s until completed/error
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const res = await researchApi.getNotebook(notebookId);
        const nb = res.data as Notebook;
        if (nb.status === 'completed' || nb.status === 'error') {
          clearInterval(id);
          qc.invalidateQueries({ queryKey: ['research-notebooks'] });
          onComplete(nb);
        }
      } catch { /* ignore polling errors */ }
    }, 3000);
    return () => clearInterval(id);
  }, [notebookId, onComplete, qc]);

  const pct = ((step + 1) / EXEC_STEPS.length) * 100;

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 10, padding: '20px 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#f59e0b' }}>
          ⏳ {EXEC_STEPS[step]}…
        </div>
        <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'monospace' }}>{elapsed}s elapsed</div>
      </div>
      <div style={{ height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden', marginBottom: 12 }}>
        <div style={{
          height: '100%', borderRadius: 3,
          background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
          width: `${pct}%`, transition: 'width 1.5s ease',
        }} />
      </div>
      <div style={{ display: 'flex', gap: 0 }}>
        {EXEC_STEPS.map((s, i) => (
          <div key={s} style={{ flex: 1, textAlign: 'center' }}>
            <div style={{
              width: 10, height: 10, borderRadius: '50%', margin: '0 auto 4px',
              background: i <= step ? '#3b82f6' : '#1e293b',
              border: `2px solid ${i <= step ? '#3b82f6' : '#334155'}`,
              transition: 'background 0.4s',
            }} />
            <div style={{ fontSize: 9, color: i <= step ? '#60a5fa' : '#334155', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {s}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Rich output renderer ──────────────────────────────────────────────────────

function OutputSection({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '10px 16px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
        <span style={{ color: '#475569', fontSize: 12 }}>{open ? '▾' : '▸'}</span>
      </button>
      {open && <div style={{ padding: '0 16px 16px' }}>{children}</div>}
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
        background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
        padding: 24, width: '100%', maxWidth: 480,
      }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
          New Research Notebook
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <label style={{ fontSize: 12, color: '#94a3b8' }}>
            Title
            <input value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. XAUUSD Weekly Analysis"
              style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a', border: '1px solid #334155',
                borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, boxSizing: 'border-box' }} />
          </label>
          <label style={{ fontSize: 12, color: '#94a3b8' }}>
            Template
            <select value={template} onChange={e => setTemplate(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a', border: '1px solid #334155',
                borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              Symbol
              <select value={symbol} onChange={e => setSymbol(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a', border: '1px solid #334155',
                  borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
                {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, color: '#94a3b8' }}>
              Timeframe
              <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
                style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a', border: '1px solid #334155',
                  borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
                {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </label>
          </div>
          <label style={{ fontSize: 12, color: '#94a3b8' }}>
            Description (optional)
            <textarea value={description} onChange={e => setDesc(e.target.value)} rows={2}
              style={{ display: 'block', width: '100%', marginTop: 4, background: '#0f172a', border: '1px solid #334155',
                borderRadius: 6, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, resize: 'vertical', boxSizing: 'border-box' }} />
          </label>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button onClick={() => onCreate({ title, template, symbol, timeframe, description })}
            disabled={!title.trim() || !template || creating}
            style={{ flex: 1, padding: '9px 0', background: '#8b5cf6', color: '#fff', border: 'none',
              borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: creating ? 'not-allowed' : 'pointer',
              opacity: (!title.trim() || !template || creating) ? 0.5 : 1 }}>
            {creating ? 'Creating…' : 'Create Notebook'}
          </button>
          <button onClick={onClose}
            style={{ padding: '9px 16px', background: '#334155', color: '#94a3b8', border: 'none',
              borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const ResearchPage: React.FC = () => {
  const qc = useQueryClient();
  const [selected, setSelected]   = useState<Notebook | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [runningId, setRunningId]   = useState<string | null>(null);

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
    onSuccess: (_res, id) => {
      qc.invalidateQueries({ queryKey: ['research-notebooks'] });
      setRunningId(id);
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
    <div style={{ padding: '24px 28px', maxWidth: 1200, margin: '0 auto' }}>
      <PageHeader
        title="Research"
        subtitle="AI-powered market analysis notebooks — enterprise tier"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'Research' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link to="/geopolitical"
              style={{ padding: '7px 14px', background: 'rgba(251,191,36,0.12)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              🌍 Geopolitical
            </Link>
            <Link to="/signals"
              style={{ padding: '7px 14px', background: 'rgba(167,139,250,0.12)', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              📡 Signals
            </Link>
            <Link to="/ai-chart"
              style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', color: '#60a5fa', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 8, fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              📈 AI Charts
            </Link>
            <button onClick={() => setShowCreate(true)}
              style={{ padding: '7px 16px', background: '#8b5cf6', color: '#fff', border: 'none',
                borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
              + New Notebook
            </button>
          </div>
        }
      />

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '320px 1fr' : '1fr', gap: 20 }}>
        {/* Notebook list */}
        <div>
          {nbLoading && (
            <div style={{ color: '#64748b', fontSize: 13, padding: 20, textAlign: 'center' }}>Loading notebooks…</div>
          )}
          {!nbLoading && notebooks.length === 0 && (
            <EmptyState
              icon="🔬"
              title="No research notebooks yet"
              description="Create a notebook to run AI-powered market analysis, backtest hypotheses, and generate insights."
              action={
                <button
                  onClick={() => setShowCreate(true)}
                  style={{ padding: '8px 18px', background: '#8b5cf6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  + New Notebook
                </button>
              }
            />
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {notebooks.map(nb => (
              <div key={nb.notebook_id}
                onClick={() => setSelected(nb)}
                style={{
                  background: selected?.notebook_id === nb.notebook_id ? '#1e3a5f' : '#1e293b',
                  border: `1px solid ${selected?.notebook_id === nb.notebook_id ? '#3b82f6' : '#334155'}`,
                  borderRadius: 10, padding: '14px 16px', cursor: 'pointer',
                  transition: 'border-color 0.15s',
                }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{nb.title}</span>
                  <StatusBadge status={nb.status} />
                </div>
                <div style={{ display: 'flex', gap: 8, fontSize: 11, color: '#64748b' }}>
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
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{selected.title}</h2>
                <div style={{ display: 'flex', gap: 8, fontSize: 12, color: '#64748b' }}>
                  <span>{selected.symbol}</span><span>·</span>
                  <span>{selected.timeframe}</span><span>·</span>
                  <StatusBadge status={selected.status} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => { runMut.mutate(selected.notebook_id); }}
                  disabled={runMut.isPending || selected.status === 'running' || runningId === selected.notebook_id}
                  style={{ padding: '7px 14px', background: '#22c55e', color: '#fff', border: 'none',
                    borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                    opacity: (runMut.isPending || selected.status === 'running' || runningId === selected.notebook_id) ? 0.5 : 1 }}>
                  {(selected.status === 'running' || runningId === selected.notebook_id) ? '⏳ Running…' : '▶ Run'}
                </button>
                <button
                  onClick={() => deleteMut.mutate(selected.notebook_id)}
                  disabled={deleteMut.isPending}
                  style={{ padding: '7px 14px', background: '#ef444422', color: '#ef4444', border: '1px solid #ef444444',
                    borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>
                  Delete
                </button>
                <button onClick={() => setSelected(null)}
                  style={{ padding: '7px 10px', background: '#334155', color: '#94a3b8', border: 'none',
                    borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>
                  ✕
                </button>
              </div>
            </div>

            {selected.description && (
              <p style={{ fontSize: 13, color: '#94a3b8', marginBottom: 20 }}>{selected.description}</p>
            )}

            {/* Execution status overlay */}
            {runningId === selected.notebook_id && (
              <div style={{ marginBottom: 20 }}>
                <ExecutionStatus
                  notebookId={selected.notebook_id}
                  onComplete={(nb) => { setSelected(nb); setRunningId(null); }}
                />
              </div>
            )}

            {selected.results && runningId !== selected.notebook_id ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Generated at */}
                <div style={{ fontSize: 11, color: '#475569', textAlign: 'right' }}>
                  Generated {new Date(selected.results.generated_at).toLocaleString()}
                </div>

                {/* Summary */}
                <OutputSection label="Summary">
                  <p style={{ margin: 0, fontSize: 13, color: '#cbd5e1', lineHeight: 1.7 }}>{selected.results.summary}</p>
                </OutputSection>

                {/* Metrics */}
                {Object.keys(selected.results.metrics).length > 0 && (
                  <OutputSection label={`Metrics (${Object.keys(selected.results.metrics).length})`}>
                    <MetricsGrid metrics={selected.results.metrics} />
                  </OutputSection>
                )}

                {/* Signals */}
                {selected.results.signals.length > 0 && (
                  <OutputSection label={`Signals (${selected.results.signals.length})`}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                      <Link to="/ai-strategy"
                        style={{ padding: '4px 12px', borderRadius: 5, background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)', color: '#a78bfa', fontSize: 11, fontWeight: 700, textDecoration: 'none' }}
                        title="Use these research signals to generate a trading strategy">
                        🤖 Convert to Strategy
                      </Link>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selected.results.signals.map((s, i) => <SignalCard key={i} signal={s} />)}
                    </div>
                  </OutputSection>
                )}
              </div>
            ) : (
              !runningId && (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#64748b', fontSize: 13 }}>
                  {selected.status === 'running'
                    ? '⏳ Analysis in progress…'
                    : 'Click ▶ Run to execute this notebook'}
                </div>
              )
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

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/geopolitical" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🌍 Geopolitical</Link>
        <Link to="/correlation" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🔗 Correlation</Link>
        <Link to="/calendar" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📅 Economic Calendar</Link>
        <Link to="/signals" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📡 Signal Feed</Link>
        <Link to="/ai-chart" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📈 AI Charts</Link>
      </div>
    </div>
  );
};

export default ResearchPage;
