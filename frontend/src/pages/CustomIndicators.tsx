/**
 * Custom Indicator Builder
 * Define indicator formulas, preview on chart, save for use in strategies.
 *
 * Wires to:
 *   GET  /api/indicators          — list saved indicators
 *   POST /api/indicators          — save indicator
 *   POST /api/indicators/preview  — compute preview data
 *   DELETE /api/indicators/:id    — delete indicator
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components';
import { createChart, LineSeries, type UTCTimestamp } from 'lightweight-charts';
import { indicatorsApi } from '../hooks/useApi';

interface Indicator { id: string; name: string; formula: string; symbol: string; color: string; created_at: string; }
interface PreviewPoint { index: number; value: number; }

const EXAMPLES = [
  { label: 'EMA 20/50 Ratio', formula: 'EMA(close, 20) / EMA(close, 50)' },
  { label: 'RSI(14)',          formula: 'RSI(close, 14)' },
  { label: 'SMA(20)',          formula: 'SMA(close, 20)' },
  { label: 'EMA(9)',           formula: 'EMA(close, 9)' },
  { label: 'MACD Signal',      formula: 'EMA(close, 12) - EMA(close, 26)' },
  { label: 'Bollinger %B',     formula: '(close - SMA(close, 20)) / (2 * SMA(close, 20))' },
];

// ── Syntax highlighter ────────────────────────────────────────────────────────
// Tokenises formula text and applies colour coding without external deps.

const FUNC_KEYWORDS = ['EMA', 'SMA', 'RSI', 'MACD', 'ATR', 'STOCH', 'BB', 'WMA', 'DEMA', 'TEMA'];
const DATA_KEYWORDS = ['close', 'open', 'high', 'low', 'volume'];

function highlightFormula(formula: string): React.ReactNode[] {
  // Simple token-based highlighter
  const tokens: React.ReactNode[] = [];
  let i = 0;
  while (i < formula.length) {
    // Try to match a word
    const wordMatch = formula.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
    if (wordMatch) {
      const word = wordMatch[0];
      if (FUNC_KEYWORDS.includes(word)) {
        tokens.push(<span key={i} style={{ color: '#60a5fa', fontWeight: 700 }}>{word}</span>);
      } else if (DATA_KEYWORDS.includes(word)) {
        tokens.push(<span key={i} style={{ color: '#4ade80' }}>{word}</span>);
      } else {
        tokens.push(<span key={i} style={{ color: '#e2e8f0' }}>{word}</span>);
      }
      i += word.length;
      continue;
    }
    // Number
    const numMatch = formula.slice(i).match(/^\d+(\.\d+)?/);
    if (numMatch) {
      tokens.push(<span key={i} style={{ color: '#f59e0b' }}>{numMatch[0]}</span>);
      i += numMatch[0].length;
      continue;
    }
    // Operator / punctuation
    const ch = formula[i];
    const opColor = '+-*/()'.includes(ch) ? '#a78bfa' : '#94a3b8';
    tokens.push(<span key={i} style={{ color: opColor }}>{ch}</span>);
    i++;
  }
  return tokens;
}

// ── Syntax-highlighted formula display ───────────────────────────────────────

const FormulaHighlight: React.FC<{ formula: string }> = ({ formula }) => (
  <div style={{
    background: '#0a0f1a', border: '1px solid #1e293b', borderRadius: 6,
    padding: '8px 12px', fontFamily: 'monospace', fontSize: 13, lineHeight: 1.6,
    marginTop: 6, minHeight: 36, wordBreak: 'break-all',
  }}>
    {formula ? highlightFormula(formula) : <span style={{ color: '#334155' }}>Enter a formula above…</span>}
  </div>
);

const PreviewChart: React.FC<{ data: PreviewPoint[]; color: string }> = ({ data, color }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = createChart(ref.current, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: ref.current.clientWidth, height: 200,
      timeScale: { borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });
    const series = chart.addSeries(LineSeries, { color, lineWidth: 2 });
    // Use real timestamps: anchor to today and step back by day per point
    const nowSec = Math.floor(Date.now() / 1000);
    series.setData(data.map((d, i) => ({
      time: (nowSec - (data.length - 1 - i) * 86400) as UTCTimestamp,
      value: d.value,
    })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, color]);
  return <div ref={ref} style={{ width: '100%', height: 200 }} />;
};

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

const CustomIndicators: React.FC = () => {
  const [formula,    setFormula]    = useState('EMA(close, 20)');
  const [name,       setName]       = useState('');
  const [color,      setColor]      = useState('#60a5fa');
  const [symbol,     setSymbol]     = useState('XAU/USD');
  const [preview,    setPreview]    = useState<PreviewPoint[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState('');
  const [msg,        setMsg]        = useState('');
  const [deleteErr,  setDeleteErr]  = useState('');
  const [autoPreview, setAutoPreview] = useState(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadIndicators = useCallback(async () => {
    try {
      const res = await indicatorsApi.list();
      const d = res.data as { indicators?: Indicator[] } | Indicator[];
      setIndicators(Array.isArray(d) ? d : (d.indicators ?? []));
    } catch { setIndicators([]); }
  }, []);

  useEffect(() => { loadIndicators(); }, [loadIndicators]);

  const runPreview = useCallback(async (f?: string, s?: string) => {
    const fml = f ?? formula;
    const sym = s ?? symbol;
    if (!fml.trim()) return;
    setLoading(true); setError('');
    try {
      const res = await indicatorsApi.preview({ formula: fml, symbol: sym, periods: 100 });
      const d = res.data as { data?: PreviewPoint[] } | PreviewPoint[];
      setPreview(Array.isArray(d) ? d : (d.data ?? []));
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Formula error');
      setPreview([]);
    }
    setLoading(false);
  }, [formula, symbol]);

  // Auto-preview: debounce 800ms after formula/symbol change
  useEffect(() => {
    if (!autoPreview) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { void runPreview(); }, 800);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [formula, symbol, autoPreview, runPreview]);

  const save = async () => {
    if (!name.trim()) { setError('Enter a name first.'); return; }
    try {
      await indicatorsApi.create({ name, formula, symbol, color });
      setMsg(`Saved "${name}"`);
      setName('');
      await loadIndicators();
    } catch { setError('Failed to save.'); }
  };

  const del = async (id: string) => {
    setDeleteErr('');
    try {
      await indicatorsApi.delete(id);
      setIndicators(prev => prev.filter(i => i.id !== id));
    } catch (err) {
      setDeleteErr(extractErrorMessage(err, 'Failed to delete indicator. Please try again.'));
    }
  };

  return (
    <div style={s.page}>
      <PageHeader
        title="Custom Indicator Builder"
        icon="📐"
        subtitle="Define indicator formulas using EMA, SMA, RSI. Preview on chart. Save for use in strategies."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'AI Strategy', href: '/ai-strategy' },
          { label: 'Custom Indicators' },
        ]}
        actions={
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <Link to="/ai-chart"
              style={{ background:'rgba(59,130,246,0.12)', border:'1px solid rgba(59,130,246,0.35)', borderRadius:7, color:'#60a5fa', fontSize:12, fontWeight:600, padding:'6px 12px', textDecoration:'none' }}>
              📈 AI Charts
            </Link>
            <Link to="/ai-strategy"
              style={{ background:'rgba(167,139,250,0.12)', border:'1px solid rgba(167,139,250,0.35)', borderRadius:7, color:'#a78bfa', fontSize:12, fontWeight:600, padding:'6px 12px', textDecoration:'none' }}>
              🤖 AI Strategy
            </Link>
            <Link to="/walk-forward"
              style={{ background:'rgba(96,165,250,0.12)', border:'1px solid rgba(96,165,250,0.35)', borderRadius:7, color:'#60a5fa', fontSize:12, fontWeight:600, padding:'6px 12px', textDecoration:'none' }}>
              📊 Walk-Forward
            </Link>
            <Link to="/pattern-detector"
              style={{ background:'rgba(251,191,36,0.12)', border:'1px solid rgba(251,191,36,0.35)', borderRadius:7, color:'#fbbf24', fontSize:12, fontWeight:600, padding:'6px 12px', textDecoration:'none' }}>
              🔍 Patterns
            </Link>
          </div>
        }
      />

      <div style={s.grid}>
        {/* Builder */}
        <div style={s.card}>
          <div style={s.cardTitle}>Formula Editor</div>
          {/* Auto-preview toggle */}
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
            <div style={{ fontSize:11, color:'#64748b' }}>
              Syntax: <span style={{ color:'#60a5fa' }}>FUNC</span> · <span style={{ color:'#4ade80' }}>data</span> · <span style={{ color:'#f59e0b' }}>number</span> · <span style={{ color:'#a78bfa' }}>operator</span>
            </div>
            <label style={{ display:'flex', alignItems:'center', gap:6, cursor:'pointer', fontSize:11, color:'#64748b' }}>
              <input type="checkbox" checked={autoPreview} onChange={e => setAutoPreview(e.target.checked)}
                style={{ accentColor:'#3b82f6' }} />
              Auto-preview
            </label>
          </div>

          <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:12 }}>
            {EXAMPLES.map(ex => (
              <button key={ex.label} style={s.exBtn} onClick={() => setFormula(ex.formula)}>{ex.label}</button>
            ))}
          </div>
          <label style={s.label}>Formula</label>
          <textarea
            style={s.textarea}
            value={formula}
            onChange={e => setFormula(e.target.value)}
            rows={3}
            placeholder="EMA(close, 20) / EMA(close, 50)"
            spellCheck={false}
          />
          {/* Syntax-highlighted preview of formula */}
          <FormulaHighlight formula={formula} />
          <div style={{ fontSize:11, color:'#475569', marginTop:6 }}>
            Functions: <span style={{ color:'#60a5fa' }}>EMA SMA RSI MACD ATR BB</span> · Data: <span style={{ color:'#4ade80' }}>close open high low volume</span>
          </div>
          {error && <div style={s.error}>{error}</div>}
          {msg   && <div style={s.success}>{msg}</div>}
          <div style={{ display:'flex', gap:8, marginTop:12 }}>
            <select style={s.select} value={symbol} onChange={e => setSymbol(e.target.value)}>
              {['XAU/USD','EUR/USD','GBP/USD','BTC/USD'].map(sym => <option key={sym} value={sym}>{sym}</option>)}
            </select>
            <input type="color" value={color} onChange={e => setColor(e.target.value)}
              style={{ width:40, height:36, border:'none', background:'none', cursor:'pointer' }} />
          </div>
          <button style={{ ...s.btn, marginTop:12 }} onClick={() => void runPreview()} disabled={loading}>
            {loading ? 'Computing…' : '▶ Preview'}
          </button>
          <div style={s.divider} />
          <label style={s.label}>Save as</label>
          <input style={s.input} value={name} onChange={e => setName(e.target.value)} placeholder="My EMA Ratio" />
          <button style={{ ...s.btn, background:'#334155', marginTop:8 }} onClick={save}>Save Indicator</button>
        </div>

        {/* Preview chart */}
        <div style={s.card}>
          <div style={s.cardTitle}>Preview — {symbol}</div>
          {loading && (
            <div style={{ textAlign:'center', padding:'20px 0', color:'#64748b', fontSize:13 }}>⏳ Computing…</div>
          )}
          {!loading && preview.length > 0
            ? <PreviewChart data={preview} color={color} />
            : !loading && <div style={s.placeholder}>{autoPreview ? 'Type a formula above — preview updates automatically.' : 'Click ▶ Preview to plot the indicator on live ' + symbol + ' data.'}</div>
          }
          {preview.length > 0 && (
            <div style={{ fontSize:12, color:'#64748b', marginTop:8 }}>
              {preview.length} data points · min {Math.min(...preview.map(d=>d.value)).toFixed(4)} · max {Math.max(...preview.map(d=>d.value)).toFixed(4)}
            </div>
          )}
        </div>
      </div>

      {/* Saved indicators */}
      {indicators.length > 0 && (
        <div style={s.card}>
          <div style={s.cardTitle}>Saved Indicators</div>
          {deleteErr && <div style={s.error}>{deleteErr}</div>}
          {indicators.map(ind => (
            <div key={ind.id} style={s.indRow}>
              <div style={{ width:12, height:12, borderRadius:'50%', background:ind.color, flexShrink:0 }} />
              <div style={{ flex:1 }}>
                <div style={{ fontWeight:600, fontSize:14 }}>{ind.name}</div>
                <div style={{ fontSize:12, color:'#64748b', fontFamily:'monospace' }}>{ind.formula}</div>
              </div>
              <span style={{ fontSize:12, color:'#64748b' }}>{ind.symbol}</span>
              <button style={s.delBtn} onClick={() => del(ind.id)}>Delete</button>
            </div>
          ))}
        </div>
      )}

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/ai-strategy" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🤖 AI Strategy</Link>
        <Link to="/ai-chart" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📈 AI Charts</Link>
        <Link to="/pattern-detector" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🔍 Pattern Detector</Link>
        <Link to="/walk-forward" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📊 Walk-Forward</Link>
      </div>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page: { minHeight:'100vh', background:'#0f172a', color:'#f8fafc', fontFamily:"'Inter',system-ui,sans-serif", padding:24 },
  header: { marginBottom:24, display:'flex', justifyContent:'space-between', alignItems:'flex-start' },
  title: { fontSize:28, fontWeight:700, margin:0 },
  subtitle: { fontSize:14, color:'#94a3b8', marginTop:4 },
  grid: { display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))', gap:20, marginBottom:20 },
  card: { background:'#1e293b', borderRadius:12, padding:24, border:'1px solid #334155', marginBottom:20 },
  cardTitle: { fontSize:13, fontWeight:600, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:16 },
  label: { fontSize:12, color:'#94a3b8', display:'block', marginBottom:6, marginTop:12 },
  textarea: { width:'100%', background:'#0f172a', border:'1px solid #334155', borderRadius:8, color:'#f8fafc', padding:'10px 12px', fontSize:13, outline:'none', resize:'vertical', boxSizing:'border-box', fontFamily:'monospace' },
  input: { width:'100%', background:'#0f172a', border:'1px solid #334155', borderRadius:8, color:'#f8fafc', padding:'9px 12px', fontSize:14, outline:'none', boxSizing:'border-box' },
  select: { flex:1, background:'#0f172a', border:'1px solid #334155', borderRadius:8, color:'#f8fafc', padding:'9px 12px', fontSize:14, outline:'none' },
  btn: { width:'100%', background:'#3b82f6', border:'none', borderRadius:8, color:'#fff', padding:'10px', fontSize:14, cursor:'pointer', fontWeight:600 },
  exBtn: { background:'#0f172a', border:'1px solid #334155', borderRadius:6, color:'#94a3b8', padding:'4px 10px', fontSize:11, cursor:'pointer' },
  divider: { height:1, background:'#334155', margin:'16px 0' },
  error: { background:'rgba(248,113,113,0.1)', border:'1px solid #f87171', borderRadius:6, padding:'6px 10px', fontSize:12, color:'#f87171', marginTop:8 },
  success: { background:'rgba(74,222,128,0.1)', border:'1px solid #4ade80', borderRadius:6, padding:'6px 10px', fontSize:12, color:'#4ade80', marginTop:8 },
  placeholder: { color:'#475569', fontSize:13, textAlign:'center', padding:32 },
  indRow: { display:'flex', alignItems:'center', gap:12, padding:'10px 0', borderBottom:'1px solid #0f172a' },
  delBtn: { background:'transparent', border:'1px solid #334155', borderRadius:5, color:'#f87171', padding:'3px 8px', fontSize:11, cursor:'pointer' },
};

export default CustomIndicators;
