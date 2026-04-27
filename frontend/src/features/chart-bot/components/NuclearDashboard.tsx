/**
 * NuclearDashboard.tsx
 * Master nuclear-grade trading dashboard layout.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────┐
 *   │  NuclearGeopoliticalBanner (top, full-width)        │
 *   ├──────────────────────────────────┬──────────────────┤
 *   │  NuclearCandleChart (main)       │ NuclearExplain   │
 *   │  (flex-1, live OHLCV + overlays) │ Panel (sidebar)  │
 *   ├──────────────────────────────────┴──────────────────┤
 *   │  NuclearEquityPanel (bottom, full-width)            │
 *   └─────────────────────────────────────────────────────┘
 *
 * Overlays (z-index above chart):
 *   - NuclearAlertOverlay (fixed, severity ≥ 7)
 *
 * Data flow:
 *   useNuclearWS() → /ws/nuclear → useNuclearStore → all components
 */

import React, { memo, useEffect, useCallback, useState } from 'react';
import { useNuclearWS } from '../hooks/useNuclearWS';
import { useNuclearStore } from '../store/nuclear-store';
import NuclearGeopoliticalBanner from './NuclearGeopoliticalBanner';
import NuclearCandleChart        from './NuclearCandleChart';
import NuclearExplainPanel       from './NuclearExplainPanel';
import NuclearEquityPanel        from './NuclearEquityPanel';
import NuclearAlertOverlay       from './NuclearAlertOverlay';
import NuclearMobileView         from './NuclearMobileView';
import GeopoliticalPanel         from './GeopoliticalPanel';
import { useStore }              from '../../../store';

// ─── Responsive breakpoint hook ───────────────────────────────────────────────

function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint);
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < breakpoint);
    window.addEventListener('resize', handler, { passive: true });
    return () => window.removeEventListener('resize', handler);
  }, [breakpoint]);
  return isMobile;
}

// ─── CSS injection ────────────────────────────────────────────────────────────

function injectDashboardCSS() {
  const id = 'nuclear-dashboard-css';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = `
    @keyframes nuclearGlow {
      0%, 100% { box-shadow: 0 0 0 0 rgba(255,0,51,0); }
      50%       { box-shadow: 0 0 20px 4px rgba(255,0,51,0.3); }
    }
    @keyframes statusPulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.5; }
    }
    .nuclear-glow { animation: nuclearGlow 1.5s ease-in-out infinite; }
    .status-pulse { animation: statusPulse 2s ease-in-out infinite; }
  `;
  document.head.appendChild(style);
}

// ─── WS status bar ────────────────────────────────────────────────────────────

const WsStatusBar = memo(({ status }: { status: string }) => {
  const color =
    status === 'connected'    ? '#00ff88' :
    status === 'connecting'   ? '#fbbf24' :
    status === 'error'        ? '#ff0033' : '#475569';
  const label =
    status === 'connected'    ? 'LIVE' :
    status === 'connecting'   ? 'CONNECTING…' :
    status === 'error'        ? 'ERROR' : 'OFFLINE';

  return (
    <div style={s.wsBar}>
      <span
        className={status === 'connecting' ? 'status-pulse' : ''}
        style={{ ...s.wsDot, background: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span style={{ ...s.wsLabel, color }}>NUCLEAR WS: {label}</span>
      <span style={s.wsNote}>XAU/USD · OANDA · Paper Mode</span>
    </div>
  );
});

// ─── Protected view banner ────────────────────────────────────────────────────

const ProtectedViewBanner = memo(() => (
  <div className="nuclear-glow" style={s.protectedBanner}>
    <span style={s.protectedIcon}>🔒</span>
    <span style={s.protectedText}>
      PROTECTED VIEW — Nuclear mode active. All trading halted. Awaiting manual resume.
    </span>
  </div>
));

// ─── Main dashboard ───────────────────────────────────────────────────────────

const NuclearDashboard = memo(() => {
  const isAuth  = useStore((s) => s.token !== null);
  const isMobile = useIsMobile();

  // Connect to /ws/nuclear — must be called unconditionally (Rules of Hooks)
  const { status, lastAlert } = useNuclearWS(isAuth);

  // All store reads must be unconditional — called before any early return
  const protectedView       = useNuclearStore((s) => s.protectedView);
  const showExplainPanel    = useNuclearStore((s) => s.showExplainPanel);
  const setShowExplainPanel = useNuclearStore((s) => s.setShowExplainPanel);
  const setNuclearAlert     = useNuclearStore((s) => s.setNuclearAlert);

  useEffect(() => { injectDashboardCSS(); }, []);

  // Sync lastAlert from hook into store
  useEffect(() => {
    if (lastAlert) setNuclearAlert(lastAlert);
  }, [lastAlert, setNuclearAlert]);

  const handleExplainToggle = useCallback(() => {
    setShowExplainPanel(!showExplainPanel);
  }, [showExplainPanel, setShowExplainPanel]);

  if (isMobile) return <NuclearMobileView />;

  return (
    <div style={s.root}>
      {/* Nuclear alert overlay (fixed, above everything) */}
      <NuclearAlertOverlay />

      {/* Protected view banner */}
      {protectedView && <ProtectedViewBanner />}

      {/* WS status bar */}
      <WsStatusBar status={status} />

      {/* Geopolitical risk banner */}
      <NuclearGeopoliticalBanner onClickExplain={handleExplainToggle} />

      {/* Main content area */}
      <div style={s.contentArea}>
        {/* Chart + sidebar row */}
        <div style={s.chartRow}>
          <NuclearCandleChart />
          {showExplainPanel && <NuclearExplainPanel />}
          {/* Geopolitical intelligence sidebar — always visible on desktop */}
          <div style={s.geoSidebar}>
            <GeopoliticalPanel />
          </div>
        </div>

        {/* Equity curve bottom panel */}
        <NuclearEquityPanel />
      </div>
    </div>
  );
});

export default NuclearDashboard;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex', flexDirection: 'column',
    height: '100%', width: '100%',
    background: '#020408',
    color: '#f1f5f9',
    fontFamily: 'monospace, system-ui, sans-serif',
    overflow: 'hidden',
    position: 'relative',
  },
  wsBar: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '4px 16px',
    background: '#060d18',
    borderBottom: '1px solid #0a1628',
    flexShrink: 0,
  },
  wsDot: {
    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
    transition: 'background 0.3s ease',
  },
  wsLabel: {
    fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
    transition: 'color 0.3s ease',
  },
  wsNote: {
    fontSize: 10, color: '#334155', marginLeft: 'auto',
  },
  protectedBanner: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '8px 20px',
    background: 'rgba(255,0,51,0.15)',
    borderBottom: '2px solid #ff0033',
    flexShrink: 0,
  },
  protectedIcon: { fontSize: 16 },
  protectedText: {
    fontSize: 12, color: '#fca5a5', fontWeight: 700, letterSpacing: 0.5,
  },
  contentArea: {
    flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0,
  },
  chartRow: {
    flex: 1, display: 'flex', minHeight: 0,
  },
  geoSidebar: {
    width: 260,
    flexShrink: 0,
    overflowY: 'auto',
    borderLeft: '1px solid #1a2e4a',
    background: 'rgba(6,13,24,0.97)',
  },
};
