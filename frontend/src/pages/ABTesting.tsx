/**
 * Strategy A/B Testing
 * Run two strategies in parallel on paper, auto-select winner.
 *
 * Strategy names are fetched from GET /api/advanced/ab-tests/strategies/available
 * so the list always matches what the backend accepts.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PageHeader, CrossLinkBar } from '../components';
import { api } from '../hooks/useApi';

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

// Fallback list — matches _STRATEGY_CLASS_MAP keys in api/advanced_trading.py.
// The component fetches the live list from the backend on mount and replaces this.
const STRATEGIES_FALLBACK = [
  'MovingAverageCrossover', 'RSIStrategy', 'MACDStrategy',
  'BollingerBands', 'SMCICTStrategy', 'EMAcrossover',
  'MeanReversion', 'Breakout', 'Stochastic',
];

// ── Win-rate bar ──────────────────────────────────────────────────────────────

const WinRateBar: React.FC<{ stratA: StratResult; stratB: StratResult; winner: string }> = ({ stratA, stratB, winner }) => {
  const total = stratA.win_rate + stratB.win_rate;
  const pctA  = total > 0 ? (stratA.win_rate / total) * 100 : 50;
  const pctB  = 100 - pctA;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#64748b', marginBottom: 4 }}>
        <span style={{ color: '#60a5fa', fontWeight: 600 }}>{stratA.strategy}</span>
        <span style={{ color: '#94a3b8' }}>Win Rate</span>
        <span style={{ color: '#a78bfa', fontWeight: 600 }}>{stratB.strategy}</span>
      </div>
      <div style={{ display: 'flex', height: 20, borderRadius: 10, overflow: 'hidden', background: '#0f172a' }}>
        <div style={{ width: `${pctA}%`, background: winner === stratA.strategy ? '#3b82f6' : '#1e3a5f', transition: 'width 0.6s ease', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', fontWeight: 700 }}>
          {stratA.win_rate.toFixed(1)}%
        </div>
        <div style={{ width: `${pctB}%`, background: winner === stratB.strategy ? '#8b5cf6' : '#2d1b69', transition: 'width 0.6s ease', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#fff', fontWeight: 700 }}>
          {stratB.win_rate.toFixed(1)}%
        </div>
      </div>
    </div>
  );
};

// ── Significance meter ────────────────────────────────────────────────────────

const SignificanceMeter: React.FC<{ pValue: number; significant: boolean }> = ({ pValue, significant }) => {
  const confidence = Math.max(0, Math.min(100, (1 - pValue) * 100));
  const color = significant ? '#4ade80' : pValue < 0.1 ? '#facc15' : '#f87171';
  const label = significant ? 'Statistically Significant' : pValue < 0.1 ? 'Approaching Significance' : 'Not Significant';
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 6 }}>
        <span style={{ color: '#64748b' }}>Statistical Confidence</span>
        <span style={{ color, fontWeight: 700 }}>{confidence.toFixed(1)}% — {label}</span>
      </div>
      <div style={{ height: 8, background: '#0f172a', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${confidence}%`, background: `linear-gradient(90deg, #334155, ${color})`, borderRadius: 4, transition: 'width 0.6s ease' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#475569', marginTop: 3 }}>
        <span>p = {pValue.toFixed(4)}</span>
        <span>α = 0.05 threshold</span>
        <div style={{ width: 1, height: 8, background: '#3b82f6', position: 'relative', top: -11, left: `calc(95% - 1px)` }} />
      </div>
    </div>
  );
};

// ── Metric row ────────────────────────────────────────────────────────────────

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

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const e = err as Record<string, unknown>;
    const detail = (e['response'] as Record<string, unknown> | undefined)?.['data'];
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>;
      if (typeof d['detail'] === 'string') return d['detail'];
      if (typeof d['message'] === 'string') return d['message'];
    }
    if (typeof e['message'] === 'string') return e['message'];
  }
  return fallback;
}

const ABTesting: React.FC = () => {
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<string[]>(STRATEGIES_FALLBACK);
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch available strategy names from backend so the selector always matches
  // what the backend accepts — avoids the "check strategy names" 422 error.
  useEffect(() => {
    api.get('/advanced/ab-tests/strategies/available')
      .then(res => {
        const data = res.data as { strategies?: string[] };
        if (Array.isArray(data.strategies) && data.strategies.length > 0) {
          setStrategies(data.strategies);
          // Reset selections to first two valid names
          setStratA(data.strategies[0]);
          setStratB(data.strategies[1] ?? data.strategies[0]);
        }
      })
      .catch(() => { /* keep fallback list */ });
  }, []);

  // Auto-poll every 5s while any test is in 'running' status
  const startPoll = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const res = await api.get('/advanced/ab-tests');
        const fresh: ABResult[] = res.data.tests || res.data || [];
        setTests(fresh);
        const anyRunning = fresh.some(t => t.status === 'running');
        if (!anyRunning && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch { /* non-fatal */ }
    }, 5000);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const load = useCallback(async () => {
    setLoadErr(null);
    setLoadingTests(true);
    try {
      const res = await api.get('/advanced/ab-tests');
      const fresh: ABResult[] = res.data.tests || res.data || [];
      setTests(fresh);
      if (fresh.some(t => t.status === 'running')) startPoll();
    } catch (err) {
      setTests([]);
      setLoadErr(extractErrorMessage(err, 'Failed to load test history. Ensure the API is running.'));
    } finally {
      setLoadingTests(false);
    }
  }, [startPoll]);

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
      if (res.data.status === 'running') startPoll();
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail = extractErrorMessage(err, '');
      if (status === 422) {
        setRunError(detail || 'A/B test failed — strategy or market data unavailable for the selected period. Try a shorter duration or different symbol.');
      } else if (status === 403) {
        setRunError('A/B testing requires a Professional plan or above.');
      } else {
        setRunError(detail || 'Failed to start A/B test. Ensure the backend is running.');
      }
    } finally {
      setRunning(false);
    }
  };

  const sel = selected || tests[0];

  return (
    <div style={s.page}>
      <PageHeader
        title="Strategy A/B Testing"
        icon="⚗️"
        subtitle="Run two strategies in parallel on paper. Auto-select winner after N days."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'AI Strategy', href: '/ai-strategy' },
          { label: 'A/B Testing' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Link to="/ai-strategy"      style={navLink('#06b6d4')}>🤖 AI Strategy</Link>
            <Link to="/walk-forward"     style={navLink('#8b5cf6')}>📊 Walk-Forward</Link>
            <Link to="/pattern-detector" style={navLink('#fbbf24')}>🔍 Patterns</Link>
            <Link to="/performance"      style={navLink('#4ade80')}>📈 Performance</Link>
          </div>
        }
      />

      <div style={s.grid}>
        {/* Config */}
        <div style={s.card}>
          <div style={s.cardTitle}>New Test</div>
          <label style={s.label}>Strategy A</label>
          <select style={s.select} value={stratA} onChange={e => setStratA(e.target.value)}>
            {strategies.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
          <label style={s.label}>Strategy B</label>
          <select style={s.select} value={stratB} onChange={e => setStratB(e.target.value)}>
            {strategies.map(name => <option key={name} value={name}>{name}</option>)}
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
            {/* Auto-winner banner */}
            <div style={{ ...s.winnerBanner, border: `1px solid ${sel.significant ? '#4ade80' : '#facc15'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize:12, color:'#94a3b8' }}>
                    {sel.status === 'running' ? '⏳ Running…' : sel.significant ? '🏆 Auto-Winner' : '⚖ Inconclusive'}
                  </div>
                  <div style={{ fontSize:20, fontWeight:800, color: sel.significant ? '#4ade80' : '#facc15' }}>
                    {sel.winner || '—'}
                  </div>
                </div>
                {sel.status === 'running' && (
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#facc15', animation: 'pulse 1.5s infinite' }} />
                )}
              </div>
            </div>

            {/* Win-rate bar */}
            <WinRateBar stratA={sel.strategy_a} stratB={sel.strategy_b} winner={sel.winner} />

            {/* Significance meter */}
            <SignificanceMeter pValue={sel.p_value} significant={sel.significant} />

            <div style={{ fontSize:12, color:'#94a3b8', margin:'4px 0 12px' }}>{sel.recommendation}</div>
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

      <CrossLinkBar title="Related" style={{ marginTop: 16 }} links={[
        { label: 'AI Strategy',     href: '/ai-strategy',      icon: '🤖', color: '#06b6d4' },
        { label: 'Walk-Forward',    href: '/walk-forward',     icon: '📊', color: '#8b5cf6' },
        { label: 'Performance',     href: '/performance',      icon: '📈', color: '#4ade80' },
        { label: 'Pattern Detector',href: '/pattern-detector', icon: '🔍', color: '#fbbf24' },
        { label: 'Backtesting',     href: '/backtest',         icon: '⚗️', color: '#f97316' },
        { label: 'Trade Journal',   href: '/journal',          icon: '📓', color: '#a78bfa' },
      ]} />
    </div>
  );
};

const navLink = (color: string): React.CSSProperties => ({
  padding: '6px 12px', background: `${color}1a`, border: `1px solid ${color}55`,
  borderRadius: 7, color, fontSize: 12, fontWeight: 600, textDecoration: 'none',
});

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
