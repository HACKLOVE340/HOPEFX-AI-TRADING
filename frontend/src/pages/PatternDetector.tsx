/**
 * Pattern Detector (Task: AI-powered chart pattern recognition)
 *
 * Calls GET /api/trading/patterns and displays detected patterns
 * with confidence bars, entry/target/stop prices, and R:R ratio.
 */

import { PageShell } from '../components/system/PageShell';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { RelatedPages } from '../components';
import { AlertTriangle, BarChart3, BookOpen, Bot, Brain, Cpu, Radar, ScanSearch, Search, Shield, TrendingDown } from 'lucide-react';
import { tradingApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

interface DetectedPattern {
  pattern_type: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  entry_price: number;
  target_price: number;
  stop_loss: number;
  start_index: number;
  end_index: number;
  description: string;
}

interface PatternResponse {
  patterns: DetectedPattern[];
  symbol: string;
  count: number;
  /**
   * Set by the backend only when detection could not run — no OHLCV bars for
   * this symbol/timeframe, or fewer than the ~20 needed. Absent on a genuine
   * negative result. The two are completely different statements and must not
   * render the same way: "no patterns above 50%" reads as a confident finding,
   * and showing it when nothing was ever analysed is a failure dressed as a fact.
   */
  note?: string;
  /** Bars actually available, when the backend reports too few. */
  bars?: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'XAG/USD', 'EUR/USD', 'GBP/USD', 'BTC/USD', 'ETH/USD'] as const;
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;

/** snake_case / camelCase / PascalCase → Title Case with ampersand variants */
function formatPatternName(raw: string): string {
  return raw
    .replace(/_/g, ' ')                       // snake_case → spaces
    .replace(/([a-z])([A-Z])/g, '$1 $2')      // camelCase → spaced
    .replace(/\band\b/gi, '&')                // "and" → "&"
    .replace(/\b\w/g, (c) => c.toUpperCase()) // Title Case
    .trim();
}

const fmtPrice = (n: number): string =>
  Number.isFinite(n) ? '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';

function confidenceColor(c: number): string {
  if (c >= 0.7) return '#4ade80';
  if (c >= 0.5) return '#facc15';
  return '#f87171';
}

function riskReward(entry: number, target: number, stop: number): string {
  if (![entry, target, stop].every(Number.isFinite)) return '—';
  const denom = Math.abs(stop - entry);
  if (denom === 0) return '—';
  const ratio = Math.abs(target - entry) / denom;
  return Number.isFinite(ratio) ? ratio.toFixed(2) : '—';
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

interface PatternCardProps {
  pattern: DetectedPattern;
  symbol: string;
  onTrade: (p: DetectedPattern) => void;
}

const PatternCard: React.FC<PatternCardProps> = ({ pattern, symbol, onTrade }) => {
  const bullish = pattern.direction === 'bullish';
  const neutral = pattern.direction === 'neutral';
  const dirColor = neutral ? '#94a3b8' : bullish ? '#4ade80' : '#f87171';
  const barColor = confidenceColor(pattern.confidence);
  const pct = Math.round(pattern.confidence * 100);

  return (
    <div style={s.card}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-strong)' }}>
          {formatPatternName(pattern.pattern_type)}
        </div>
        <span style={{
          fontSize: 'var(--fs-label)', fontWeight: 700, padding: '3px 8px', borderRadius: 20,
          background: neutral ? 'var(--raised)' : bullish ? '#14532d' : '#450a0a',
          color: dirColor,
          border: `1px solid ${neutral ? '#334155' : bullish ? '#166534' : '#7f1d1d'}`,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}>
          {pattern.direction}
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
          <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)' }}>Confidence</span>
          <span style={{ fontSize: 'var(--fs-body)', fontWeight: 700, color: barColor }}>{pct}%</span>
        </div>
        <div style={{ height: 6, borderRadius: 4, background: 'var(--surface)', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 4, transition: 'width 0.4s ease' }} />
        </div>
      </div>

      {/* Price levels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8, marginBottom: 14 }}>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Entry</span>
          <span style={{ ...s.priceVal, color: 'var(--text-strong)' }}>{fmtPrice(pattern.entry_price)}</span>
        </div>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Target</span>
          <span style={{ ...s.priceVal, color: 'var(--gain)' }}>{fmtPrice(pattern.target_price)}</span>
        </div>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Stop Loss</span>
          <span style={{ ...s.priceVal, color: 'var(--loss)' }}>{fmtPrice(pattern.stop_loss)}</span>
        </div>
      </div>

      {/* R:R + description */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 'var(--fs-body)', color: 'var(--text-muted)' }}>R:R</span>
        <span style={{ fontSize: 'var(--fs-body)', fontWeight: 700, color: 'var(--text-strong)' }}>
          {riskReward(pattern.entry_price, pattern.target_price, pattern.stop_loss)}
        </span>
        <span style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', marginLeft: 'auto' }}>
          Bars {pattern.start_index}–{pattern.end_index}
        </span>
      </div>

      {pattern.description && (
        <p style={{ margin: 0, fontSize: 'var(--fs-body)', color: 'var(--text-dim)', lineHeight: 1.6, marginBottom: 12 }}>
          {pattern.description}
        </p>
      )}

      {pattern.confidence >= 0.5 && !neutral && (
        <button
          onClick={() => onTrade(pattern)}
          style={{
            width: '100%', padding: '8px 0', borderRadius: 7, cursor: 'pointer', fontWeight: 700,
            fontSize: 'var(--fs-body)', fontFamily: 'inherit',
            background: bullish ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)',
            border: `1px solid ${bullish ? 'rgba(74,222,128,0.4)' : 'rgba(248,113,113,0.4)'}`,
            color: bullish ? 'var(--gain)' : 'var(--loss)',
          }}
        >
          <Cpu size={14} strokeWidth={2} aria-hidden /> {bullish ? 'BUY' : 'SELL'} {symbol} — trade this pattern
        </button>
      )}
      {pattern.confidence >= 0.5 && neutral && (
        <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-muted)', textAlign: 'center', padding: '6px 0' }}>
          Direction unconfirmed — await breakout before trading
        </div>
      )}
    </div>
  );
};

// ─── Main page ────────────────────────────────────────────────────────────────

const PatternDetector: React.FC = () => {
  const navigate = useNavigate();
  const [symbol, setSymbol]     = useState<string>('XAU/USD');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [minConf, setMinConf]   = useState<number>(0.5);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [data, setData]         = useState<PatternResponse | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const scan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await tradingApi.patterns(symbol, timeframe, 200, minConf);
      if (!mountedRef.current) return;
      setData(res.data as PatternResponse);
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = extractApiError(err, 'Failed to scan patterns');
      setError(msg);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [symbol, timeframe, minConf]);

  const handleTrade = (p: DetectedPattern) => {
    navigate('/trade', {
      state: {
        signal: {
          symbol,
          direction: p.direction === 'bullish' ? 'BUY' : 'SELL',
          stop_loss: p.stop_loss,
          take_profit: p.target_price,
        }
      }
    });
  };

  // Auto-scan on mount and when params change
  useEffect(() => { scan(); }, [scan]);

  return (
    <PageShell
      width="wide" title="Pattern Detector"
      subtitle="AI-powered chart pattern recognition for XAU/USD and major instruments"
      actions={<><div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => navigate('/ai-chart')} style={s.navBtn}>
            <Brain size="1em" aria-hidden /> AI Chart
          </button>
          <button onClick={() => navigate('/ai-strategy')} style={s.navBtn}>
            <Bot size="1em" aria-hidden /> AI Strategy
          </button>
          <button onClick={() => navigate('/risk-calculator')} style={s.navBtn}>
            <Shield size="1em" aria-hidden /> Risk Calc
          </button>
        </div>

        {/* Controls */}
        <div style={s.controls}>
          {/* Symbol */}
          <div style={s.controlGroup}>
            <label style={s.controlLabel}>Symbol</label>
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              style={s.select}
            >
              {SYMBOLS.map(sym => (
                <option key={sym} value={sym}>{sym}</option>
              ))}
            </select>
          </div>

          {/* Timeframe */}
          <div style={s.controlGroup}>
            <label style={s.controlLabel}>Timeframe</label>
            <div style={{ display: 'flex', gap: 4 }}>
              {TIMEFRAMES.map(tf => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  style={{ ...s.tfBtn, ...(timeframe === tf ? s.tfBtnActive : {}) }}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* Confidence threshold */}
          <div style={s.controlGroup}>
            <label id="patterndetector-min-confidence-label" htmlFor="patterndetector-min-confidence" style={s.controlLabel}>
              Min Confidence: <span style={{ color: 'var(--text-strong)', fontWeight: 700 }}>{Math.round(minConf * 100)}%</span>
            </label>
            <input id="patterndetector-min-confidence" aria-labelledby="patterndetector-min-confidence-label"
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={minConf}
              onChange={e => setMinConf(parseFloat(e.target.value))}
              style={{ width: 140, accentColor: '#3b82f6', cursor: 'pointer' }}
            />
          </div>

          {/* Scan button */}
          <button
            onClick={scan}
            disabled={loading}
            style={{ ...s.scanBtn, ...(loading ? s.scanBtnDisabled : {}) }}
          >
            {loading ? 'Scanning…' : <><ScanSearch size={14} strokeWidth={2} aria-hidden /> Scan</>}
          </button>
        </div></>}
    >
      {/* Header */}


      {/* Body */}
      {loading ? (
        <div style={s.center}>
          <div style={s.spinner} />
          <span style={{ color: 'var(--text-dim)', fontSize: 14, marginTop: 12 }}>Scanning patterns…</span>
        </div>
      ) : error ? (
        <div style={{ ...s.center, gap: 12 }}>
          <span style={{ color: 'var(--loss)', fontSize: 14 }}><AlertTriangle size="1em" aria-hidden /> {error}</span>
          <button onClick={scan} style={s.retryBtn}>Retry</button>
        </div>
      ) : data ? (
        (data.patterns ?? []).length === 0 ? (
          data.note ? (
            /* Detection never ran — say so, rather than reporting a clean negative. */
            <div style={s.center}>
              <span style={{ fontSize: 32, marginBottom: 12 }}><TrendingDown size="1em" aria-hidden /></span>
              <p style={{ color: '#facc15', fontSize: 14, textAlign: 'center', maxWidth: 460, lineHeight: 1.7 }}>
                Insufficient price history for{' '}
                <strong style={{ color: '#fde68a' }}>{data.symbol}</strong> / {timeframe}
                {typeof data.bars === 'number' ? ` — only ${data.bars} bar${data.bars === 1 ? '' : 's'}` : ''}.
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: 'var(--fs-body)', textAlign: 'center', maxWidth: 460, lineHeight: 1.7 }}>
                {data.note}
              </p>
              <button onClick={scan} style={s.retryBtn}>Retry</button>
            </div>
          ) : (
            <div style={s.center}>
              <span style={{ fontSize: 32, marginBottom: 12 }}><Search size="1em" aria-hidden /></span>
              <p style={{ color: 'var(--text-muted)', fontSize: 14, textAlign: 'center', maxWidth: 420, lineHeight: 1.7 }}>
                No patterns detected above{' '}
                <strong style={{ color: 'var(--text-dim)' }}>{Math.round(minConf * 100)}%</strong>{' '}
                confidence threshold. Try lowering the threshold or switching timeframe.
              </p>
            </div>
          )
        ) : (
          <div>
            <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-muted)', marginBottom: 16 }}>
              Found <strong style={{ color: 'var(--text-dim)' }}>{data.count}</strong> pattern{data.count !== 1 ? 's' : ''} on{' '}
              <strong style={{ color: 'var(--text-dim)' }}>{data.symbol}</strong> / {timeframe}
            </div>
            <div style={s.grid}>
              {(data.patterns ?? []).map((p, i) => (
                <PatternCard key={`${p.pattern_type}-${p.start_index}-${i}`} pattern={p} symbol={symbol} onTrade={handleTrade} />
              ))}
            </div>
          </div>
        )
      ) : null}
      <RelatedPages
        links={[
          { to: '/ai-chart', label: 'Charts', hint: 'See the pattern on the chart', icon: BarChart3 },
          { to: '/trade', label: 'Trading ticket', hint: 'Act on a detected pattern', icon: Cpu },
          { to: '/signals', label: 'Signal feed', hint: 'What the model is publishing', icon: Radar },
          { to: '/journal', label: 'Trade journal', hint: 'Whether patterns worked for you', icon: BookOpen },
        ]}
      />

    </PageShell>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:    { minHeight: '100vh', background: 'var(--surface)', color: 'var(--text-strong)', fontFamily: "'Inter',system-ui,sans-serif", padding: 24 },
  header:  { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28, flexWrap: 'wrap', gap: 20 },
  title:   { fontSize: 'var(--fs-hero)', fontWeight: 700, margin: 0 },
  subtitle:{ fontSize: 14, color: 'var(--text-dim)', marginTop: 4 },

  controls: { display: 'flex', alignItems: 'flex-end', gap: 20, flexWrap: 'wrap' },
  controlGroup: { display: 'flex', flexDirection: 'column', gap: 6 },
  controlLabel: { fontSize: 'var(--fs-body)', color: 'var(--text-muted)', fontWeight: 600 },

  select: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 6,
    color: 'var(--text-strong)', fontSize: 'var(--fs-body)', padding: '6px 10px', cursor: 'pointer',
    outline: 'none',
  },

  tfBtn: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 6,
    color: 'var(--text-muted)', fontSize: 'var(--fs-body)', padding: '5px 9px', cursor: 'pointer',
    fontWeight: 500,
  },
  tfBtnActive: { background: '#3b82f6', border: '1px solid #3b82f6', color: '#fff' },

  scanBtn: {
    background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', fontSize: 14, fontWeight: 600,
    padding: '9px 22px', cursor: 'pointer', whiteSpace: 'nowrap',
  },
  scanBtnDisabled: { opacity: 0.6, cursor: 'not-allowed' },

  retryBtn: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 6,
    color: 'var(--text-dim)', cursor: 'pointer', fontSize: 'var(--fs-body)', padding: '6px 18px',
  },

  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(320px,1fr))', gap: 20 },

  card: { background: 'var(--raised)', borderRadius: 12, padding: 22, border: '1px solid var(--border-strong)' },

  priceCell:  { background: 'var(--surface)', borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 },
  priceLabel: { fontSize: 'var(--fs-label)', color: 'var(--text-faint)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' },
  priceVal:   { fontSize: 14, fontWeight: 700 },

  center: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 64, gap: 8 },
  spinner: {
    width: 32, height: 32,
    border: '3px solid var(--border-strong)',
    borderTopColor: '#3b82f6',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  navBtn: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 7,
    color: 'var(--text-dim)', cursor: 'pointer', fontSize: 'var(--fs-body)', fontWeight: 600,
    padding: '6px 14px', fontFamily: 'inherit',
  },
};

export default PatternDetector;
