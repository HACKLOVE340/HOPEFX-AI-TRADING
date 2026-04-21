/**
 * Multi-Symbol Correlation Dashboard (Task 45)
 * + CFTC COT Gold Sentiment (Task 46)
 */
import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../hooks/useApi';

interface CorrelationData {
  symbols: string[];
  matrix: Record<string, Record<string, number>>;
  insights: string[];
  window: number;
  updated_at: string;
}

interface COTData {
  report_date: string;
  net_speculator_long: number;
  long_positions: number;
  short_positions: number;
  sentiment: string;
  sentiment_strength: string;
  note: string;
  weekly_change?: number;
  source: string;
}

const corrColor = (v: number): string => {
  if (v >= 0.7)  return '#4ade80';
  if (v >= 0.3)  return '#86efac';
  if (v >= -0.3) return '#94a3b8';
  if (v >= -0.7) return '#fca5a5';
  return '#f87171';
};

const CorrelationDashboard: React.FC = () => {
  const [corr, setCorr]   = useState<CorrelationData | null>(null);
  const [cot,  setCot]    = useState<COTData | null>(null);
  const [loading, setLoading] = useState(true);
  const [window, setWindow]   = useState(30);

  const load = useCallback(async () => {
    setLoading(true);
    const [corrRes, cotRes] = await Promise.allSettled([
      api.get('/advanced/correlation', { params: { window } }),
      api.get('/advanced/cot-sentiment'),
    ]);
    setCorr(corrRes.status === 'fulfilled' ? corrRes.value.data : null);
    setCot(cotRes.status === 'fulfilled' ? cotRes.value.data : null);
    setLoading(false);
  }, [window]);

  useEffect(() => { load(); }, [load]);

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Correlation & Sentiment</h1>
          <p style={s.subtitle}>Rolling correlations between gold, FX, equities, and macro indicators.</p>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:13, color:'#94a3b8' }}>Window:</span>
          {[14,30,60,90].map(w => (
            <button key={w} style={{ ...s.wBtn, ...(window===w ? s.wBtnActive : {}) }} onClick={() => setWindow(w)}>{w}d</button>
          ))}
        </div>
      </div>

      {loading ? <div style={s.dim}>Loading…</div> : (!corr && !cot) ? (
        <div style={s.dim}>Correlation data unavailable. Ensure the data layer is running.</div>
      ) : (
        <div style={s.grid}>
          {/* Correlation matrix */}
          {corr && (
            <div style={{ ...s.card, gridColumn:'span 2' }}>
              <div style={s.cardTitle}>Rolling {corr.window}-Day Correlation Matrix</div>
              <div style={{ overflowX:'auto' }}>
                <table style={{ borderCollapse:'collapse', fontSize:12 }}>
                  <thead>
                    <tr>
                      <th style={s.mth} />
                      {corr.symbols.map(sym => <th key={sym} style={s.mth}>{sym}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {corr.symbols.map(row => (
                      <tr key={row}>
                        <td style={{ ...s.mtd, fontWeight:600, color:'#94a3b8', whiteSpace:'nowrap' }}>{row}</td>
                        {corr.symbols.map(col => {
                          const v = corr.matrix[row]?.[col] ?? 0;
                          return (
                            <td key={col} style={{ ...s.mtd, background: row===col ? '#334155' : `${corrColor(v)}22`, color: corrColor(v), fontWeight: row===col ? 700 : 400 }}>
                              {v.toFixed(2)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ marginTop:16 }}>
                <div style={s.cardTitle}>Key Insights</div>
                {corr.insights.map((ins, i) => (
                  <div key={i} style={{ fontSize:13, color:'#94a3b8', padding:'4px 0', borderBottom:'1px solid #0f172a' }}>
                    • {ins}
                  </div>
                ))}
              </div>
              <div style={{ display:'flex', gap:16, marginTop:12, flexWrap:'wrap' }}>
                {[['≥ 0.7','Strong positive','#4ade80'],['0.3–0.7','Moderate positive','#86efac'],
                  ['-0.3–0.3','Weak / none','#94a3b8'],['-0.7–-0.3','Moderate negative','#fca5a5'],['≤ -0.7','Strong negative','#f87171']].map(([range,label,color]) => (
                  <div key={range} style={{ display:'flex', alignItems:'center', gap:6, fontSize:11 }}>
                    <div style={{ width:12, height:12, borderRadius:2, background: color as string }} />
                    <span style={{ color:'#64748b' }}>{range} {label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* COT Sentiment */}
          {cot && (
            <div style={s.card}>
              <div style={s.cardTitle}>CFTC COT — Gold Speculator Sentiment</div>
              <div style={{ textAlign:'center', padding:'16px 0' }}>
                <div style={{ fontSize:36, fontWeight:800, color: cot.sentiment==='BULLISH' ? '#4ade80' : '#f87171' }}>
                  {cot.sentiment}
                </div>
                <div style={{ fontSize:14, color:'#64748b', marginTop:4 }}>{cot.sentiment_strength}</div>
              </div>
              <div style={s.cotRow}>
                <span style={s.cotLabel}>Net Long</span>
                <span style={{ fontSize:18, fontWeight:700, color: (cot.net_speculator_long ?? 0) > 0 ? '#4ade80' : '#f87171' }}>
                  {(cot.net_speculator_long ?? 0) > 0 ? '+' : ''}{(cot.net_speculator_long ?? 0).toLocaleString()}
                </span>
              </div>
              <div style={s.cotRow}>
                <span style={s.cotLabel}>Long Positions</span>
                <span style={{ color:'#4ade80' }}>{(cot.long_positions ?? 0).toLocaleString()}</span>
              </div>
              <div style={s.cotRow}>
                <span style={s.cotLabel}>Short Positions</span>
                <span style={{ color:'#f87171' }}>{(cot.short_positions ?? 0).toLocaleString()}</span>
              </div>
              {cot.weekly_change !== undefined && (
                <div style={s.cotRow}>
                  <span style={s.cotLabel}>Weekly Change</span>
                  <span style={{ color: cot.weekly_change > 0 ? '#4ade80' : '#f87171' }}>
                    {cot.weekly_change > 0 ? '+' : ''}{cot.weekly_change.toLocaleString()}
                  </span>
                </div>
              )}
              <div style={s.cotRow}>
                <span style={s.cotLabel}>Report Date</span>
                <span style={{ color:'#94a3b8' }}>{cot.report_date}</span>
              </div>
              <div style={{ fontSize:12, color:'#475569', marginTop:12, lineHeight:1.5 }}>{cot.note}</div>
              <div style={{ fontSize:11, color:'#334155', marginTop:8 }}>Source: {cot.source}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page: { minHeight:'100vh', background:'#0f172a', color:'#f8fafc', fontFamily:"'Inter',system-ui,sans-serif", padding:24 },
  header: { display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:24, flexWrap:'wrap', gap:12 },
  title: { fontSize:28, fontWeight:700, margin:0 },
  subtitle: { fontSize:14, color:'#94a3b8', marginTop:4 },
  grid: { display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))', gap:20 },
  card: { background:'#1e293b', borderRadius:12, padding:24, border:'1px solid #334155' },
  cardTitle: { fontSize:13, fontWeight:600, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:16 },
  mth: { padding:'8px 12px', color:'#64748b', fontWeight:600, textAlign:'center', whiteSpace:'nowrap', borderBottom:'1px solid #334155' },
  mtd: { padding:'8px 12px', textAlign:'center', borderBottom:'1px solid #0f172a' },
  cotRow: { display:'flex', justifyContent:'space-between', alignItems:'center', padding:'8px 0', borderBottom:'1px solid #0f172a', fontSize:14 },
  cotLabel: { color:'#64748b', fontSize:13 },
  wBtn: { background:'#1e293b', border:'1px solid #334155', borderRadius:6, color:'#64748b', padding:'5px 10px', fontSize:12, cursor:'pointer' },
  wBtnActive: { background:'#3b82f6', border:'1px solid #3b82f6', color:'#fff' },
  dim: { color:'#475569', textAlign:'center', padding:48 },
};

export default CorrelationDashboard;
