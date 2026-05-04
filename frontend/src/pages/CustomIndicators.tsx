/**
 * Custom Indicator Builder (Task 44)
 * Define indicator formulas, preview on chart, save for use in strategies.
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChart, LineSeries, type IChartApi, type UTCTimestamp } from 'lightweight-charts';
import { indicatorsApi } from '../hooks/useApi';

interface Indicator { id: string; name: string; formula: string; symbol: string; color: string; created_at: string; }
interface PreviewPoint { index: number; value: number; }

const EXAMPLES = [
  { label: 'EMA 20/50 Ratio', formula: 'EMA(close, 20)' },
  { label: 'RSI(14)',          formula: 'RSI(close, 14)' },
  { label: 'SMA(20)',          formula: 'SMA(close, 20)' },
  { label: 'EMA(9)',           formula: 'EMA(close, 9)' },
];

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
  const navigate = useNavigate();
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

  const loadIndicators = useCallback(async () => {
    try {
      const res = await indicatorsApi.list();
      const d = res.data as { indicators?: Indicator[] } | Indicator[];
      setIndicators(Array.isArray(d) ? d : (d.indicators ?? []));
    } catch { setIndicators([]); }
  }, []);

  useEffect(() => { loadIndicators(); }, [loadIndicators]);

  const runPreview = async () => {
    setLoading(true); setError('');
    try {
      const res = await indicatorsApi.preview({ formula, symbol, periods: 100 });
      const d = res.data as { data?: PreviewPoint[] } | PreviewPoint[];
      setPreview(Array.isArray(d) ? d : (d.data ?? []));
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Formula error');
      setPreview([]);
    }
    setLoading(false);
  };

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
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Custom Indicator Builder</h1>
          <p style={s.subtitle}>Define indicator formulas using EMA, SMA, RSI. Preview on chart. Save for use in strategies.</p>
        </div>
        <div style={{ display:'flex', gap:8 }}>
          <button
            onClick={() => navigate('/ai-strategy')}
            style={{ background:'rgba(167,139,250,0.12)', border:'1px solid rgba(167,139,250,0.35)', borderRadius:7, color:'#a78bfa', fontSize:12, fontWeight:700, padding:'7px 14px', cursor:'pointer' }}
          >
            🤖 AI Strategy
          </button>
          <button
            onClick={() => navigate('/walk-forward')}
            style={{ background:'rgba(96,165,250,0.12)', border:'1px solid rgba(96,165,250,0.35)', borderRadius:7, color:'#60a5fa', fontSize:12, fontWeight:700, padding:'7px 14px', cursor:'pointer' }}
          >
            📊 Walk-Forward Test
          </button>
        </div>
      </div>

      <div style={s.grid}>
        {/* Builder */}
        <div style={s.card}>
          <div style={s.cardTitle}>Formula Editor</div>
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
          />
          <div style={{ fontSize:11, color:'#475569', marginTop:4 }}>
            Available: EMA(data, n), SMA(data, n), RSI(data, n), close, open, high, low, volume
          </div>
          {error && <div style={s.error}>{error}</div>}
          {msg   && <div style={s.success}>{msg}</div>}
          <div style={{ display:'flex', gap:8, marginTop:12 }}>
            <select style={s.select} value={symbol} onChange={e => setSymbol(e.target.value)}>
              {['XAU/USD','EUR/USD','GBP/USD','BTC/USD'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <input type="color" value={color} onChange={e => setColor(e.target.value)}
              style={{ width:40, height:36, border:'none', background:'none', cursor:'pointer' }} />
          </div>
          <button style={{ ...s.btn, marginTop:12 }} onClick={runPreview} disabled={loading}>
            {loading ? 'Computing…' : 'Preview'}
          </button>
          <div style={s.divider} />
          <label style={s.label}>Save as</label>
          <input style={s.input} value={name} onChange={e => setName(e.target.value)} placeholder="My EMA Ratio" />
          <button style={{ ...s.btn, background:'#334155', marginTop:8 }} onClick={save}>Save Indicator</button>
        </div>

        {/* Preview chart */}
        <div style={s.card}>
          <div style={s.cardTitle}>Preview — {symbol}</div>
          {preview.length > 0
            ? <PreviewChart data={preview} color={color} />
            : <div style={s.placeholder}>Click "Preview" to see the indicator plotted on live {symbol} data.</div>
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
