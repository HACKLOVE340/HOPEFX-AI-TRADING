/**
 * Pattern Detector (Task: AI-powered chart pattern recognition)
 *
 * Calls GET /api/trading/patterns and displays detected patterns
 * with confidence bars, entry/target/stop prices, and R:R ratio.
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PageHeader } from '../components';
import { tradingApi, signalsApi } from '../hooks/useApi';
import { useToast } from '../components/Toast';

// ─── Types ────────────────────────────────────────────────────────────────────

interface DetectedPattern {
  pattern_type: string;
  direction: 'bullish' | 'bearish';
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
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SYMBOLS = ['XAU/USD', 'XAG/USD', 'EUR/USD', 'GBP/USD', 'BTC/USD', 'ETH/USD'] as const;
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;

/** CamelCase / PascalCase → Title Case with ampersand variants */
function formatPatternName(raw: string): string {
  return raw
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace('And', '&')
    .trim();
}

const fmtPrice = (n: number): string =>
  '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function confidenceColor(c: number): string {
  if (c >= 0.7) return '#4ade80';
  if (c >= 0.5) return '#facc15';
  return '#f87171';
}

function riskReward(entry: number, target: number, stop: number): string {
  const denom = Math.abs(stop - entry);
  if (denom === 0) return '—';
  return (Math.abs(target - entry) / denom).toFixed(2);
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

interface PatternCardProps {
  pattern: DetectedPattern;
  symbol: string;
  onTrade: (p: DetectedPattern) => void;
  onAlert: (p: DetectedPattern) => void;
  alertSet: boolean;
}

const PatternCard: React.FC<PatternCardProps> = ({ pattern, symbol, onTrade, onAlert, alertSet }) => {
  const bullish = pattern.direction === 'bullish';
  const dirColor = bullish ? '#4ade80' : '#f87171';
  const barColor = confidenceColor(pattern.confidence);
  const pct = Math.round(pattern.confidence * 100);

  return (
    <div style={s.card}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>
          {formatPatternName(pattern.pattern_type)}
        </div>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 20,
          background: bullish ? '#14532d' : '#450a0a',
          color: dirColor,
          border: `1px solid ${bullish ? '#166534' : '#7f1d1d'}`,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}>
          {pattern.direction}
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Confidence</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: barColor }}>{pct}%</span>
        </div>
        <div style={{ height: 6, borderRadius: 4, background: '#0f172a', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 4, transition: 'width 0.4s ease' }} />
        </div>
      </div>

      {/* Price levels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 14 }}>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Entry</span>
          <span style={{ ...s.priceVal, color: '#f1f5f9' }}>{fmtPrice(pattern.entry_price)}</span>
        </div>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Target</span>
          <span style={{ ...s.priceVal, color: '#4ade80' }}>{fmtPrice(pattern.target_price)}</span>
        </div>
        <div style={s.priceCell}>
          <span style={s.priceLabel}>Stop Loss</span>
          <span style={{ ...s.priceVal, color: '#f87171' }}>{fmtPrice(pattern.stop_loss)}</span>
        </div>
      </div>

      {/* R:R + description */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 12, color: '#64748b' }}>R:R</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>
          {riskReward(pattern.entry_price, pattern.target_price, pattern.stop_loss)}
        </span>
        <span style={{ fontSize: 11, color: '#475569', marginLeft: 'auto' }}>
          Bars {pattern.start_index}–{pattern.end_index}
        </span>
      </div>

      {pattern.description && (
        <p style={{ margin: 0, fontSize: 12, color: '#94a3b8', lineHeight: 1.6, marginBottom: 12 }}>
          {pattern.description}
        </p>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        {pattern.confidence >= 0.5 && (
          <button
            onClick={() => onTrade(pattern)}
            style={{
              flex: 1, padding: '8px 0', borderRadius: 7, cursor: 'pointer', fontWeight: 700,
              fontSize: 13, fontFamily: 'inherit',
              background: bullish ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)',
              border: `1px solid ${bullish ? 'rgba(74,222,128,0.4)' : 'rgba(248,113,113,0.4)'}`,
              color: bullish ? '#4ade80' : '#f87171',
            }}
          >
            ⚡ {bullish ? 'BUY' : 'SELL'} {symbol}
          </button>
        )}
        <button
          onClick={() => onAlert(pattern)}
          title={alertSet ? 'Alert set' : 'Set alert for this pattern'}
          style={{
            padding: '8px 12px', borderRadius: 7, cursor: 'pointer', fontWeight: 700,
            fontSize: 13, fontFamily: 'inherit',
            background: alertSet ? 'rgba(251,191,36,0.18)' : 'rgba(251,191,36,0.08)',
            border: `1px solid ${alertSet ? 'rgba(251,191,36,0.6)' : 'rgba(251,191,36,0.25)'}`,
            color: '#fbbf24',
            transition: 'all 0.15s',
          }}
        >
          {alertSet ? '🔔 Alert Set' : '🔔'}
        </button>
      </div>
    </div>
  );
};

// ─── Main page ────────────────────────────────────────────────────────────────

const PatternDetector: React.FC = () => {
  const navigate = useNavigate();
  const toast    = useToast();
  const [symbol, setSymbol]       = useState<string>('XAU/USD');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [minConf, setMinConf]     = useState<number>(0.5);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [data, setData]           = useState<PatternResponse | null>(null);
  const [alertedKeys, setAlertedKeys] = useState<Set<string>>(new Set());

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
      const msg = err instanceof Error ? err.message : 'Failed to scan patterns';
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
        },
      },
    });
  };

  const handleAlert = useCallback(async (p: DetectedPattern) => {
    const key = `${p.pattern_type}-${p.start_index}`;
    if (alertedKeys.has(key)) return;
    try {
      await signalsApi.setAlert({
        symbol,
        timeframe,
        pattern_type: p.pattern_type,
        direction: p.direction,
        confidence_threshold: p.confidence,
        entry_price: p.entry_price,
        target_price: p.target_price,
        stop_loss: p.stop_loss,
      });
      setAlertedKeys(prev => new Set([...prev, key]));
      toast.success(`Alert set for ${formatPatternName(p.pattern_type)} on ${symbol}`);
    } catch {
      toast.error('Failed to set alert. Check your connection.');
    }
  }, [alertedKeys, symbol, timeframe, toast]);

  // Auto-scan on mount and when params change
  useEffect(() => { scan(); }, [scan]);

  return (
    <div style={s.page}>
      <PageHeader
        title="Pattern Detector"
        icon="🔍"
        subtitle="AI-powered chart pattern recognition for XAU/USD and major instruments"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'AI Strategy', href: '/ai-strategy' },
          { label: 'Pattern Detector' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Link to="/ai-chart-dashboard" style={s.navLink}>📈 AI Charts</Link>
            <Link to="/ai-strategy"        style={s.navLink}>🤖 AI Strategy</Link>
            <Link to="/walk-forward"       style={s.navLink}>📊 Walk-Forward</Link>
            <Link to="/risk-calculator"    style={s.navLink}>🛡 Risk Calc</Link>
            <Link to="/correlation"        style={s.navLink}>📊 Correlation</Link>
          </div>
        }
      />
      <div style={s.header}>

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
            <label style={s.controlLabel}>
              Min Confidence: <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{Math.round(minConf * 100)}%</span>
            </label>
            <input
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
            {loading ? 'Scanning…' : '🔍 Scan'}
          </button>
        </div>
      </div>

      {/* Body */}
      {loading ? (
        <div style={s.center}>
          <div style={s.spinner} />
          <span style={{ color: '#94a3b8', fontSize: 14, marginTop: 12 }}>Scanning patterns…</span>
        </div>
      ) : error ? (
        <div style={{ ...s.center, gap: 12 }}>
          <span style={{ color: '#f87171', fontSize: 14 }}>⚠ {error}</span>
          <button onClick={scan} style={s.retryBtn}>Retry</button>
        </div>
      ) : data ? (
        data.patterns.length === 0 ? (
          <div style={s.center}>
            <span style={{ fontSize: 32, marginBottom: 12 }}>🔍</span>
            <p style={{ color: '#64748b', fontSize: 14, textAlign: 'center', maxWidth: 420, lineHeight: 1.7 }}>
              No patterns detected above{' '}
              <strong style={{ color: '#94a3b8' }}>{Math.round(minConf * 100)}%</strong>{' '}
              confidence threshold. Try lowering the threshold or switching timeframe.
            </p>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
              Found <strong style={{ color: '#94a3b8' }}>{data.count}</strong> pattern{data.count !== 1 ? 's' : ''} on{' '}
              <strong style={{ color: '#94a3b8' }}>{data.symbol}</strong> / {timeframe}
            </div>
            <div style={s.grid}>
              {data.patterns.map((p, i) => {
                const key = `${p.pattern_type}-${p.start_index}`;
                return (
                  <PatternCard
                    key={`${key}-${i}`}
                    pattern={p}
                    symbol={symbol}
                    onTrade={handleTrade}
                    onAlert={handleAlert}
                    alertSet={alertedKeys.has(key)}
                  />
                );
              })}
            </div>
          </div>
        )
      ) : null}
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:    { minHeight: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: "'Inter',system-ui,sans-serif", padding: 24 },
  header:  { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28, flexWrap: 'wrap', gap: 20 },
  title:   { fontSize: 28, fontWeight: 700, margin: 0 },
  subtitle:{ fontSize: 14, color: '#94a3b8', marginTop: 4 },

  controls: { display: 'flex', alignItems: 'flex-end', gap: 20, flexWrap: 'wrap' },
  controlGroup: { display: 'flex', flexDirection: 'column', gap: 6 },
  controlLabel: { fontSize: 12, color: '#64748b', fontWeight: 600 },

  select: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#f1f5f9', fontSize: 13, padding: '6px 10px', cursor: 'pointer',
    outline: 'none',
  },

  tfBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#64748b', fontSize: 12, padding: '5px 9px', cursor: 'pointer',
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
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '6px 18px',
  },

  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(320px,1fr))', gap: 20 },

  card: { background: '#1e293b', borderRadius: 12, padding: 22, border: '1px solid #334155' },

  priceCell:  { background: '#0f172a', borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 },
  priceLabel: { fontSize: 11, color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' },
  priceVal:   { fontSize: 14, fontWeight: 700 },

  center: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 64, gap: 8 },
  spinner: {
    width: 32, height: 32,
    border: '3px solid #334155',
    borderTopColor: '#3b82f6',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite',
  },
  navBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 7,
    color: '#94a3b8', cursor: 'pointer', fontSize: 12, fontWeight: 600,
    padding: '6px 14px', fontFamily: 'inherit',
  },
  navLink: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 7,
    color: '#94a3b8', fontSize: 12, fontWeight: 600,
    padding: '6px 14px', textDecoration: 'none', display: 'inline-block',
  },
};

export default PatternDetector;
