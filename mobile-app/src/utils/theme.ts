// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * utils/theme.ts
 * ==============
 * Institutional-grade dark trading theme.
 * Bloomberg Terminal meets 2026 — deep blacks, surgical neon, crystal P&L.
 */

import { Platform, TextStyle } from 'react-native';

// ── Color palette ─────────────────────────────────────────────────────────────

export const COLORS = {
  // Backgrounds — layered depth
  background:     '#080c14',   // deepest black
  surface:        '#0d1117',   // card surface
  surfaceAlt:     '#111827',   // elevated surface
  surfaceHigh:    '#1a2235',   // highest elevation
  overlay:        'rgba(8,12,20,0.92)',

  // Borders
  border:         '#1e2d45',
  borderBright:   '#2a3f5f',
  borderAccent:   'rgba(0,212,170,0.25)',

  // Accent — surgical teal/cyan
  accent:         '#00d4aa',
  accentDim:      '#00a882',
  accentGlow:     'rgba(0,212,170,0.15)',
  accentStrong:   '#00ffcc',

  // Trading signals — crystal clear
  buy:            '#00c896',   // emerald green
  buyDim:         'rgba(0,200,150,0.15)',
  buyGlow:        'rgba(0,200,150,0.3)',
  sell:           '#ff4757',   // vivid red
  sellDim:        'rgba(255,71,87,0.15)',
  sellGlow:       'rgba(255,71,87,0.3)',

  // P&L
  profit:         '#00e676',   // bright green
  profitDim:      'rgba(0,230,118,0.12)',
  loss:           '#ff1744',   // vivid red
  lossDim:        'rgba(255,23,68,0.12)',

  // Status
  warning:        '#ffab00',
  warningDim:     'rgba(255,171,0,0.15)',
  danger:         '#ff1744',
  dangerDim:      'rgba(255,23,68,0.15)',
  success:        '#00e676',
  successDim:     'rgba(0,230,118,0.12)',
  info:           '#40c4ff',
  infoDim:        'rgba(64,196,255,0.12)',

  // Kill switch
  killSwitch:     '#ff1744',
  killSwitchDim:  'rgba(255,23,68,0.2)',

  // Text hierarchy
  text:           '#e8eaf0',   // primary — near white
  textSecondary:  '#9ba3b5',   // secondary
  textMuted:      '#5c6880',   // muted
  textDim:        '#3a4255',   // very dim
  white:          '#ffffff',
  black:          '#000000',

  // Special
  gold:           '#ffd700',
  goldDim:        'rgba(255,215,0,0.15)',
  silver:         '#c0c0c0',
  platinum:       '#e5e4e2',

  // Sentiment
  bullish:        '#00e676',
  bearish:        '#ff1744',
  neutral:        '#5c6880',

  // Chart
  chartLine:      '#00d4aa',
  chartFill:      'rgba(0,212,170,0.08)',
  chartDrawdown:  'rgba(255,23,68,0.2)',
  chartGrid:      'rgba(30,45,69,0.6)',
  chartCrosshair: 'rgba(0,212,170,0.5)',
} as const;

// ── Typography ────────────────────────────────────────────────────────────────

const MONO_FONT = Platform.select({
  ios:     'Courier New',
  android: 'monospace',
  default: 'Courier New',
});

const SYSTEM_FONT = Platform.select({
  ios:     'SF Pro Display',
  android: 'Roboto',
  default: 'System',
});

export const FONTS = {
  regular:  SYSTEM_FONT!,
  medium:   SYSTEM_FONT!,
  bold:     SYSTEM_FONT!,
  mono:     MONO_FONT!,
} as const;

// Pre-built text styles for institutional typography
export const TEXT: Record<string, TextStyle> = {
  // Display — large numbers, equity values
  displayXL: { fontSize: 42, fontWeight: '900', fontFamily: MONO_FONT, letterSpacing: -1, color: COLORS.text },
  displayLG: { fontSize: 34, fontWeight: '900', fontFamily: MONO_FONT, letterSpacing: -0.5, color: COLORS.text },
  displayMD: { fontSize: 28, fontWeight: '800', fontFamily: MONO_FONT, color: COLORS.text },
  displaySM: { fontSize: 22, fontWeight: '700', fontFamily: MONO_FONT, color: COLORS.text },

  // Headings — section titles
  h1: { fontSize: 24, fontWeight: '800', color: COLORS.text, letterSpacing: -0.3 },
  h2: { fontSize: 20, fontWeight: '700', color: COLORS.text },
  h3: { fontSize: 17, fontWeight: '700', color: COLORS.text },
  h4: { fontSize: 15, fontWeight: '600', color: COLORS.text },

  // Body
  bodyLG: { fontSize: 16, fontWeight: '400', color: COLORS.text, lineHeight: 24 },
  body:   { fontSize: 14, fontWeight: '400', color: COLORS.text, lineHeight: 20 },
  bodySM: { fontSize: 13, fontWeight: '400', color: COLORS.textSecondary, lineHeight: 18 },

  // Labels — uppercase tracking
  labelLG: { fontSize: 13, fontWeight: '700', color: COLORS.textMuted, textTransform: 'uppercase', letterSpacing: 1.2 },
  label:   { fontSize: 11, fontWeight: '700', color: COLORS.textMuted, textTransform: 'uppercase', letterSpacing: 1 },
  labelSM: { fontSize: 10, fontWeight: '600', color: COLORS.textDim,   textTransform: 'uppercase', letterSpacing: 0.8 },

  // Numeric — monospace for prices
  numericXL: { fontSize: 36, fontWeight: '900', fontFamily: MONO_FONT, color: COLORS.text, letterSpacing: -0.5 },
  numericLG: { fontSize: 24, fontWeight: '700', fontFamily: MONO_FONT, color: COLORS.text },
  numericMD: { fontSize: 18, fontWeight: '700', fontFamily: MONO_FONT, color: COLORS.text },
  numericSM: { fontSize: 14, fontWeight: '600', fontFamily: MONO_FONT, color: COLORS.text },
  numericXS: { fontSize: 12, fontWeight: '600', fontFamily: MONO_FONT, color: COLORS.textSecondary },

  // Caption
  caption:   { fontSize: 11, fontWeight: '500', color: COLORS.textMuted },
  captionSM: { fontSize: 10, fontWeight: '400', color: COLORS.textDim },
} as const;

// ── Spacing ───────────────────────────────────────────────────────────────────

export const SPACING = {
  xs:   4,
  sm:   8,
  md:   16,
  lg:   24,
  xl:   32,
  xxl:  48,
  xxxl: 64,
} as const;

// ── Border radius ─────────────────────────────────────────────────────────────

export const RADIUS = {
  xs:   4,
  sm:   6,
  md:   10,
  lg:   14,
  xl:   20,
  xxl:  28,
  full: 9999,
} as const;

// ── Shadows ───────────────────────────────────────────────────────────────────

export const SHADOW = {
  none: {},
  xs: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.4,
    shadowRadius: 2,
    elevation: 1,
  },
  sm: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.5,
    shadowRadius: 4,
    elevation: 3,
  },
  md: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.6,
    shadowRadius: 8,
    elevation: 6,
  },
  lg: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.7,
    shadowRadius: 16,
    elevation: 10,
  },
  // Colored glow shadows for accent elements
  accentGlow: {
    shadowColor: COLORS.accent,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 12,
    elevation: 8,
  },
  buyGlow: {
    shadowColor: COLORS.buy,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 10,
    elevation: 6,
  },
  sellGlow: {
    shadowColor: COLORS.sell,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 10,
    elevation: 6,
  },
  dangerGlow: {
    shadowColor: COLORS.danger,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.7,
    shadowRadius: 14,
    elevation: 10,
  },
} as const;

// ── Animation durations ───────────────────────────────────────────────────────

export const DURATION = {
  instant:  0,
  fast:     150,
  normal:   250,
  slow:     400,
  verySlow: 600,
} as const;

// ── Z-index layers ────────────────────────────────────────────────────────────

export const Z = {
  base:    0,
  card:    10,
  overlay: 100,
  modal:   200,
  toast:   300,
} as const;

// ── Utility helpers ───────────────────────────────────────────────────────────

/** Returns profit/loss color based on value sign. */
export function pnlColor(value: number): string {
  if (value > 0) return COLORS.profit;
  if (value < 0) return COLORS.loss;
  return COLORS.textMuted;
}

/** Returns buy/sell color based on side string. */
export function sideColor(side: 'buy' | 'sell' | string): string {
  return side === 'buy' ? COLORS.buy : COLORS.sell;
}

/** Returns signal direction color. */
export function signalColor(direction: 'long' | 'short' | 'neutral' | string): string {
  if (direction === 'long')  return COLORS.buy;
  if (direction === 'short') return COLORS.sell;
  return COLORS.neutral;
}

/** Returns confidence tier color (0–1 scale). */
export function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return COLORS.profit;
  if (confidence >= 0.6) return COLORS.accent;
  if (confidence >= 0.4) return COLORS.warning;
  return COLORS.textMuted;
}

/** Returns risk level color. */
export function riskColor(utilization: number): string {
  if (utilization >= 0.85) return COLORS.danger;
  if (utilization >= 0.65) return COLORS.warning;
  if (utilization >= 0.40) return COLORS.accent;
  return COLORS.success;
}

/** Hex color with alpha (0–1). */
export function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}
