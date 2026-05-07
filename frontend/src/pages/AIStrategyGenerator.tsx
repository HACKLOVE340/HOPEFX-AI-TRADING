/**
 * AI Strategy Generator — plain-English prompt → generated strategy code
 * → auto-backtest → deploy to paper trading.
 *
 * Wires to: POST /api/brain/generate-strategy
 *           POST /api/brain/deploy-strategy
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, CrossLinkBar } from '../components';
import { useStore } from '../store';
import { aiStrategyApi, llmApi } from '../hooks/useApi';
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

const fmt = (n: number, decimals = 2) => n.toFixed(decimals);
const pct = (n: number) => `${n >= 0 ? '+' : ''}${fmt(n)}%`;

// ── Component ─────────────────────────────────────────────────────────────────

// ── Streaming token display ───────────────────────────────────────────────────

const StreamingOutput: React.FC<{ tokens: string; done: boolean }> = ({ tokens, done }) => {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [tokens]);

  return (
    <div style={{ background: '#0a0f1a', border: '1px solid #1e2d3d', borderRadius: 8, padding: '12px 14px', fontFamily: 'monospace', fontSize: 12, color: '#94a3b8', maxHeight: 200, overflowY: 'auto', lineHeight: 1.6 }}>
      <span style={{ color: '#4ade80' }}>{tokens}</span>
      {!done && <span style={{ animation: 'pulse 1s infinite', color: '#3b82f6' }}>▋</span>}
      <div ref={endRef} />
    </div>
  );
};

// ── Strategy diff viewer ──────────────────────────────────────────────────────

const StrategyDiff: React.FC<{ oldCode: string; newCode: string }> = ({ oldCode, newCode }) => {
  const oldLines = oldCode.split('\n');
  const newLines = newCode.split('\n');
  const maxLen   = Math.max(oldLines.length, newLines.length);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontFamily: 'monospace', fontSize: 11 }}>
      <div>
        <div style={{ fontSize: 10, color: '#f87171', marginBottom: 4, fontWeight: 700 }}>− Previous</div>
        <div style={{ background: '#0a0f1a', border: '1px solid #1e2d3d', borderRadius: 6, padding: '8px 10px', maxHeight: 200, overflowY: 'auto' }}>
          {oldLines.map((line, i) => {
            const changed = line !== (newLines[i] ?? '');
            return (
              <div key={i} style={{ color: changed ? '#f87171' : '#475569', background: changed ? 'rgba(248,113,113,0.08)' : 'transparent', padding: '0 2px' }}>
                {line || ' '}
              </div>
            );
          })}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 10, color: '#4ade80', marginBottom: 4, fontWeight: 700 }}>+ New</div>
        <div style={{ background: '#0a0f1a', border: '1px solid #1e2d3d', borderRadius: 6, padding: '8px 10px', maxHeight: 200, overflowY: 'auto' }}>
          {newLines.map((line, i) => {
            const changed = line !== (oldLines[i] ?? '');
            return (
              <div key={i} style={{ color: changed ? '#4ade80' : '#475569', background: changed ? 'rgba(74,222,128,0.08)' : 'transparent', padding: '0 2px' }}>
                {line || ' '}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const AIStrategyGenerator: React.FC = () => {
  const toast = useToast();

  const [prompt, setPrompt]         = useState('');
  const [symbol, setSymbol]         = useState('XAU_USD');
  const [timeframe, setTimeframe]   = useState('H1');
  const [stage, setStage]           = useState<Stage>('idle');
  const [result, setResult]         = useState<GenerateResponse | null>(null);
  const [prevCode, setPrevCode]     = useState<string>('');
  const [showDiff, setShowDiff]     = useState(false);
  const [streamTokens, setStreamTokens] = useState('');
  const [streamDone, setStreamDone] = useState(false);
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
        const d = res.data as { status?: string; backend?: string };
        setLlmStatus(d?.status === 'ok' ? 'ok' : 'unavailable');
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
    setStreamTokens('');
    setStreamDone(false);
    setShowDiff(false);

    // Try streaming endpoint first, fall back to regular
    try {
      const streamUrl = `/api/brain/generate-strategy/stream`;
      const token = useStore.getState().token;
      const resp = await fetch(streamUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ prompt, symbol, timeframe }),
      });

      if (resp.ok && resp.headers.get('content-type')?.includes('text/event-stream')) {
        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let accumulated = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          // SSE format: "data: <token>\n\n"
          for (const line of chunk.split('\n')) {
            if (line.startsWith('data: ')) {
              const payload = line.slice(6);
              if (payload === '[DONE]') { setStreamDone(true); break; }
              try {
                const parsed = JSON.parse(payload) as { token?: string; result?: GenerateResponse };
                if (parsed.token) { accumulated += parsed.token; setStreamTokens(accumulated); }
                if (parsed.result) {
                  const d = parsed.result;
                  if (result?.strategy_code) setPrevCode(result.strategy_code);
                  setResult(d);
                  setStage(d.success ? 'done' : 'error');
                  setStreamDone(true);
                  if (d.success) { loadHistory(); toast.success('Strategy generated.'); }
                }
              } catch { accumulated += payload; setStreamTokens(accumulated); }
            }
          }
        }
        return;
      }
    } catch { /* fall through to regular */ }

    // Regular (non-streaming) fallback
    try {
      const res = await aiStrategyApi.generate({ prompt, symbol, timeframe });
      const d = res.data as GenerateResponse;
      if (result?.strategy_code) setPrevCode(result.strategy_code);
      setResult(d);
      setStage(d.success ? 'done' : 'error');
      setStreamDone(true);
      if (d.success) { loadHistory(); toast.success('Strategy generated.'); }
    } catch (err: unknown) {
      setResult({ success: false, strategy_name: '', strategy_code: '', backtest: null, iterations: 0, error: (err as { message?: string })?.message ?? 'Unknown error' });
      setStage('error');
      setStreamDone(true);
    }
  };

  const handleDeploy = async () => {
    if (!result?.strategy_code) return;
    setDeploying(true);
    setDeployMsg('');
    try {
      await aiStrategyApi.deploy({ strategy_name: result.strategy_name, strategy_code: result.strategy_code, symbol, mode: 'paper' });
      setDeployMsg('Strategy deployed to paper trading.');
      toast.success(`"${result.strategy_name}" deployed to paper trading.`);
      loadHistory();
    } catch (err: unknown) {
      const msg = `Deploy failed: ${err instanceof Error ? err.message : 'Unknown error'}`;
      setDeployMsg(msg);
      toast.error(msg);
    } finally {
      setDeploying(false);
    }
  };

  const handleDeleteStrategy = async (strategyId: string) => {
    try {
      await aiStrategyApi.deleteStrategy(strategyId);
      setHistory(prev => prev.filter(s => s.strategy_id !== strategyId));
    } catch { /* non-fatal */ }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
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
      <PageHeader
        title="AI Strategy Generator"
        icon="🤖"
        subtitle="Describe your trading idea in plain English. The AI generates strategy code, runs a backtest, and deploys to paper trading."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'AI Strategy' },
        ]}
        actions={
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
            <Link to="/ai-chart"         style={{ padding: '6px 12px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>📈 AI Charts</Link>
            <Link to="/pattern-detector" style={{ padding: '6px 12px', background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.35)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>🔍 Patterns</Link>
            <Link to="/walk-forward"     style={{ padding: '6px 12px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>📊 Walk-Forward</Link>
            <Link to="/ab-testing"       style={{ padding: '6px 12px', background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.35)', borderRadius: 7, color: '#34d399', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>⚡ A/B Test</Link>
          </div>
        }
      />

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
                    <span style={{ fontSize: 11, color: str.backtest.total_return_pct >= 0 ? '#4ade80' : '#f87171' }}>
                      {str.backtest.total_return_pct >= 0 ? '+' : ''}{str.backtest.total_return_pct.toFixed(1)}% return
                    </span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>Sharpe {str.backtest.sharpe_ratio.toFixed(2)}</span>
                    <span style={{ fontSize: 11, color: '#94a3b8' }}>WR {str.backtest.win_rate.toFixed(0)}%</span>
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
          {stage === 'generating' ? '⏳ Generating…' : '✨ Generate Strategy'}
        </button>
      </div>

      {/* Streaming output while generating */}
      {stage === 'generating' && streamTokens && (
        <div style={s.card}>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>Generating strategy…</div>
          <StreamingOutput tokens={streamTokens} done={streamDone} />
        </div>
      )}

      {/* Results */}
      {result && (
        <div style={s.card}>
          {result.success ? (
            <>
              <div style={s.resultHeader}>
                <span style={s.strategyName}>{result.strategy_name}</span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={s.badge}>✓ Generated in {result.iterations} iteration{result.iterations !== 1 ? 's' : ''}</span>
                  {prevCode && prevCode !== result.strategy_code && (
                    <button
                      onClick={() => setShowDiff((v) => !v)}
                      style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 6, color: '#fbbf24', fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '3px 10px' }}
                    >
                      {showDiff ? 'Hide Diff' : '⟷ Show Diff'}
                    </button>
                  )}
                </div>
              </div>

              {/* Strategy diff viewer */}
              {showDiff && prevCode && (
                <div style={{ marginBottom: 16 }}>
                  <StrategyDiff oldCode={prevCode} newCode={result.strategy_code} />
                </div>
              )}

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
                <Link
                  to="/walk-forward"
                  style={{
                    background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)',
                    borderRadius: 8, color: '#a78bfa', fontSize: 13, fontWeight: 600,
                    padding: '9px 16px', textDecoration: 'none', display: 'inline-block',
                  }}
                  title="Validate this strategy with walk-forward testing"
                >
                  📈 Walk-Forward Validate
                </Link>
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

      <CrossLinkBar title="Related" style={{ marginTop: 24 }} links={[
        { label: '📈 AI Charts',        href: '/ai-chart',         color: '#60a5fa' },
        { label: '🔍 Pattern Detector', href: '/pattern-detector', color: '#a78bfa' },
        { label: '📊 Walk-Forward',     href: '/walk-forward',     color: '#34d399' },
        { label: '⚗️ A/B Testing',     href: '/ab-testing',       color: '#fbbf24' },
        { label: '📐 Indicators',       href: '/indicators',       color: '#f97316' },
        { label: '🛒 Marketplace',      href: '/marketplace',      color: '#4ade80' },
      ]}/>
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
