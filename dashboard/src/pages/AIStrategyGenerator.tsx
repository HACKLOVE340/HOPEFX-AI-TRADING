/**
 * AI Strategy Generator — plain-English prompt → generated strategy code
 * → auto-backtest → deploy to paper trading.
 *
 * Wires to: POST /api/brain/generate-strategy
 *           POST /api/brain/deploy-strategy
 */

import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import { extractApiError } from '../lib/utils';

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

const AIStrategyGenerator: React.FC = () => {
  const token = useStore((s) => s.token);

  const [prompt, setPrompt]         = useState('');
  const [symbol, setSymbol]         = useState('XAU_USD');
  const [timeframe, setTimeframe]   = useState('H1');
  const [stage, setStage]           = useState<Stage>('idle');
  const [result, setResult]         = useState<GenerateResponse | null>(null);
  const [deploying, setDeploying]   = useState(false);
  const [deployMsg, setDeployMsg]   = useState('');

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setStage('generating');
    setResult(null);
    setDeployMsg('');

    try {
      const res = await fetch('/api/brain/generate-strategy', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ prompt, symbol, timeframe }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GenerateResponse = await res.json();
      setResult(data);
      setStage(data.success ? 'done' : 'error');
    } catch (err: unknown) {
      setResult({
        success: false,
        strategy_name: '',
        strategy_code: '',
        backtest: null,
        iterations: 0,
        error: extractApiError(err, 'Unknown error'),
      });
      setStage('error');
    }
  };

  const handleDeploy = async () => {
    if (!result?.strategy_code) return;
    setDeploying(true);
    setDeployMsg('');

    try {
      const res = await fetch('/api/brain/deploy-strategy', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          strategy_name: result.strategy_name,
          strategy_code: result.strategy_code,
          symbol,
          mode: 'paper',
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDeployMsg('Strategy deployed to paper trading.');
    } catch (err: unknown) {
      setDeployMsg(`Deploy failed: ${extractApiError(err, 'Unknown error')}`);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>AI Strategy Generator</h1>
        <p style={s.subtitle}>
          Describe your trading idea in plain English. The AI generates Python strategy code,
          runs a backtest, and lets you deploy it to paper trading in one click.
        </p>
      </div>

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

              {/* Generated code */}
              <details style={s.codeDetails}>
                <summary style={s.codeSummary}>View generated Python code</summary>
                <pre style={s.code}>{result.strategy_code}</pre>
              </details>

              {/* Deploy button */}
              <div style={s.deployRow}>
                <button
                  onClick={handleDeploy}
                  disabled={deploying}
                  style={{ ...s.deployBtn, opacity: deploying ? 0.5 : 1 }}
                >
                  {deploying ? '⏳ Deploying…' : '🚀 Deploy to Paper Trading'}
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
  header:        { marginBottom: 24 },
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
};

export default AIStrategyGenerator;
