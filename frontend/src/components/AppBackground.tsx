/**
 * AppBackground.tsx
 *
 * Theme-aware since 2026-09-15. This is a `position: fixed; inset: 0; z-index: 0`
 * layer mounted on every authenticated route, and it painted
 * `linear-gradient(180deg, #0a1424, #0a0f1c, #06090f)` as a literal — so
 * choosing Light moved `body` and the chrome while the ground stayed navy. A
 * white sidebar over a dark page is what that looked like on a phone.
 *
 * Every colour here now comes from a token that BOTH themes define (see the
 * `--ground-*`, `--orb-*` and `--spark-*` block in index.css). The mask uses
 * `black`, which is an alpha stencil rather than a colour anyone sees.
 * Premium animated backdrop used across the whole app.
 *
 * Two variants:
 *   - "auth" (login / register): bold — gradient + aurora glows + faded grid +
 *     an on-brand animated price-line/candlestick motif + vignette.
 *   - "app"  (everything else):  subtle — gradient + softer glows + faint grid +
 *     vignette, no chart motif, so it beautifies without distracting from data.
 *
 * All layers are fixed, pointer-events:none, and z-index 0 (content sits above).
 * Motion is disabled under prefers-reduced-motion.
 */

import React from 'react';

interface AppBackgroundProps {
  variant?: 'auth' | 'app';
}

const AppBackground: React.FC<AppBackgroundProps> = ({ variant = 'auth' }) => {
  const isAuth = variant === 'auth';
  const orbOpacity = isAuth ? 1 : 0.5;
  return (
    <>
      <div aria-hidden style={styles.base} />

      {/* Aurora glows */}
      <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbBlue, opacity: orbOpacity }} />
      <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbIndigo, opacity: orbOpacity }} />
      <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbCyan, opacity: orbOpacity }} />
      <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbGold, opacity: orbOpacity }} />

      {/* Terminal grid */}
      <div
        aria-hidden
        className="hopefx-auth-grid"
        style={{ ...styles.grid, opacity: isAuth ? 1 : 0.6 }}
      />

      {/* Market motif — auth screens only */}
      {isAuth && (
        <div aria-hidden style={styles.chartWrap} className="hopefx-auth-chart">
          <svg viewBox="0 0 1440 360" preserveAspectRatio="none" width="100%" height="100%" style={{ display: 'block' }}>
            <defs>
              <linearGradient id="hopefxLineGrad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="var(--spark-a)" />
                <stop offset="55%" stopColor="var(--link)" />
                <stop offset="100%" stopColor="var(--spark-b)" />
              </linearGradient>
              <linearGradient id="hopefxAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--ground-glow-a)" />
                <stop offset="100%" stopColor="transparent" />
              </linearGradient>
              <filter id="hopefxGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="6" result="b" />
                <feMerge>
                  <feMergeNode in="b" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <g opacity="0.5">
              {CANDLES.map((c, i) => (
                <g key={i} stroke={c.up ? 'var(--spark-up)' : 'var(--spark-down)'} fill={c.up ? 'var(--spark-up)' : 'var(--spark-down)'}>
                  <line x1={c.x} x2={c.x} y1={c.wickTop} y2={c.wickBot} strokeWidth="1.5" opacity="0.35" />
                  <rect x={c.x - 5} y={c.bodyTop} width="10" height={c.bodyH} opacity="0.18" rx="1" />
                </g>
              ))}
            </g>

            <path d={`${LINE_PATH} L1440,360 L0,360 Z`} fill="url(#hopefxAreaGrad)" />
            <path
              className="hopefx-auth-line"
              d={LINE_PATH}
              fill="none"
              stroke="url(#hopefxLineGrad)"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              filter="url(#hopefxGlow)"
            />
          </svg>
        </div>
      )}

      {/* Vignette — a touch stronger app-wide for content contrast */}
      <div aria-hidden style={{ ...styles.vignette, ...(isAuth ? null : styles.vignetteApp) }} />

      <style>{KEYFRAMES}</style>
    </>
  );
};

const LINE_PATH =
  'M0,250 C120,210 210,275 330,235 S560,150 660,185 S880,115 1010,150 S1230,80 1440,120';

const CANDLES = [
  { x: 160,  up: true,  wickTop: 205, wickBot: 270, bodyTop: 222, bodyH: 34 },
  { x: 430,  up: false, wickTop: 195, wickBot: 260, bodyTop: 210, bodyH: 38 },
  { x: 720,  up: true,  wickTop: 150, wickBot: 215, bodyTop: 168, bodyH: 36 },
  { x: 1010, up: true,  wickTop: 120, wickBot: 185, bodyTop: 138, bodyH: 32 },
  { x: 1280, up: false, wickTop: 95,  wickBot: 165, bodyTop: 112, bodyH: 36 },
];

const KEYFRAMES = `
  @keyframes hopefxFloatA { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(50px,-40px) scale(1.08); } }
  @keyframes hopefxFloatB { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(-45px,40px) scale(1.10); } }
  @keyframes hopefxFloatC { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(35px,45px) scale(0.94); } }
  @keyframes hopefxFloatD { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(-30px,-30px) scale(1.06); } }
  @keyframes hopefxGridPan { 0% { background-position: 0 0; } 100% { background-position: 54px 54px; } }
  @keyframes hopefxChartFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
  @keyframes hopefxLineFlow { to { stroke-dashoffset: -260; } }
  .hopefx-auth-line { stroke-dasharray: 14 10; animation: hopefxLineFlow 6s linear infinite; }
  .hopefx-auth-chart { animation: hopefxChartFloat 12s ease-in-out infinite; }
  @media (prefers-reduced-motion: reduce) {
    .hopefx-auth-orb, .hopefx-auth-grid, .hopefx-auth-line, .hopefx-auth-chart { animation: none !important; }
  }
`;

const orbBase: React.CSSProperties = {
  position: 'fixed',
  borderRadius: '50%',
  filter: 'blur(95px)',
  zIndex: 0,
  pointerEvents: 'none',
  willChange: 'transform',
};

const styles: Record<string, React.CSSProperties> = {
  base: {
    position: 'fixed',
    inset: 0,
    zIndex: 0,
    pointerEvents: 'none',
    background:
      'radial-gradient(ellipse at 50% -8%, var(--ground-glow-a), transparent 55%),' +
      'radial-gradient(ellipse at 12% 18%, var(--ground-glow-b), transparent 45%),' +
      'radial-gradient(ellipse at 88% 100%, var(--ground-glow-c), transparent 50%),' +
      'radial-gradient(ellipse at 30% 70%, var(--ground-glow-d), transparent 45%),' +
      'linear-gradient(180deg, var(--ground-base) 0%, var(--ground-mid) 45%, var(--ground-deep) 100%)',
  },
  orb: orbBase,
  orbBlue: {
    width: 600, height: 600, top: -160, left: -110,
    background: 'radial-gradient(circle, var(--orb-blue) 0%, transparent 70%)',
    animation: 'hopefxFloatA 22s ease-in-out infinite',
  },
  orbIndigo: {
    width: 520, height: 520, top: '8%', right: '6%',
    background: 'radial-gradient(circle, var(--orb-indigo) 0%, transparent 70%)',
    animation: 'hopefxFloatD 26s ease-in-out infinite',
  },
  orbCyan: {
    width: 480, height: 480, bottom: -140, right: -80,
    background: 'radial-gradient(circle, var(--orb-cyan) 0%, transparent 70%)',
    animation: 'hopefxFloatB 24s ease-in-out infinite',
  },
  orbGold: {
    width: 400, height: 400, top: '46%', left: '50%',
    background: 'radial-gradient(circle, var(--orb-gold) 0%, transparent 70%)',
    animation: 'hopefxFloatC 30s ease-in-out infinite',
  },
  grid: {
    position: 'fixed',
    inset: 0,
    zIndex: 0,
    pointerEvents: 'none',
    backgroundImage:
      'linear-gradient(var(--ground-grid) 1px, transparent 1px),' +
      'linear-gradient(90deg, var(--ground-grid) 1px, transparent 1px)',
    backgroundSize: '54px 54px',
    WebkitMaskImage: 'radial-gradient(ellipse at 50% 42%, black 28%, transparent 78%)',
    maskImage: 'radial-gradient(ellipse at 50% 42%, black 28%, transparent 78%)',
    animation: 'hopefxGridPan 30s linear infinite',
  },
  chartWrap: {
    position: 'fixed',
    left: 0,
    right: 0,
    bottom: 0,
    height: '46vh',
    minHeight: 280,
    zIndex: 0,
    pointerEvents: 'none',
    opacity: 0.55,
    willChange: 'transform',
  },
  vignette: {
    position: 'fixed',
    inset: 0,
    zIndex: 0,
    pointerEvents: 'none',
    background: 'radial-gradient(ellipse at 50% 45%, transparent 40%, var(--ground-vignette) 100%)',
  },
  vignetteApp: {
    background: 'radial-gradient(ellipse at 50% 40%, transparent 32%, var(--ground-vignette-strong) 100%)',
  },
};

export default AppBackground;
