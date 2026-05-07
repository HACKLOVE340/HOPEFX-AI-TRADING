/**
 * Multi-Symbol Correlation Dashboard
 *
 * Wires to:
 *   GET /api/advanced/correlation?window=N   — rolling correlation matrix + insights
 *   GET /api/advanced/cot-sentiment          — CFTC COT gold speculator data
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PageHeader, CrossLinkBar } from '../components';
import { api } from '../hooks/useApi';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';

// ── Types ─────────────────────────────────────────────────────────────────────

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
  history?: { date: string; net: number }[];
}

interface HoverCell {
  row: string;
  col: string;
  value: number;
  x: number;
  y: number;
}

// ── Colour helpers ────────────────────────────────────────────────────────────

const corrColor = (v: number): string => {
  if (v >= 0.7)  return '#4ade80';
  if (v >= 0.3)  return '#86efac';
  if (v >= -0.3) return '#94a3b8';
  if (v >= -0.7) return '#fca5a5';
  return '#f87171';
};

const corrBg = (v: number, isDiag: boolean): string => {
  if (isDiag) return '#334155';
  const alpha = Math.abs(v) * 0.45 + 0.05;
  if (v >= 0) return `rgba(74,222,128,${alpha})`;
  return `rgba(248,113,113,${alpha})`;
};

const corrLabel = (v: number): string => {
  if (v >= 0.7)  return 'Strong positive';
  if (v >= 0.3)  return 'Moderate positive';
  if (v >= -0.3) return 'Weak / None';
  if (v >= -0.7) return 'Moderate negative';
  return 'Strong negative';
};

// ── COT history bar chart ─────────────────────────────────────────────────────

const COTHistoryChart: React.FC<{ history: { date: string; net: number }[] }> = ({ history }) => (
  <ResponsiveContainer width="100%" height={120}>
    <BarChart data={history} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
      <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} />
      <YAxis tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} />
      <Tooltip
        contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
        formatter={(v: any) => [v.toLocaleString(), 'Net Long']}
        labelStyle={{ color: '#94a3b8' }}
      />
      <ReferenceLine y={0} stroke="#334155" />
      <Bar dataKey="net" radius={[2, 2, 0, 0]}>
        {history.map((entry, i) => (
          <rect key={i} fill={entry.net >= 0 ? '#4ade80' : '#f87171'} />
        ))}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
);

// ── Heatmap tooltip ───────────────────────────────────────────────────────────

const HeatmapTooltip: React.FC<{ cell: HoverCell }> = ({ cell }) => (
  <div style={{
    position: 'fixed', left: cell.x + 12, top: cell.y - 8,
    background: '#0f172a', border: `1px solid ${corrColor(cell.value)}`,
    borderRadius: 8, padding: '8px 12px', fontSize: 12,
    pointerEvents: 'none', zIndex: 9999, minWidth: 160,
    boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
  }}>
    <div style={{ fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>{cell.row} / {cell.col}</div>
    <div style={{ color: corrColor(cell.value), fontSize: 18, fontWeight: 800 }}>{cell.value.toFixed(3)}</div>
    <div style={{ color: '#64748b', marginTop: 2 }}>{corrLabel(cell.value)}</div>
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const CorrelationDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [corr, setCorr]           = useState<CorrelationData | null>(null);
  const [cot, setCot]             = useState<COTData | null>(null);
  const [loading, setLoading]     = useState(true);
  const [loadErr, setLoadErr]     = useState<string | null>(null);
  const [window, setWindow]       = useState(30);
  const [hoverCell, setHoverCell] = useState<HoverCell | null>(null);
  const [drillPair, setDrillPair] = useState<{ row: string; col: string; value: number } | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    const [corrRes, cotRes] = await Promise.allSettled([
      api.get('/advanced/correlation', { params: { window } }),
      api.get('/advanced/cot-sentiment'),
    ]);
    if (!mountedRef.current) return;
    setCorr(corrRes.status === 'fulfilled' ? corrRes.value.data : null);
    setCot(cotRes.status  === 'fulfilled' ? cotRes.value.data  : null);
    if (corrRes.status !== 'fulfilled' && cotRes.status !== 'fulfilled') {
      const reason = (corrRes as PromiseRejectedResult).reason;
      setLoadErr(reason instanceof Error ? reason.message : 'Failed to load correlation data');
    }
    setLoading(false);
  }, [window]);

  useEffect(() => { load(); }, [load]);

  const cotHistory: { date: string; net: number }[] = cot?.history?.length
    ? cot.history.slice(-12)
    : cot ? [{ date: cot.report_date, net: cot.net_speculator_long }] : [];

  return (
    <div style={s.page}>
      <PageHeader
        title="Correlation & Sentiment"
        icon="🔗"
        subtitle="Rolling correlations between gold, FX, equities, and macro indicators."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Analytics', href: '/performance' },
          { label: 'Correlation' },
        ]}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>Window:</span>
            {[14, 30, 60, 90].map(w => (
              <button key={w} style={{ ...s.wBtn, ...(window === w ? s.wBtnActive : {}) }} onClick={() => setWindow(w)}>
                {w}d
              </button>
            ))}
            <div style={{ width: 1, height: 20, background: '#334155', margin: '0 2px' }} />
            <Link to="/geopolitical" style={navLink('#fbbf24')}>🌍 Geopolitical</Link>
            <Link to="/ai-strategy"  style={navLink('#a78bfa')}>🤖 AI Strategy</Link>
            <Link to="/performance"  style={navLink('#4ade80')}>📈 Performance</Link>
          </div>
        }
      />

      {loading ? (
        <div style={s.dim}>
          <div style={s.spinner} />
          <span style={{ marginTop: 12 }}>Loading…</span>
        </div>
      ) : loadErr ? (
        <div style={{ ...s.dim, flexDirection: 'column', gap: 12 }}>
          <span style={{ color: '#f87171' }}>⚠ {loadErr}</span>
          <button onClick={load} style={s.retryBtn}>↻ Retry</button>
        </div>
      ) : (!corr && !cot) ? (
        <div style={{ ...s.dim, flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 40 }}>📊</div>
          <div style={{ color: '#e2e8f0', fontSize: 15 }}>No correlation data available</div>
          <div style={{ color: '#64748b', fontSize: 13 }}>Ensure the data layer is running.</div>
          <button onClick={load} style={{ ...s.retryBtn, marginTop: 8 }}>↻ Retry</button>
        </div>
      ) : (
        <div style={s.grid}>

          {/* ── Heatmap ── */}
          {corr && (
            <div style={{ ...s.card, gridColumn: 'span 2' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
                <div style={s.cardTitle}>Rolling {corr.window}-Day Correlation Matrix</div>
                <div style={{ fontSize: 11, color: '#475569' }}>
                  Updated {new Date(corr.updated_at).toLocaleTimeString()}
                </div>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th style={s.mth} />
                      {corr.symbols.map(sym => <th key={sym} style={s.mth}>{sym}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {corr.symbols.map(row => (
                      <tr key={row}>
                        <td style={{ ...s.mtd, fontWeight: 600, color: '#94a3b8', whiteSpace: 'nowrap' }}>{row}</td>
                        {corr.symbols.map(col => {
                          const v = corr.matrix[row]?.[col] ?? 0;
                          const isDiag = row === col;
                          return (
                            <td
                              key={col}
                              style={{
                                ...s.mtd,
                                background: corrBg(v, isDiag),
                                color: isDiag ? '#94a3b8' : corrColor(v),
                                fontWeight: isDiag ? 700 : 500,
                                cursor: isDiag ? 'default' : 'pointer',
                                transition: 'transform 0.1s, box-shadow 0.1s',
                                position: 'relative',
                              }}
                              onMouseEnter={e => {
                                if (!isDiag) {
                                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                                  setHoverCell({ row, col, value: v, x: rect.right, y: rect.top });
                                  (e.currentTarget as HTMLElement).style.transform = 'scale(1.08)';
                                  (e.currentTarget as HTMLElement).style.boxShadow = `0 0 0 2px ${corrColor(v)}`;
                                }
                              }}
                              onMouseLeave={e => {
                                setHoverCell(null);
                                (e.currentTarget as HTMLElement).style.transform = '';
                                (e.currentTarget as HTMLElement).style.boxShadow = '';
                              }}
                              onClick={() => { if (!isDiag) setDrillPair({ row, col, value: v }); }}
                            >
                              {v.toFixed(2)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Legend */}
              <div style={{ display: 'flex', gap: 16, marginTop: 14, flexWrap: 'wrap' }}>
                {[['≥ 0.7','Strong +','#4ade80'],['0.3–0.7','Moderate +','#86efac'],['-0.3–0.3','Weak / None','#94a3b8'],['-0.7–-0.3','Moderate −','#fca5a5'],['≤ -0.7','Strong −','#f87171']].map(([range, label, color]) => (
                  <div key={range} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                    <div style={{ width: 12, height: 12, borderRadius: 2, background: color }} />
                    <span style={{ color: '#64748b' }}>{range} {label}</span>
                  </div>
                ))}
              </div>

              {/* Insights */}
              {corr.insights.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Key Insights</div>
                    <Link to="/ai-strategy" style={{ background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 6, color: '#a78bfa', fontSize: 11, fontWeight: 700, padding: '4px 10px', textDecoration: 'none' }}>
                      🤖 Build Strategy from Insights
                    </Link>
                  </div>
                  {corr.insights.map((ins, i) => (
                    <div key={i} style={{ fontSize: 13, color: '#94a3b8', padding: '5px 0', borderBottom: '1px solid #0f172a', display: 'flex', gap: 8 }}>
                      <span style={{ color: '#3b82f6', flexShrink: 0 }}>•</span>{ins}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── COT Sentiment ── */}
          {cot && (
            <div style={s.card}>
              <div style={s.cardTitle}>CFTC COT — Gold Speculator Sentiment</div>
              <div style={{ textAlign: 'center', padding: '12px 0 8px' }}>
                <div style={{ fontSize: 32, fontWeight: 800, color: cot.sentiment === 'BULLISH' ? '#4ade80' : '#f87171' }}>{cot.sentiment}</div>
                <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>{cot.sentiment_strength}</div>
              </div>
              {[
                ['Net Long', (cot.net_speculator_long ?? 0) > 0 ? `+${(cot.net_speculator_long ?? 0).toLocaleString()}` : String(cot.net_speculator_long ?? 0), (cot.net_speculator_long ?? 0) > 0 ? '#4ade80' : '#f87171'],
                ['Long Positions', (cot.long_positions ?? 0).toLocaleString(), '#4ade80'],
                ['Short Positions', (cot.short_positions ?? 0).toLocaleString(), '#f87171'],
                ...(cot.weekly_change !== undefined ? [['Weekly Change', `${cot.weekly_change > 0 ? '+' : ''}${cot.weekly_change.toLocaleString()}`, cot.weekly_change > 0 ? '#4ade80' : '#f87171']] : []),
                ['Report Date', cot.report_date, '#94a3b8'],
              ].map(([label, value, color]) => (
                <div key={label} style={s.cotRow}>
                  <span style={s.cotLabel}>{label}</span>
                  <span style={{ color, fontWeight: 600 }}>{value}</span>
                </div>
              ))}
              {cotHistory.length > 1 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 11, color: '#475569', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Net Position History</div>
                  <COTHistoryChart history={cotHistory} />
                </div>
              )}
              <div style={{ fontSize: 12, color: '#475569', marginTop: 12, lineHeight: 1.5 }}>{cot.note}</div>
              <div style={{ fontSize: 11, color: '#334155', marginTop: 6 }}>Source: {cot.source}</div>
              <Link
                to="/trade"
                style={{ marginTop: 16, display: 'block', textAlign: 'center', padding: '9px 0', borderRadius: 8, fontWeight: 700, fontSize: 13, textDecoration: 'none', background: cot.sentiment === 'BULLISH' ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)', border: `1px solid ${cot.sentiment === 'BULLISH' ? 'rgba(74,222,128,0.4)' : 'rgba(248,113,113,0.4)'}`, color: cot.sentiment === 'BULLISH' ? '#4ade80' : '#f87171' }}
              >
                ⚡ Trade XAU/USD — {cot.sentiment}
              </Link>
            </div>
          )}

          <CrossLinkBar title="Related Tools" links={[
            { label: 'AI Strategy Generator', href: '/ai-strategy',      icon: '🤖', color: '#a78bfa' },
            { label: 'Pattern Detector',       href: '/pattern-detector', icon: '🔍', color: '#fbbf24' },
            { label: 'Walk-Forward Analysis',  href: '/walk-forward',     icon: '📊', color: '#60a5fa' },
            { label: 'A/B Testing',            href: '/ab-testing',       icon: '⚗️', color: '#34d399' },
            { label: 'Geopolitical Risk',      href: '/geopolitical',     icon: '🌍', color: '#f59e0b' },
          ]} />
        </div>
      )}

      {hoverCell && <HeatmapTooltip cell={hoverCell} />}

      {/* ── Drill-down modal ── */}
      {drillPair && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setDrillPair(null)}>
          <div style={{ background: '#1e293b', border: `1px solid ${corrColor(drillPair.value)}`, borderRadius: 12, padding: 28, minWidth: 320, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>{drillPair.row} ↔ {drillPair.col}</div>
              <button onClick={() => setDrillPair(null)} style={{ background: 'transparent', border: 'none', color: '#64748b', fontSize: 18, cursor: 'pointer' }}>✕</button>
            </div>
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <div style={{ fontSize: 48, fontWeight: 800, color: corrColor(drillPair.value) }}>{drillPair.value.toFixed(3)}</div>
              <div style={{ fontSize: 14, color: '#64748b', marginTop: 4 }}>{corrLabel(drillPair.value)} correlation</div>
            </div>
            <div style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6, marginTop: 8 }}>
              {drillPair.value >= 0.7 ? `${drillPair.row} and ${drillPair.col} move strongly together. A move in one is a strong signal for the other.`
                : drillPair.value <= -0.7 ? `${drillPair.row} and ${drillPair.col} move in opposite directions. Use as a hedge or divergence signal.`
                : drillPair.value >= 0.3 ? 'Moderate positive relationship. Useful for confirmation but not reliable alone.'
                : drillPair.value <= -0.3 ? 'Moderate negative relationship. Partial hedge potential.'
                : 'Weak or no consistent relationship over the selected window.'}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
              <Link to="/ai-strategy" style={{ flex: 1, textAlign: 'center', padding: '9px 0', background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 13, fontWeight: 600, textDecoration: 'none' }} onClick={() => setDrillPair(null)}>
                🤖 Build Strategy
              </Link>
              <button onClick={() => setDrillPair(null)} style={{ flex: 1, padding: '9px 0', background: '#334155', border: 'none', borderRadius: 7, color: '#94a3b8', fontSize: 13, cursor: 'pointer' }}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const navLink = (color: string): React.CSSProperties => ({
  background: `${color}1a`, border: `1px solid ${color}55`, borderRadius: 6,
  color, fontSize: 12, fontWeight: 600, padding: '5px 12px', textDecoration: 'none',
});

const s: Record<string, React.CSSProperties> = {
  page:     { minHeight: '100vh', background: '#0f172a', color: '#f8fafc', fontFamily: "'Inter',system-ui,sans-serif", padding: 24 },
  grid:     { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 20 },
  card:     { background: '#1e293b', borderRadius: 12, padding: 24, border: '1px solid #334155' },
  cardTitle:{ fontSize: 13, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 },
  mth:      { padding: '8px 12px', color: '#64748b', fontWeight: 600, textAlign: 'center', whiteSpace: 'nowrap', borderBottom: '1px solid #334155' },
  mtd:      { padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid #0f172a' },
  cotRow:   { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid #0f172a', fontSize: 13 },
  cotLabel: { color: '#64748b', fontSize: 12 },
  wBtn:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#64748b', padding: '5px 10px', fontSize: 12, cursor: 'pointer', fontFamily: 'inherit' },
  wBtnActive:{ background: '#3b82f6', border: '1px solid #3b82f6', color: '#fff' },
  dim:      { color: '#475569', textAlign: 'center', padding: 64, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  spinner:  { width: 32, height: 32, border: '3px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.8s linear infinite' },
  retryBtn: { background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '6px 16px', fontFamily: 'inherit' },
};

export default CorrelationDashboard;
