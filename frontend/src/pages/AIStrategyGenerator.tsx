/**
 * AI Strategy Generator — plain-English prompt → generated strategy code
 * → auto-backtest → deploy to paper trading.
 *
 * Wires to: POST /api/brain/generate-strategy
 *           POST /api/brain/deploy-strategy
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { RelatedPages } from '../components';
import {
  Sparkles, Brain, Radar, ScanSearch, FlaskConical, Cpu, LineChart, Loader2,
  Microscope, BarChart3, BookOpen, Activity,
} from 'lucide-react';
import { useStore } from '../store';
import { aiStrategyApi, llmApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

// ── Types ─────────────────────────────────────────────────────────────────────

interface BacktestResult {
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate: number;
  total_trades: number;
}

interface GenerateResponse {
  success: boolean;
  strategy_name: string;
  strategy_code: string;
  backtest: BacktestResult | null;
  iterations: number;
  error?: string;
}

type Stage = 'idle' | 'generating' | 'done' | 'error';

interface StrategyRecord {
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  timeframe: string;
  created_at: string;
  status: string;
  backtest?: BacktestResult | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const EXAMPLE_PROMPTS = [
  'Buy gold when RSI drops below 30 and DXY is falling. Exit when RSI crosses above 60.',
  'Trend-following strategy: enter long when 20 EMA crosses above 50 EMA on H1. Use 1.5% stop loss.',
  'Mean-reversion: sell when price is 2 standard deviations above the 20-period Bollinger Band.',
  'Momentum strategy: buy when MACD histogram turns positive and volume is above 20-period average.',
];

const fmt = (n: number, decimals = 2) => (Number.isFinite(n) ? n.toFixed(decimals) : '—');
const pct = (n: number) => (Number.isFinite(n) ? `${n >= 0 ? '+' : ''}${n.toFixed(2)}%` : '—');

// ── Component ─────────────────────────────────────────────────────────────────

const AIStrategyGenerator: React.FC = () => {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const toast = useToast();

  const [prompt, setPrompt]         = useState('');
  const [symbol, setSymbol]         = useState('XAU_USD');
  const [timeframe, setTimeframe]   = useState('H1');
  const [stage, setStage]           = useState<Stage>('idle');
  const [result, setResult]         = useState<GenerateResponse | null>(null);
  const [deploying, setDeploying]   = useState(false);
  const [deployMsg, setDeployMsg]   = useState('');
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [copied, setCopied]         = useState(false);
  const [history, setHistory]       = useState<StrategyRecord[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const [activeTab, setActiveTab]   = useState<'generate' | 'history'>('generate');
  const [llmStatus, setLlmStatus]   = useState<'checking' | 'ok' | 'unavailable'>('checking');
  const [llmBackend, setLlmBackend] = useState<string>('');

  // Pre-flight LLM health check — shows a clear banner when no LLM is configured
  // instead of letting the user wait 3 minutes for a timeout.
  useEffect(() => {
    llmApi.health()
      .then((res) => {
        // GET /brain/health returns { available, backend, model, detail } — there
        // is no `status` field, so the old `status === 'ok'` check was always
        // false and the page was permanently stuck on "AI not configured".
        const d = res.data as { available?: boolean; backend?: string };
        setLlmStatus(d?.available === true ? 'ok' : 'unavailable');
        setLlmBackend(d?.backend ?? '');
      })
      .catch(() => setLlmStatus('unavailable'));
  }, []);

  const loadHistory = useCallback(async () => {
    setHistLoading(true);
    try {
      const res = await aiStrategyApi.history({ limit: 20 });
      const d = res.data as { strategies?: StrategyRecord[] } | StrategyRecord[];
      setHistory(Array.isArray(d) ? d : (d.strategies ?? []));
    } catch { setHistory([]); }
    finally { setHistLoading(false); }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setStage('generating');
    setResult(null);
    setDeployMsg('');

    try {
      const res = await aiStrategyApi.generate({ prompt, symbol, timeframe });
      const d = res.data as GenerateResponse;
      setResult(d);
      setStage(d.success ? 'done' : 'error');
      if (d.success) loadHistory();
    } catch (err: unknown) {
      setResult({
        success: false,
        strategy_name: '',
        strategy_code: '',
        backtest: null,
        iterations: 0,
        error: (err as { message?: string })?.message ?? 'Unknown error',
      });
      setStage('error');
    }
  };

  const handleDeploy = async () => {
    if (!result?.strategy_code) return;
    setDeploying(true);
    setDeployMsg('');

    try {
      await aiStrategyApi.deploy({
        strategy_name: result.strategy_name,
        strategy_code: result.strategy_code,
        symbol,
        mode: 'paper',
      });
      setDeployMsg('Strategy deployed to paper trading.');
      loadHistory();
    } catch (err: unknown) {
      setDeployMsg(`Deploy failed: ${extractApiError(err, 'Unknown error')}`);
    } finally {
      setDeploying(false);
    }
  };

  const handleDeleteStrategy = async (strategyId: string) => {
    const ok = await confirm({
      title: 'Delete strategy?',
      description: 'This permanently removes the strategy and cannot be undone.',
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;
    try {
      await aiStrategyApi.deleteStrategy(strategyId);
      setHistory(prev => prev.filter(s => s.strategy_id !== strategyId));
      toast.success('Strategy deleted.');
    } catch (e) {
      toast.error(extractApiError(e, 'Failed to delete strategy.'));
    }
  };

  return (
    <div className="page-content">
      {/* LLM health banner — shown while checking and when unavailable */}
      {llmStatus === 'checking' && (
        <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '10px 16px', marginBottom: 16, fontSize: 13, color: '#94a3b8' }}>
          Checking AI backend availability…
        </div>
      )}
      {llmStatus === 'unavailable' && (
        <div style={{ background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#fca5a5' }}>
          <strong>AI backend not configured.</strong> Set <code>ANTHROPIC_API_KEY</code> or <code>OPENAI_API_KEY</code> in your <code>.env</code> file to enable strategy generation.
          Strategy generation will return an error until an LLM backend is available.
        </div>
      )}
      {llmStatus === 'ok' && llmBackend && (
        <div style={{ background: '#052e16', border: '1px solid #166534', borderRadius: 8, padding: '8px 16px', marginBottom: 16, fontSize: 12, color: '#86efac' }}>
          AI backend: <strong>{llmBackend}</strong> — ready
        </div>
      )}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>AI Strategy Generator</h1>
          <p style={s.subtitle}>
            Describe your trading idea in plain English. The AI generates Python strategy code,
            runs a backtest, and lets you deploy it to paper trading in one click.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {(['generate', 'history'] as const).map(t => (
            <button key={t} onClick={() => setActiveTab(t)} style={{
              ...s.tabBtn,
              ...(activeTab === t ? s.tabBtnActive : {}),
            }}>
              {t === 'generate' ? '✨ Generate' : `📋 History (${history.length})`}
            </button>
          ))}
          <div style={{ width: 1, height: 20, background: '#334155' }} />
          <button onClick={() => navigate('/pattern-detector')}
            style={{ padding: '6px 13px', background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.35)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🔍 Patterns
          </button>
          <button onClick={() => navigate('/ab-testing')}
            style={{ padding: '6px 13px', background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.35)', borderRadius: 7, color: '#34d399', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            ⚡ A/B Test
          </button>
        </div>
      </div>

      {/* ── History tab ── */}
      {activeTab === 'history' && (
        <div style={s.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>Strategy History</h3>
            <button onClick={loadHistory} disabled={histLoading} style={{ ...s.btn, width: 'auto', padding: '6px 14px', fontSize: 13 }}>
              {histLoading ? '⟳' : '↻'} Refresh
            </button>
          </div>
          {histLoading && <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>}
          {!histLoading && history.length === 0 && (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 }}>
              No strategies generated yet. Use the Generate tab to create your first strategy.
            </div>
          )}
          {history.map(str => (
            <div key={str.strategy_id} style={{ ...s.histRow }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, color: '#f1f5f9', fontSize: 14 }}>{str.strategy_name}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {str.symbol} · {str.timeframe} · {new Date(str.created_at).toLocaleDateString()}
                </div>
                {str.backtest && (
                  <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
                    <span style={{ fontSize: 11, color: (str.backtest.total_return_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                      {pct(str.backtest.total_return_pct)} return
                    </span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>Sharpe {fmt(str.backtest.sharpe_ratio)}</span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>WR {fmt(str.backtest.win_rate, 0)}%</span>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  background: str.status === 'active' ? '#14532d' : '#1e293b',
                  color: str.status === 'active' ? '#4ade80' : '#64748b',
                }}>
                  {str.status}
                </span>
                <button onClick={() => handleDeleteStrategy(str.strategy_id)} style={s.delBtn}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Generate tab ── */}
      {activeTab === 'generate' && (
      <>
      {/* Input panel */}
      <div style={s.card}>
        <div style={s.row}>
          <div style={{ flex: 1 }}>
            <label style={s.label}>Symbol</label>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)} style={s.select}>
              <option value="XAU_USD">XAUUSD (Gold)</option>
              <option value="EUR_USD">EURUSD</option>
              <option value="GBP_USD">GBPUSD</option>
              <option value="USD_JPY">USDJPY</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label style={s.label}>Timeframe</label>
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} style={s.select}>
              <option value="M15">M15</option>
              <option value="H1">H1</option>
              <option value="H4">H4</option>
              <option value="D">Daily</option>
            </select>
          </div>
        </div>

        <label style={s.label}>Describe your strategy</label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Buy gold when RSI drops below 30 and DXY is falling..."
          style={s.textarea}
          rows={4}
        />

        {/* Example prompts */}
        <div style={s.examples}>
          <span style={s.examplesLabel}>Examples:</span>
          {EXAMPLE_PROMPTS.map((ex, i) => (
            <button key={i} onClick={() => setPrompt(ex)} style={s.exampleBtn}>
              {ex.slice(0, 55)}…
            </button>
          ))}
        </div>

        <button
          onClick={handleGenerate}
          disabled={!prompt.trim() || stage === 'generating'}
          style={{
            ...s.btn,
            opacity: !prompt.trim() || stage === 'generating' ? 0.5 : 1,
          }}
        >
          {stage === 'generating'
              ? <><Loader2 size={14} strokeWidth={2} aria-hidden className="animate-spin" /> Generating…</>
              : <><Sparkles size={14} strokeWidth={2} aria-hidden /> Generate strategy</>}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div style={s.card}>
          {result.success ? (
            <>
              <div style={s.resultHeader}>
                <span style={s.strategyName}>{result.strategy_name}</span>
                <span style={s.badge}>✓ Generated in {result.iterations} iteration{result.iterations !== 1 ? 's' : ''}</span>
              </div>

              {/* Backtest metrics */}
              {result.backtest && (
                <div style={s.metricsGrid}>
                  <MetricCard label="Total Return" value={pct(result.backtest.total_return_pct)} positive={result.backtest.total_return_pct >= 0} />
                  <MetricCard label="Sharpe Ratio" value={fmt(result.backtest.sharpe_ratio)} positive={result.backtest.sharpe_ratio >= 1} />
                  <MetricCard label="Max Drawdown" value={pct(result.backtest.max_drawdown_pct)} positive={false} />
                  <MetricCard label="Win Rate" value={`${fmt(result.backtest.win_rate)}%`} positive={result.backtest.win_rate >= 50} />
                  <MetricCard label="Total Trades" value={String(result.backtest.total_trades)} positive={result.backtest.total_trades > 0} />
                </div>
              )}

              {/* Generated code — collapsible with copy button */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <button
                    onClick={() => setCodeExpanded(v => !v)}
                    style={{ background: 'transparent', border: 'none', color: '#60a5fa', fontSize: 13, cursor: 'pointer', padding: 0, fontFamily: 'inherit', fontWeight: 600 }}
                  >
                    {codeExpanded ? '▼ Hide Python code' : '▶ Show generated Python code'}
                  </button>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(result.strategy_code ?? '').then(() => {
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      }).catch(() => {});
                    }}
                    style={{
                      background: copied ? 'rgba(34,197,94,0.1)' : 'rgba(59,130,246,0.1)',
                      border: `1px solid ${copied ? '#22c55e40' : '#3b82f640'}`,
                      borderRadius: 5, color: copied ? '#22c55e' : '#60a5fa',
                      fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '3px 10px',
                      fontFamily: 'inherit', transition: 'all 0.2s',
                    }}
                  >
                    {copied ? '✓ Copied!' : '⎘ Copy'}
                  </button>
                </div>
                {codeExpanded && (
                  <pre style={s.code}>{result.strategy_code}</pre>
                )}
              </div>

              {/* Deploy button + Walk-Forward link */}
              <div style={s.deployRow}>
                <button
                  onClick={handleDeploy}
                  disabled={deploying}
                  style={{ ...s.deployBtn, opacity: deploying ? 0.5 : 1 }}
                >
                  {deploying ? '⏳ Deploying…' : '🚀 Deploy to Paper Trading'}
                </button>
                <button
                  onClick={() => navigate('/walk-forward')}
                  style={{
                    background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)',
                    borderRadius: 8, color: '#a78bfa', fontSize: 13, fontWeight: 600,
                    cursor: 'pointer', padding: '9px 16px', fontFamily: 'inherit',
                  }}
                  title="Validate this strategy with walk-forward testing"
                >
                  📈 Walk-Forward Validate
                </button>
                {deployMsg && (
                  <span style={{ color: deployMsg.startsWith('Deploy failed') ? '#f87171' : '#4ade80', fontSize: 14 }}>
                    {deployMsg}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div style={s.errorBox}>
              <strong>Generation failed</strong>
              <p style={{ margin: '8px 0 0', color: '#94a3b8' }}>{result.error}</p>
            </div>
          )}
        </div>
      )}
      </>
      )}
    <RelatedPages
      links={[
        { to: '/backtest', label: 'Backtest', hint: 'Test the generated strategy', icon: FlaskConical },
        { to: '/intelligence', label: 'AI intelligence', hint: 'What the live model knows', icon: Sparkles },
        { to: '/ab-testing', label: 'A/B testing', hint: 'Run two strategies side by side', icon: Activity },
        { to: '/signals', label: 'Signal feed', hint: 'Signals the engine is publishing', icon: Radar },
        { to: '/walk-forward', label: 'Walk-forward', hint: 'Validate out of sample', icon: LineChart },
      ]}
    />
    </div>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

const MetricCard: React.FC<{ label: string; value: string; positive: boolean }> = ({ label, value, positive }) => (
  <div style={s.metricCard}>
    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, color: positive ? '#4ade80' : '#f87171' }}>{value}</div>

  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: '24px', maxWidth: 900, margin: '0 auto' },
  header:        { marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 8px' },
  subtitle:      { fontSize: 14, color: '#64748b', margin: 0 },
  card:          { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24, marginBottom: 20 },
  row:           { display: 'flex', gap: 16, marginBottom: 16 },
  label:         { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6, fontWeight: 500 },
  select:        { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14 },
  textarea:      { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '10px 12px', fontSize: 14, resize: 'vertical', boxSizing: 'border-box', fontFamily: 'inherit' },
  examples:      { display: 'flex', flexDirection: 'column', gap: 6, margin: '12px 0 16px' },
  examplesLabel: { fontSize: 12, color: '#475569', marginBottom: 4 },
  exampleBtn:    { background: 'transparent', border: '1px solid #334155', borderRadius: 6, color: '#64748b', fontSize: 12, cursor: 'pointer', padding: '6px 10px', textAlign: 'left' },
  btn:           { background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 15, fontWeight: 600, cursor: 'pointer', padding: '12px 24px', width: '100%' },
  resultHeader:  { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 },
  strategyName:  { fontSize: 18, fontWeight: 700, color: '#f1f5f9' },
  badge:         { background: '#166534', color: '#4ade80', fontSize: 12, padding: '3px 10px', borderRadius: 20 },
  metricsGrid:   { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12, marginBottom: 20 },
  metricCard:    { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, padding: '12px 16px' },
  codeDetails:   { marginBottom: 20 },
  codeSummary:   { cursor: 'pointer', color: '#60a5fa', fontSize: 14, padding: '8px 0' },
  code:          { background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, padding: 16, fontSize: 12, color: '#94a3b8', overflowX: 'auto', marginTop: 8 },
  deployRow:     { display: 'flex', alignItems: 'center', gap: 16 },
  deployBtn:     { background: '#059669', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '10px 20px' },
  errorBox:      { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: 16, color: '#f87171' },
  tabBtn:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 16px' },
  tabBtnActive:  { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  histRow:       { display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 0', borderBottom: '1px solid #1e293b' },
  delBtn:        { background: 'transparent', border: '1px solid #7f1d1d', borderRadius: 6, color: '#f87171', cursor: 'pointer', fontSize: 12, padding: '4px 10px' },
};

export default AIStrategyGenerator;
