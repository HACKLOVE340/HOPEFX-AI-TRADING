/**
 * Strategy A/B Testing (Task 42)
 * Run two strategies in parallel on paper, auto-select winner.
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface ABResult {
  test_id: string;
  symbol: string;
  status: string;
  winner: string;
  p_value: number;
  significant: boolean;
  recommendation: string;
  strategy_a: StratResult;
  strategy_b: StratResult;
  created_at: string;
}

interface StratResult {
  strategy: string;
  final_equity: number;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_trades: number;
  win_rate: number;
}

const STRATEGIES = [
  'MovingAverageCrossover','RSIStrategy','MACDStrategy',
  'BollingerBands','SMCICTStrategy','EMAcrossover',
  'MeanReversion','Breakout','Stochastic',
];

const MetricRow: React.FC<{ label: string; a: string; b: string; winner: string; stratA: string; stratB: string }> = ({
  label, a, b, winner, stratA, stratB,
}) => (
  <div style={{ display:'flex', gap:8, padding:'8px 0', borderBottom:'1px solid #0f172a', alignItems:'center' }}>
    <div style={{ width:140, fontSize:12, color:'#64748b' }}>{label}</div>
    <div style={{ flex:1, textAlign:'center', fontSize:14, fontWeight:600,
      color: winner === stratA ? '#4ade80' : '#f8fafc' }}>{a}</div>
    <div style={{ flex:1, textAlign:'center', fontSize:14, fontWeight:600,
      color: winner === stratB ? '#4ade80' : '#f8fafc' }}>{b}</div>
  </div>
);

const ABTesting: React.FC = () => {
  const navigate = useNavigate();
  const [tests, setTests]       = useState<ABResult[]>([]);
  const [stratA, setStratA]     = useState('MovingAverageCrossover');
  const [stratB, setStratB]     = useState('RSIStrategy');
  const [symbol, setSymbol]     = useState('XAU/USD');
  const [days, setDays]         = useState('30');
  const [running, setRunning]   = useState(false);
  const [loadingTests, setLoadingTests] = useState(true);
  const [runError, setRunError] = useState<string | null>(null);
  const [loadErr, setLoadErr]   = useState<string | null>(null);
  const [selected, setSelected] = useState<ABResult | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    setLoadingTests(true);
    try {
      const res = await api.get('/advanced/ab-tests');
      setTests(res.data.tests || res.data || []);
    } catch (err) {
      setTests([]);
      setLoadErr(extractApiError(err, 'Failed to load test history. Ensure the API is running.'));
    } finally {
      setLoadingTests(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const run = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const res = await api.post('/advanced/ab-tests/run', {
        strategy_a: stratA, strategy_b: stratB,
        symbol, duration_days: parseInt(days) || 30,
      });
      setTests(prev => [res.data, ...prev]);
      setSelected(res.data);
    } catch (err) {
      setRunError(extractApiError(err, 'Failed to start A/B test. Check strategy names and try again.'));
    } finally {
      setRunning(false);
    }
  };

  const sel = selected || tests[0];

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Strategy A/B Testing</h1>
          <p style={s.subtitle}>Run two strategies in parallel on paper. Auto-select winner after N days.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => navigate('/ai-strategy')}
            style={{ padding: '7px 14px', background: 'rgba(6,182,212,0.12)', border: '1px solid rgba(6,182,212,0.35)', borderRadius: 7, color: '#06b6d4', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🤖 AI Strategy
          </button>
          <button onClick={() => navigate('/walk-forward')}
            style={{ padding: '7px 14px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#8b5cf6', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            📈 Walk-Forward
          </button>
        </div>
      </div>

      <div style={s.grid}>
        {/* Config */}
        <div style={s.card}>
          <div style={s.cardTitle}>New Test</div>
          <label style={s.label}>Strategy A</label>
          <select style={s.select} value={stratA} onChange={e => setStratA(e.target.value)}>
            {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <label style={s.label}>Strategy B</label>
          <select style={s.select} value={stratB} onChange={e => setStratB(e.target.value)}>
            {STRATEGIES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <label style={s.label}>Symbol</label>
          <select style={s.select} value={symbol} onChange={e => setSymbol(e.target.value)}>
            {['XAU/USD','EUR/USD','GBP/USD','BTC/USD'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <label style={s.label}>Duration (days)</label>
          <input style={s.input} type="number" value={days} onChange={e => setDays(e.target.value)} min="1" max="365" />
          <button style={{ ...s.btn, marginTop:16, opacity: running ? 0.6 : 1 }} onClick={run} disabled={running}>
            {running ? 'Running…' : 'Run A/B Test'}
          </button>
          {runError && (
            <div style={s.errorBox}>{runError}</div>
          )}
        </div>

        {/* Results */}
        {sel && (
          <div style={s.card}>
            <div style={s.cardTitle}>Results — {sel.symbol}</div>
            <div style={{ ...s.winnerBanner, border: `1px solid ${sel.significant ? '#4ade80' : '#facc15'}` }}>
              <div style={{ fontSize:12, color:'#94a3b8' }}>Winner</div>
              <div style={{ fontSize:20, fontWeight:800, color: sel.significant ? '#4ade80' : '#facc15' }}>
                {sel.winner}
              </div>
              <div style={{ fontSize:12, color:'#64748b' }}>
                p={sel.p_value} · {sel.significant ? 'Statistically significant' : 'Not significant yet'}
              </div>
            </div>
            <div style={{ fontSize:12, color:'#94a3b8', margin:'12px 0 4px' }}>{sel.recommendation}</div>
            <div style={{ display:'flex', gap:8, marginBottom:8 }}>
              <div style={{ flex:1, textAlign:'center', fontSize:12, fontWeight:700, color:'#60a5fa' }}>{sel.strategy_a.strategy}</div>
              <div style={{ width:140 }} />
              <div style={{ flex:1, textAlign:'center', fontSize:12, fontWeight:700, color:'#a78bfa' }}>{sel.strategy_b.strategy}</div>
            </div>
            <MetricRow label="Total Return" a={`${sel.strategy_a.total_return}%`} b={`${sel.strategy_b.total_return}%`}
              winner={sel.winner} stratA={sel.strategy_a.strategy} stratB={sel.strategy_b.strategy} />
            <MetricRow label="Sharpe Ratio" a={sel.strategy_a.sharpe_ratio.toFixed(2)} b={sel.strategy_b.sharpe_ratio.toFixed(2)}
              winner={sel.winner} stratA={sel.strategy_a.strategy} stratB={sel.strategy_b.strategy} />
            <MetricRow label="Max Drawdown" a={`${sel.strategy_a.max_drawdown}%`} b={`${sel.strategy_b.max_drawdown}%`}
              winner={sel.winner} stratA={sel.strategy_a.strategy} stratB={sel.strategy_b.strategy} />
            <MetricRow label="Win Rate" a={`${sel.strategy_a.win_rate}%`} b={`${sel.strategy_b.win_rate}%`}
              winner={sel.winner} stratA={sel.strategy_a.strategy} stratB={sel.strategy_b.strategy} />
            <MetricRow label="Total Trades" a={String(sel.strategy_a.total_trades)} b={String(sel.strategy_b.total_trades)}
              winner={sel.winner} stratA={sel.strategy_a.strategy} stratB={sel.strategy_b.strategy} />
          </div>
        )}
      </div>

      {/* History */}
      {loadingTests && (
        <div style={{ ...s.card, textAlign: 'center', color: '#64748b', padding: 24 }}>
          Loading test history…
        </div>
      )}
      {loadErr && (
        <div style={{ ...s.card }}>
          <div style={s.errorBox}>{loadErr}</div>
        </div>
      )}
      {!loadErr && tests.length > 1 && (
        <div style={s.card}>
          <div style={s.cardTitle}>Test History</div>
          {tests.map(t => (
            <div key={t.test_id} style={{ ...s.histRow, background: sel?.test_id === t.test_id ? '#0f172a' : 'transparent' }}
              onClick={() => setSelected(t)}>
              <span style={{ fontSize:13 }}>{t.strategy_a.strategy} vs {t.strategy_b.strategy}</span>
              <span style={{ fontSize:12, color:'#64748b' }}>{t.symbol}</span>
              <span style={{ fontSize:12, color:'#4ade80' }}>Winner: {t.winner}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page: { minHeight:'100vh', background:'#0f172a', color:'#f8fafc', fontFamily:"'Inter',system-ui,sans-serif", padding:24 },
  header: { marginBottom:24, display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:12 },
  title: { fontSize:28, fontWeight:700, margin:0 },
  subtitle: { fontSize:14, color:'#94a3b8', marginTop:4 },
  grid: { display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))', gap:20, marginBottom:20 },
  card: { background:'#1e293b', borderRadius:12, padding:24, border:'1px solid #334155', marginBottom:20 },
  cardTitle: { fontSize:13, fontWeight:600, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:16 },
  label: { fontSize:12, color:'#94a3b8', display:'block', marginBottom:6, marginTop:12 },
  select: { width:'100%', background:'#0f172a', border:'1px solid #334155', borderRadius:8, color:'#f8fafc', padding:'9px 12px', fontSize:14, outline:'none' },
  input: { width:'100%', background:'#0f172a', border:'1px solid #334155', borderRadius:8, color:'#f8fafc', padding:'9px 12px', fontSize:14, outline:'none', boxSizing:'border-box' },
  btn: { width:'100%', background:'#3b82f6', border:'none', borderRadius:8, color:'#fff', padding:'10px', fontSize:14, cursor:'pointer', fontWeight:600 },
  winnerBanner: { background:'rgba(74,222,128,0.08)', border:'1px solid #334155', borderRadius:8, padding:'14px 16px', marginBottom:12 },
  histRow: { display:'flex', gap:16, alignItems:'center', padding:'10px 12px', borderRadius:6, cursor:'pointer', flexWrap:'wrap' },
  errorBox: {
    background:'rgba(248,113,113,0.1)', border:'1px solid #f87171', borderRadius:6,
    padding:'8px 12px', marginTop:12, fontSize:13, color:'#f87171',
  },
};

export default ABTesting;
