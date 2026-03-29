// HOPEFX-AI-TRADING — AGPL-3.0
/** Shared design tokens — dark trading theme matching the web dashboard. */

export const COLORS = {
  background:  '#0a0f1c',
  surface:     '#131722',
  surfaceAlt:  '#1a2035',
  border:      '#2a3350',
  accent:      '#00d4aa',
  accentDim:   '#00a882',
  buy:         '#26a69a',
  sell:        '#ef5350',
  warning:     '#f59e0b',
  text:        '#d1d4dc',
  textMuted:   '#6b7280',
  textDim:     '#4b5563',
  white:       '#ffffff',
  gold:        '#f59e0b',
  profit:      '#26a69a',
  loss:        '#ef5350',
  neutral:     '#6b7280',
} as const;

export const FONTS = {
  regular:  'System',
  medium:   'System',
  bold:     'System',
  mono:     'Courier',
} as const;

export const SPACING = {
  xs:  4,
  sm:  8,
  md:  16,
  lg:  24,
  xl:  32,
  xxl: 48,
} as const;

export const RADIUS = {
  sm:  6,
  md:  10,
  lg:  16,
  xl:  24,
  full: 9999,
} as const;

export const SHADOW = {
  sm: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.3,
    shadowRadius: 3,
    elevation: 2,
  },
  md: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 5,
  },
} as const;
