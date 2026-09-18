/**
 * hub/a11yContrast.ts — §27 colour contrast, measured rather than remembered.
 *
 * A muted grey was added to the presence overlay in this session and read as
 * obviously fine. Measured against the surface it actually sits on, it was
 * below the 4.5:1 floor. Nothing in the code said so, because nothing in the
 * code could: the ratio existed only in whoever picked the colour's head.
 *
 * So the ratio is computed here, from the WCAG 2.1 definition, and the palette
 * below is a set of claims the test suite re-measures on every run. A colour
 * that stops passing fails a test instead of shipping.
 *
 * ## Why the surfaces are composites
 *
 * `vizPalette.ts` found the same thing for data colour: validating against
 * `#000` or against a token literal measures a background that is not on
 * screen. The panel hull is translucent over the stage void, so the number
 * that matters is the composite. `overlay` below is `slate-900` at 90% over
 * the void — the presence overlay's actual hull — arrived at by compositing,
 * not by reading the token.
 *
 * ## The forbidden list is not decoration
 *
 * `FORBIDDEN_TEXT` records colours that were reached for and refused, with the
 * ratio each one measures. The suite re-measures them too: a "forbidden"
 * colour that now passes is a stale prohibition, and a stated ratio that no
 * longer matches the measurement is a memory wearing the clothes of a
 * measurement. Both fail.
 */

/** Normal text, WCAG 2.1 AA (1.4.3). */
export const TEXT_FLOOR = 4.5;

/** Text at 18.66px bold or 24px regular, AA (1.4.3). */
export const LARGE_TEXT_FLOOR = 3;

/** Borders, icons, focus rings — anything carrying meaning that is not text (1.4.11). */
export const NON_TEXT_FLOOR = 3;

/** AAA for normal text (1.4.6). What `high` contrast mode is held to. */
export const HIGH_CONTRAST_FLOOR = 7;

export const CONTRAST_MODES = ['standard', 'high'] as const;
export type ContrastMode = (typeof CONTRAST_MODES)[number];

/**
 * The backgrounds text is actually drawn on, after compositing.
 *
 * `panel`   the surface `vizPalette.ts` validated against: the panel hull over
 *           the stage void.
 * `overlay` the presence overlay's hull: `#0f172a` at 90% over `#070c16`.
 * `stage`   the void itself, where the presence canvas sits.
 */
export const SURFACES = Object.freeze({
  panel: '#0f1a2a',
  overlay: '#0e1628',
  stage: '#070c16',
});

export type SurfaceName = keyof typeof SURFACES;

/** A colour that was refused, and the measurement that refused it. */
export interface ForbiddenColour {
  hex: string;
  /** Which surface it was measured against. The ratio is meaningless without it. */
  surface: SurfaceName;
  /** Carries the measured ratio. The suite checks that it still does. */
  reason: string;
}

/**
 * Greys that read as "muted body text" and are not.
 *
 * Both were reached for in this codebase. `slate-500` is the one that shipped
 * on the presence overlay before it was measured.
 */
export const FORBIDDEN_TEXT: Readonly<Record<string, ForbiddenColour>> = Object.freeze({
  'text-slate-500': Object.freeze({
    hex: '#64748b',
    surface: 'panel',
    reason: 'measures 3.67:1 on the panel hull, below the 4.5:1 floor for normal text',
  }),
  'text-slate-600': Object.freeze({
    hex: '#475569',
    surface: 'panel',
    reason: 'measures 2.31:1 on the panel hull; it is a border colour, not a text colour',
  }),
});

/**
 * Text colours cleared for use, by mode.
 *
 * `standard` clears 4.5:1 on every surface above; `high` clears 7:1. Neither
 * list is asserted — `hub_a11y.test.ts` measures every token against every
 * surface, so adding one without measuring it fails.
 */
const PALETTES: Readonly<Record<ContrastMode, Readonly<Record<string, string>>>> = Object.freeze({
  standard: Object.freeze({
    strong: '#f8fafc',
    body: '#e2e8f0',
    muted: '#94a3b8',
    accent: '#38bdf8',
    good: '#6ee7b7',
    warn: '#fcd34d',
    bad: '#fb7185',
  }),
  high: Object.freeze({
    strong: '#ffffff',
    body: '#f1f5f9',
    muted: '#cbd5e1',
    accent: '#7dd3fc',
    good: '#a7f3d0',
    warn: '#fde68a',
    bad: '#fda4af',
  }),
});

export function textPalette(mode: ContrastMode): Readonly<Record<string, string>> {
  return PALETTES[mode];
}

/**
 * The panel's colours by ROLE, in the names `SurfaceView` already uses.
 *
 * Two things this is not. It is not a second palette — every value comes from
 * `PALETTES` above, so a colour added here without being measured is
 * impossible. And it is not only text: a high-contrast mode that raised the
 * body copy and left `warn` and `bad` alone would be a screen where the words
 * are readable and the warnings are not.
 *
 * `speak` and `ok` deliberately share a value. They mean different things —
 * "the AI is describing this panel" and "healthy" — and are never drawn on the
 * same element, and §27's rule that colour is never the only indicator is what
 * keeps them distinguishable: the spoken-about panel also carries
 * `aria-current` and the words "speaking about".
 */
export function surfacePalette(mode: ContrastMode): Readonly<Record<SurfaceRole, string>> {
  const p = PALETTES[mode];
  return Object.freeze({
    text: p.strong!,
    dim: p.body!,
    quiet: p.muted!,
    core: p.accent!,
    ok: p.good!,
    speak: p.good!,
    warn: p.warn!,
    bad: p.bad!,
  });
}

export type SurfaceRole = 'text' | 'dim' | 'quiet' | 'core' | 'ok' | 'speak' | 'warn' | 'bad';

/**
 * `#rgb`, `#rrggbb` and `#rrggbbaa`.
 *
 * Alpha is parsed and discarded: this function measures a colour against a
 * surface, and a translucent foreground has no single ratio. Composite it
 * first, as `SURFACES.overlay` was, rather than letting a ratio be computed
 * from a colour that is not what appears.
 */
function parseHex(value: string): [number, number, number] {
  const raw = typeof value === 'string' ? value.trim().replace(/^#/, '') : '';
  let hex = raw;
  if (/^[0-9a-fA-F]{3}$/.test(raw)) hex = raw.replace(/./g, (c) => c + c);
  else if (/^[0-9a-fA-F]{4}$/.test(raw)) hex = raw.slice(0, 3).replace(/./g, (c) => c + c);
  else if (/^[0-9a-fA-F]{8}$/.test(raw)) hex = raw.slice(0, 6);
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) {
    // Never 0 or black. A silently-black foreground scores maximum contrast
    // against a light surface and minimum against a dark one; either way the
    // palette would pass or fail for a reason nobody could see.
    throw new Error(`a11yContrast: ${String(value)} is not a hex colour (#rgb, #rrggbb or #rrggbbaa)`);
  }
  return [
    parseInt(hex.slice(0, 2), 16) / 255,
    parseInt(hex.slice(2, 4), 16) / 255,
    parseInt(hex.slice(4, 6), 16) / 255,
  ];
}

function channel(c: number): number {
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2.1 relative luminance. */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * WCAG 2.1 contrast ratio, 1..21.
 *
 * Symmetric by construction — a ratio has no foreground — so a caller cannot
 * get a different answer by passing the pair the other way round.
 */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

export interface ContrastOptions {
  /** 18.66px bold or 24px regular. Lowers the floor to 3:1, as 1.4.3 does. */
  large?: boolean;
  /** Borders, icons, focus rings. 3:1 under 1.4.11. */
  nonText?: boolean;
  /** Hold the pair to AAA instead of AA. */
  mode?: ContrastMode;
}

export function floorFor(options: ContrastOptions = {}): number {
  if (options.mode === 'high') return HIGH_CONTRAST_FLOOR;
  if (options.nonText) return NON_TEXT_FLOOR;
  if (options.large) return LARGE_TEXT_FLOOR;
  return TEXT_FLOOR;
}

export function meetsContrast(foreground: string, background: string, options: ContrastOptions = {}): boolean {
  return contrastRatio(foreground, background) >= floorFor(options);
}

/**
 * The pair in words, carrying the number.
 *
 * Used in developer-facing output. "Fails" without a ratio is an opinion;
 * "3.67:1 against a 4.5:1 floor" is something to act on.
 */
export function describeContrast(foreground: string, background: string, options: ContrastOptions = {}): string {
  const ratio = contrastRatio(foreground, background);
  const floor = floorFor(options);
  const verdict = ratio >= floor ? 'pass' : 'fail';
  return `${foreground} on ${background}: ${ratio.toFixed(2)}:1 against a ${floor}:1 floor — ${verdict}`;
}

/**
 * Whether the operator asked for more contrast.
 *
 * Unreadable means `standard`, and that is a different call from
 * `usePrefersReducedMotion`, which defaults the other way. Motion defaults to
 * off because a wrong guess causes symptoms. Contrast defaults to standard
 * because the standard palette already clears AA on every surface — nobody is
 * harmed by not being upgraded, and forcing AAA on every browser that cannot
 * report the query changes the product for everyone on the strength of a
 * missing media query.
 */
export function prefersHighContrast(): ContrastMode {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'standard';
    if (window.matchMedia('(forced-colors: active)').matches) return 'high';
    if (window.matchMedia('(prefers-contrast: more)').matches) return 'high';
    return 'standard';
  } catch {
    return 'standard';
  }
}
