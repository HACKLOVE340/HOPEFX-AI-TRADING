/**
 * NuclearMobileView.tsx
 * Mobile-responsive nuclear dashboard — stacked single-column layout.
 * Optimised for screens < 768px: touch-friendly, minimal chrome.
 */

import React, { memo, useState, useCallback } from 'react';
import { useNuclearStore } from '../store/nuclear-store';
import { useNuclearWS } from '../hooks/useNuclearWS';
import { useStore } from '../../../store';
import { fmtPrice, fmtPctRaw, fmtPnl } from '../../../lib/utils';
import { severityColor, actionColor } from '../types/nuclear';
import NuclearCandleChart from './NuclearCandleChart';
import NuclearAlertOverlay from './NuclearAlertOverlay';

// ─── Mobile gauge strip ───────────────────────────────────────────────────────

const MobileGaugeStrip = memo(() => {
  const nuclear = useNuclearStore((s) => s.nuclear);
  const gauge   = useNuclearStore((s) => s.gauge);
  const severity = nuclear?.severity ?? 0;
  const color    = severityColor(severity);
  const isAlert  = severity >= 7;

  return (
    <div style={{
      ...ms.gaugeStrip,
      borderColor: color,
      background: isAlert ? `rgba(255,0,51,0.1)` : `rgba(0,255,136,0.04)`,
    }}>
      <div style={{ ...ms.severityCircle, background: color, boxShadow: `0 0 10px ${color}` }}>
        {severity}
      </div>
      <div style={ms.gaugeCenter}>
        <div style={ms.gaugeTrack}>
          <div style={{
            ...ms.gaugeFill,
            width: `${(gauge?.score ?? 0)}%`,
            background: `linear-gradient(90deg, #00ff88, ${color})`,
          }} />
        </div>
        <span style={{ ...ms.gaugeLabel, color }}>
          {gauge?.label ?? 'NORMAL'} · {nuclear?.rl_action_label ?? 'NORMAL'}
        </span>
      </div>
      <div style={{ ...ms.actionBadge, borderColor: actionColor(nuclear?.action ?? 'normal'), color: actionColor(nuclear?.action ?? 'normal') }}>
        {(nuclear?.action ?? 'normal').replace(/_/g, ' ').toUpperCase().slice(0, 6)}
      </div>
    </div>
  );
});

// ─── Mobile price bar ─────────────────────────────────────────────────────────

const MobilePriceBar = memo(() => {
  const price = useNuclearStore((s) => s.price);
  if (!price) return null;
  const chg = price.change_pct ?? 0;
  return (
    <div style={ms.priceBar}>
      <span style={ms.symbol}>XAU/USD</span>
      <span style={ms.price}>{fmtPrice(price.mid)}</span>
      <span style={{ ...ms.change, color: chg >= 0 ? '#00ff88' : '#ef4444' }}>
        {fmtPctRaw(chg * 100, 3)}
      </span>
    </div>
  );
});

// ─── Mobile explain accordion ─────────────────────────────────────────────────

const MobileExplainAccordion = memo(() => {
  const [open, setOpen] = useState(false);
  const nuclear = useNuclearStore((s) => s.nuclear);
  const risk    = useNuclearStore((s) => s.risk);

  if (!nuclear) return null;

  return (
    <div style={ms.accordion}>
      <button style={ms.accordionBtn} onClick={() => setOpen((o) => !o)}>
        <span style={ms.accordionTitle}>AI EXPLANATION</span>
        <span style={ms.accordionChevron}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={ms.accordionBody}>
          <p style={ms.explainText}>{nuclear.explanation}</p>
          {nuclear.historical_analog && (
            <div style={ms.analogBox}>
              <span style={ms.analogLabel}>📊 HISTORICAL ANALOG</span>
              <p style={ms.analogText}>{nuclear.historical_analog}</p>
            </div>
          )}
          {risk && (
            <div style={ms.riskGrid}>
              <MobileRiskCell label="CVaR 95%" value={fmtPctRaw(risk.cvar_95 * 100, 2)} />
              <MobileRiskCell label="Exposure" value={fmtPctRaw(risk.exposure * 100, 1)} />
              <MobileRiskCell label="Drawdown" value={fmtPctRaw(risk.drawdown_pct, 2)} />
              <MobileRiskCell label="Daily P&L" value={fmtPnl(risk.daily_pnl)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
});

const MobileRiskCell = memo(({ label, value }: { label: string; value: string }) => (
  <div style={ms.riskCell}>
    <span style={ms.riskLabel}>{label}</span>
    <span style={ms.riskValue}>{value}</span>
  </div>
));

// ─── Mobile signal list ───────────────────────────────────────────────────────

const MobileSignalList = memo(() => {
  const signals = useNuclearStore((s) => s.signals).slice(0, 3);
  if (!signals.length) return null;

  return (
    <div style={ms.signalList}>
      <div style={ms.sectionTitle}>SIGNALS</div>
      {signals.map((sig) => (
        <div key={sig.id} style={ms.signalRow}>
          <span style={{
            ...ms.signalDir,
            color: sig.direction === 'long' ? '#00ff88' : sig.direction === 'short' ? '#ef4444' : '#64748b',
          }}>
            {sig.direction.toUpperCase()}
          </span>
          <span style={ms.signalModel}>{sig.model}</span>
          <span style={ms.signalConf}>{(sig.confidence * 100).toFixed(0)}%</span>
          <span style={ms.signalEntry}>{sig.entry.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
});

// ─── Main mobile view ─────────────────────────────────────────────────────────

const NuclearMobileView = memo(() => {
  const isAuth = useStore((s) => s.token !== null);
  const { status } = useNuclearWS(isAuth);
  const protectedView = useNuclearStore((s) => s.protectedView);

  return (
    <div style={ms.root}>
      <NuclearAlertOverlay />

      {/* Status dot */}
      <div style={ms.statusBar}>
        <span style={{
          ...ms.statusDot,
          background: status === 'connected' ? '#00ff88' : status === 'connecting' ? '#fbbf24' : '#ef4444',
        }} />
        <span style={ms.statusText}>
          {status === 'connected' ? 'LIVE' : status.toUpperCase()}
        </span>
        <span style={ms.statusNote}>HOPEFX Nuclear · Paper</span>
      </div>

      {protectedView && (
        <div style={ms.protectedBar}>
          🔒 PROTECTED VIEW — Trading halted
        </div>
      )}

      <MobileGaugeStrip />
      <MobilePriceBar />

      {/* Chart — fixed height on mobile */}
      <div style={ms.chartWrap}>
        <NuclearCandleChart />
      </div>

      <MobileExplainAccordion />
      <MobileSignalList />
    </div>
  );
});

export default NuclearMobileView;

// ─── Styles ───────────────────────────────────────────────────────────────────

const ms: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex', flexDirection: 'column',
    height: '100%', width: '100%',
    background: '#020408', color: '#f1f5f9',
    fontFamily: 'monospace, system-ui', overflow: 'hidden',
  },
  statusBar: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '4px 12px', background: '#060d18',
    borderBottom: '1px solid #0a1628', flexShrink: 0,
  },
  statusDot: { width: 6, height: 6, borderRadius: '50%' },
  statusText: { fontSize: 10, fontWeight: 700, letterSpacing: 1 },
  statusNote: { fontSize: 10, color: '#334155', marginLeft: 'auto' },
  protectedBar: {
    padding: '6px 12px', background: 'rgba(255,0,51,0.15)',
    borderBottom: '1px solid #ff0033',
    fontSize: 11, color: '#fca5a5', fontWeight: 700, flexShrink: 0,
  },
  gaugeStrip: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '8px 12px', borderBottom: '2px solid',
    flexShrink: 0, transition: 'all 0.4s ease',
  },
  severityCircle: {
    width: 36, height: 36, borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 16, fontWeight: 900, color: '#000', flexShrink: 0,
  },
  gaugeCenter: { flex: 1, display: 'flex', flexDirection: 'column', gap: 4 },
  gaugeTrack: { height: 4, background: '#1a2e4a', borderRadius: 2, overflow: 'hidden' },
  gaugeFill: { height: '100%', borderRadius: 2, transition: 'width 0.6s ease' },
  gaugeLabel: { fontSize: 10, fontWeight: 700, letterSpacing: 1 },
  actionBadge: {
    fontSize: 9, fontWeight: 800, padding: '3px 6px',
    border: '1px solid', borderRadius: 3, flexShrink: 0,
  },
  priceBar: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '8px 12px', borderBottom: '1px solid #0a1628', flexShrink: 0,
  },
  symbol: { fontSize: 12, fontWeight: 800, color: '#f59e0b' },
  price:  { fontSize: 22, fontWeight: 900, color: '#f1f5f9', flex: 1 },
  change: { fontSize: 12, fontWeight: 700 },
  chartWrap: { height: 280, flexShrink: 0, position: 'relative' },
  accordion: {
    borderBottom: '1px solid #0a1628', flexShrink: 0,
  },
  accordionBtn: {
    width: '100%', display: 'flex', justifyContent: 'space-between',
    alignItems: 'center', padding: '10px 12px',
    background: 'transparent', border: 'none', color: '#94a3b8',
    cursor: 'pointer', fontSize: 11, fontWeight: 700, letterSpacing: 1.5,
  },
  accordionTitle: { letterSpacing: 2 },
  accordionChevron: { fontSize: 10, color: '#475569' },
  accordionBody: { padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 10 },
  explainText: { fontSize: 12, color: '#cbd5e1', lineHeight: 1.7, margin: 0 },
  analogBox: {
    background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.2)',
    borderRadius: 6, padding: '8px 10px',
  },
  analogLabel: { fontSize: 9, color: '#fbbf24', letterSpacing: 2, fontWeight: 700, display: 'block', marginBottom: 4 },
  analogText: { fontSize: 11, color: '#cbd5e1', lineHeight: 1.6, margin: 0 },
  riskGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 },
  riskCell: { display: 'flex', flexDirection: 'column', gap: 2 },
  riskLabel: { fontSize: 9, color: '#475569', letterSpacing: 1 },
  riskValue: { fontSize: 13, fontWeight: 700, color: '#94a3b8', fontFamily: 'monospace' },
  signalList: { padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 },
  sectionTitle: { fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700, marginBottom: 4 },
  signalRow: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '6px 0', borderBottom: '1px solid #0a1628',
  },
  signalDir:   { fontSize: 11, fontWeight: 800, width: 40 },
  signalModel: { fontSize: 10, color: '#64748b', flex: 1 },
  signalConf:  { fontSize: 11, fontFamily: 'monospace', color: '#94a3b8' },
  signalEntry: { fontSize: 11, fontFamily: 'monospace', color: '#f1f5f9' },
};
