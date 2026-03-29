/**
 * chart-bot/utils/design-tokens.ts
 * Institutional-grade design system — single source of truth for all
 * colors, typography, spacing, and animation constants used across
 * the AI Chart Bot module.
 */

// ─── Color Palette ────────────────────────────────────────────────────────────

export const COLORS = {
  // Backgrounds — deep institutional blacks
  bg: {
    void:    '#020408',   // absolute darkest — chart canvas
    base:    '#060d18',   // primary app background
    surface: '#0a1628',   // card surfaces
    elevated:'#0f1f35',   // elevated panels
    overlay: '#162540',   // hover/active states
    border:  '#1a2e4a',   // subtle borders
    divider: '#1e3550',   // dividers
  },

  // Neon signal accents — razor-sharp, high-contrast
  neon: {
    cyan:    '#00d4ff',   // primary accent / buy signals
    blue:    '#0ea5e9',   // secondary accent
    purple:  '#a855f7',   // AI/ML indicators
    gold:    '#f59e0b',   // XAUUSD gold accent
    amber:   '#fbbf24',   // warnings
    lime:    '#84cc16',   // strong bullish
  },

  // P&L — crystal clear
  profit: {
    strong:  '#00ff88',   // strong profit
    base:    '#22c55e',   // standard profit
    muted:   '#16a34a',   // muted profit
    bg:      '#052e16',   // profit background
    border:  '#14532d',   // profit border
  },
  loss: {
    strong:  '#ff3366',   // strong loss
    base:    '#ef4444',   // standard loss
    muted:   '#dc2626',   // muted loss
    bg:      '#2d0a0a',   // loss background
    border:  '#7f1d1d',   // loss border
  },

  // Signal confidence spectrum
  confidence: {
    high:    '#00ff88',   // ≥80%
    medium:  '#f59e0b',   // 50–79%
    low:     '#ef4444',   // <50%
  },

  // Sentiment spectrum
  sentiment: {
    veryBullish: '#00ff88',
    bullish:     '#22c55e',
    neutral:     '#64748b',
    bearish:     '#ef4444',
    veryBearish: '#ff3366',
  },

  // Text hierarchy
  text: {
    primary:   '#f0f6ff',   // primary content
    secondary: '#8ba3c7',   // secondary labels
    muted:     '#4a6080',   // muted / disabled
    accent:    '#00d4ff',   // accent text
    gold:      '#f59e0b',   // gold price text
  },

  // Chart-specific
  chart: {
    candleUp:      '#00ff88',
    candleDown:    '#ff3366',
    wickUp:        '#00cc6a',
    wickDown:      '#cc2952',
    volume:        '#1a3a5c',
    volumeBuy:     '#0d4a2a',
    volumeSell:    '#4a0d1a',
    grid:          '#0d1e30',
    crosshair:     '#2a4a6a',
    bidLine:       '#22c55e',
    askLine:       '#ef4444',
    spread:        'rgba(251,191,36,0.08)',
    trendlineUp:   '#00d4ff',
    trendlineDown: '#a855f7',
    support:       '#22c55e',
    resistance:    '#ef4444',
    pivot:         '#f59e0b',
    pattern:       'rgba(168,85,247,0.15)',
  },

  // Risk heatmap
  risk: {
    low:      '#22c55e',
    moderate: '#f59e0b',
    high:     '#ef4444',
    critical: '#ff3366',
    bg:       'rgba(239,68,68,0.08)',
  },
} as const;

// ─── Typography ───────────────────────────────────────────────────────────────

export const TYPOGRAPHY = {
  fontFamily: {
    mono:    '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
    sans:    '"Inter", "SF Pro Display", system-ui, sans-serif',
    display: '"Inter", "SF Pro Display", system-ui, sans-serif',
  },
  fontSize: {
    '2xs': '10px',
    xs:    '11px',
    sm:    '12px',
    base:  '13px',
    md:    '14px',
    lg:    '15px',
    xl:    '16px',
    '2xl': '18px',
    '3xl': '20px',
    '4xl': '24px',
    '5xl': '28px',
  },
  fontWeight: {
    normal:   400,
    medium:   500,
    semibold: 600,
    bold:     700,
    black:    900,
  },
  letterSpacing: {
    tight:  '-0.02em',
    normal: '0',
    wide:   '0.04em',
    wider:  '0.08em',
    widest: '0.12em',
  },
  lineHeight: {
    tight:  1.2,
    normal: 1.5,
    loose:  1.8,
  },
} as const;

// ─── Spacing ──────────────────────────────────────────────────────────────────

export const SPACING = {
  0:   '0px',
  1:   '2px',
  2:   '4px',
  3:   '6px',
  4:   '8px',
  5:   '10px',
  6:   '12px',
  7:   '14px',
  8:   '16px',
  10:  '20px',
  12:  '24px',
  16:  '32px',
  20:  '40px',
  24:  '48px',
} as const;

// ─── Border Radius ────────────────────────────────────────────────────────────

export const RADIUS = {
  sm:   '4px',
  md:   '6px',
  lg:   '8px',
  xl:   '12px',
  '2xl':'16px',
  full: '9999px',
} as const;

// ─── Shadows / Glows ──────────────────────────────────────────────────────────

export const SHADOWS = {
  card:       '0 1px 3px rgba(0,0,0,0.6), 0 0 0 1px rgba(26,46,74,0.8)',
  elevated:   '0 4px 16px rgba(0,0,0,0.8), 0 0 0 1px rgba(26,46,74,0.6)',
  glow: {
    cyan:   '0 0 20px rgba(0,212,255,0.3), 0 0 40px rgba(0,212,255,0.1)',
    green:  '0 0 20px rgba(0,255,136,0.3), 0 0 40px rgba(0,255,136,0.1)',
    red:    '0 0 20px rgba(255,51,102,0.3), 0 0 40px rgba(255,51,102,0.1)',
    gold:   '0 0 20px rgba(245,158,11,0.3), 0 0 40px rgba(245,158,11,0.1)',
    purple: '0 0 20px rgba(168,85,247,0.3), 0 0 40px rgba(168,85,247,0.1)',
  },
} as const;

// ─── Animation ────────────────────────────────────────────────────────────────

export const ANIMATION = {
  duration: {
    instant: '50ms',
    fast:    '100ms',
    normal:  '200ms',
    slow:    '350ms',
    slower:  '500ms',
  },
  easing: {
    sharp:   'cubic-bezier(0.4, 0, 0.6, 1)',
    smooth:  'cubic-bezier(0.4, 0, 0.2, 1)',
    spring:  'cubic-bezier(0.34, 1.56, 0.64, 1)',
    linear:  'linear',
  },
} as const;

// ─── Z-Index ──────────────────────────────────────────────────────────────────

export const Z = {
  base:    0,
  chart:   10,
  overlay: 20,
  panel:   30,
  tooltip: 40,
  modal:   50,
  toast:   60,
} as const;

// ─── Chart Dimensions ─────────────────────────────────────────────────────────

export const CHART_DIMS = {
  mainHeight:       520,
  volumeHeight:     100,
  equityCurveHeight:200,
  microHeight:      160,
  panelMinWidth:    320,
  sidebarWidth:     340,
  signalFeedWidth:  300,
} as const;

// ─── Utility: confidence → color ─────────────────────────────────────────────

export function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return COLORS.confidence.high;
  if (confidence >= 0.5) return COLORS.confidence.medium;
  return COLORS.confidence.low;
}

export function pnlColor(value: number): string {
  return value >= 0 ? COLORS.profit.base : COLORS.loss.base;
}

export function sentimentColor(score: number): string {
  if (score >= 0.5)  return COLORS.sentiment.veryBullish;
  if (score >= 0.15) return COLORS.sentiment.bullish;
  if (score >= -0.15)return COLORS.sentiment.neutral;
  if (score >= -0.5) return COLORS.sentiment.bearish;
  return COLORS.sentiment.veryBearish;
}

export function riskColor(score: number): string {
  if (score < 25)  return COLORS.risk.low;
  if (score < 50)  return COLORS.risk.moderate;
  if (score < 75)  return COLORS.risk.high;
  return COLORS.risk.critical;
}

// ─── CSS custom properties injection ─────────────────────────────────────────

export const CSS_VARS = `
  :root {
    --cb-bg-void:    ${COLORS.bg.void};
    --cb-bg-base:    ${COLORS.bg.base};
    --cb-bg-surface: ${COLORS.bg.surface};
    --cb-bg-elevated:${COLORS.bg.elevated};
    --cb-neon-cyan:  ${COLORS.neon.cyan};
    --cb-neon-gold:  ${COLORS.neon.gold};
    --cb-profit:     ${COLORS.profit.base};
    --cb-loss:       ${COLORS.loss.base};
    --cb-text:       ${COLORS.text.primary};
    --cb-text-muted: ${COLORS.text.muted};
    --cb-border:     ${COLORS.bg.border};
    --cb-font-mono:  ${TYPOGRAPHY.fontFamily.mono};
    --cb-font-sans:  ${TYPOGRAPHY.fontFamily.sans};
  }
`;
