/**
 * AuthBackground.tsx
 * Animated, layered background for the auth screens (login / register).
 * Deep-blue gradient base + slowly drifting glow orbs + a faint terminal grid.
 * Purely decorative: fixed behind the page content, pointer-events disabled,
 * and motion is dropped for users who prefer reduced motion.
 */

import React from 'react';

const AuthBackground: React.FC = () => (
  <>
    <div aria-hidden style={styles.base} />
    <div aria-hidden className="hopefx-auth-grid" style={styles.grid} />
    <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbBlue }} />
    <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbCyan }} />
    <div aria-hidden className="hopefx-auth-orb" style={{ ...styles.orb, ...styles.orbGold }} />
    <style>{KEYFRAMES}</style>
  </>
);

const KEYFRAMES = `
  @keyframes hopefxFloatA { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(50px,-40px) scale(1.08); } }
  @keyframes hopefxFloatB { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(-40px,50px) scale(1.10); } }
  @keyframes hopefxFloatC { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(30px,40px) scale(0.94); } }
  @keyframes hopefxGridPan { 0% { background-position: 0 0; } 100% { background-position: 52px 52px; } }
  @media (prefers-reduced-motion: reduce) {
    .hopefx-auth-orb, .hopefx-auth-grid { animation: none !important; }
  }
`;

const styles: Record<string, React.CSSProperties> = {
  // Deep-blue layered base gradient.
  base: {
    position: 'fixed',
    inset: 0,
    zIndex: 0,
    pointerEvents: 'none',
    background:
      'radial-gradient(ellipse at 50% -10%, rgba(37,99,235,0.20), transparent 55%),' +
      'radial-gradient(ellipse at 85% 110%, rgba(34,211,238,0.10), transparent 50%),' +
      'linear-gradient(180deg, #0b1322 0%, #0a0f1a 45%, #070b14 100%)',
  },
  // Faint terminal grid, slowly panning, faded at the edges via a radial mask.
  grid: {
    position: 'fixed',
    inset: 0,
    zIndex: 0,
    pointerEvents: 'none',
    backgroundImage:
      'linear-gradient(rgba(59,130,246,0.06) 1px, transparent 1px),' +
      'linear-gradient(90deg, rgba(59,130,246,0.06) 1px, transparent 1px)',
    backgroundSize: '52px 52px',
    WebkitMaskImage: 'radial-gradient(ellipse at 50% 40%, #000 30%, transparent 80%)',
    maskImage: 'radial-gradient(ellipse at 50% 40%, #000 30%, transparent 80%)',
    animation: 'hopefxGridPan 28s linear infinite',
  },
  orb: {
    position: 'fixed',
    borderRadius: '50%',
    filter: 'blur(90px)',
    zIndex: 0,
    pointerEvents: 'none',
    willChange: 'transform',
  },
  orbBlue: {
    width: 560,
    height: 560,
    top: -140,
    left: -90,
    background: 'radial-gradient(circle, rgba(59,130,246,0.45) 0%, transparent 70%)',
    animation: 'hopefxFloatA 20s ease-in-out infinite',
  },
  orbCyan: {
    width: 460,
    height: 460,
    bottom: -120,
    right: -70,
    background: 'radial-gradient(circle, rgba(34,211,238,0.30) 0%, transparent 70%)',
    animation: 'hopefxFloatB 24s ease-in-out infinite',
  },
  orbGold: {
    width: 380,
    height: 380,
    top: '42%',
    left: '52%',
    background: 'radial-gradient(circle, rgba(245,158,11,0.16) 0%, transparent 70%)',
    animation: 'hopefxFloatC 28s ease-in-out infinite',
  },
};

export default AuthBackground;
