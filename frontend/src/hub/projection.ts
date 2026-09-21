/**
 * hub/projection.ts — where the presence is, how many of it there are, and what
 * shape it takes.
 *
 * §7's last three: "minimise, reposition, or split into multiple projections",
 * "contextual transformation into scientific representations", and "a renderer
 * abstraction for 3D, AR, VR and holographic output".
 *
 * ## The renderer abstraction is honest about what exists
 *
 * `RENDERERS` reports exactly one backend today: `canvas2d`. The abstraction is
 * the deliverable — presence logic no longer reaches for a 2D context directly,
 * so a WebGL, WebXR or holographic backend is an implementation of an interface
 * rather than a rewrite. But `available()` returns what is actually installed,
 * and a caller asking for `webxr` gets null and a reason, not a silent
 * fall-back to 2D that would let a deployment believe it was in VR.
 *
 * Claiming a capability the code does not have is the specific failure the
 * capability registry exists to catch, and it would be absurd to commit it in
 * the module that implements the registry's own §7 rows.
 */

import type { Surface } from './workspace';

// ── multiple projections (§7) ─────────────────────────────────────────────────

export type Anchor = 'centre' | 'left' | 'right' | 'top_left' | 'bottom_right';

export interface Projection {
  id: string;
  anchor: Anchor;
  /** Fraction of the plane's short edge. */
  scale: number;
  minimised: boolean;
  /** What this projection is attending to, when it was split off for one. */
  subjectId: string | null;
}

/** One presence, centred, full size. What every session starts as. */
export function singleProjection(): Projection[] {
  return [{ id: 'p0', anchor: 'centre', scale: 1, minimised: false, subjectId: null }];
}

const MIN_SCALE = 0.28;

/**
 * Split the presence so one projection attends to each subject.
 *
 * Capped at three. §7 offers splitting as a capability, not as an ambition: a
 * plane with six talking heads on it is a worse screen than one with a single
 * presence that turns, and the operator cannot follow which is speaking.
 *
 * Splitting with fewer than two subjects returns a single projection, because
 * "split" with one thing to attend to is just the presence, moved.
 */
export function splitProjection(subjects: readonly Surface[]): Projection[] {
  const chosen = subjects.slice(0, 3);
  if (chosen.length < 2) return singleProjection();

  const anchors: Anchor[] = ['left', 'right', 'bottom_right'];
  return chosen.map((surface, i) => ({
    id: `p${i}`,
    anchor: anchors[i] ?? 'centre',
    scale: Math.max(MIN_SCALE, 1 / chosen.length),
    minimised: false,
    subjectId: surface.id,
  }));
}

/**
 * Minimise or restore every projection.
 *
 * Minimised is small, not gone. A presence that can be dismissed entirely is
 * one an operator can lose — and the presence is where the alert state is
 * shown, so losing it means losing the one element that says the kill switch
 * tripped. `scale` floors at `MIN_SCALE` rather than reaching zero.
 */
export function minimiseProjections(projections: readonly Projection[], minimised: boolean): Projection[] {
  return projections.map((p) => ({
    ...p,
    minimised,
    scale: minimised ? MIN_SCALE : Math.max(MIN_SCALE, p.subjectId ? p.scale : 1),
  }));
}

export function repositionProjections(projections: readonly Projection[], anchor: Anchor): Projection[] {
  return projections.map((p) => ({ ...p, anchor }));
}

/** Read a projection command. Null when none was named. */
export type ProjectionIntent =
  | { kind: 'minimise' }
  | { kind: 'restore' }
  | { kind: 'split' }
  | { kind: 'merge' }
  | { kind: 'move'; anchor: Anchor };

export function readProjection(phrase: string): ProjectionIntent | null {
  const text = (phrase ?? '').toLowerCase();

  if (/\b(split (yourself|into|up)|two of you|multiple projections)\b/.test(text)) return { kind: 'split' };
  if (/\b(come back together|merge|just one of you|single projection)\b/.test(text)) return { kind: 'merge' };
  if (/\b(minimi[sz]e|get small|shrink|out of the way|step aside)\b/.test(text)) return { kind: 'minimise' };
  if (/\b(come back|full size|restore yourself|maximi[sz]e)\b/.test(text)) return { kind: 'restore' };

  const move = /\b(?:move|go|stand|sit)\s+(?:to\s+)?(?:the\s+)?(left|right|cent(?:re|er)|top left|bottom right)\b/.exec(text);
  if (move?.[1]) {
    const word = move[1];
    const anchor: Anchor =
      word === 'left' ? 'left'
      : word === 'right' ? 'right'
      : word === 'top left' ? 'top_left'
      : word === 'bottom right' ? 'bottom_right'
      : 'centre';
    return { kind: 'move', anchor };
  }
  return null;
}

// ── contextual transformation (§7) ────────────────────────────────────────────

/**
 * What the presence turns into for a given subject.
 *
 * §7 asks for "contextual transformation into scientific representations". The
 * restraint that makes it useful rather than a toy: it transforms only when the
 * representation *is* the subject. Discussing a loss distribution, the presence
 * becoming a distribution is a second view of the thing being discussed.
 * Discussing anything else, it stays a core, because a presence that
 * reshapes constantly is a distraction wearing the costume of information.
 */
export type Representation = 'core' | 'distribution' | 'network' | 'waveform' | 'timeline';

const BY_KIND: Record<string, Representation> = {
  distribution: 'distribution',
  network: 'network',
  timeline: 'timeline',
  chart: 'waveform',
};

export function representationFor(subject: Surface | null | undefined): Representation {
  if (!subject) return 'core';
  return BY_KIND[subject.kind] ?? 'core';
}

// ── the renderer abstraction (§7) ─────────────────────────────────────────────

export type RendererId = 'canvas2d' | 'webgl' | 'webxr' | 'holographic';

export interface RendererInfo {
  id: RendererId;
  name: string;
  /** Whether this deployment can actually use it. */
  available: boolean;
  /** Why not, when it is not. Never blank for an unavailable renderer. */
  reason: string;
}

/**
 * Every backend §7 names, and the truth about each.
 *
 * A `webxr` entry marked available with no implementation behind it would be
 * exactly the omission the capability registry exists to catch — so the three
 * that do not exist say so, and say why.
 */
export const RENDERERS: readonly RendererInfo[] = [
  { id: 'canvas2d', name: '2D canvas', available: true, reason: '' },
  {
    id: 'webgl',
    name: 'WebGL',
    available: false,
    reason: 'No WebGL backend is implemented in this deployment.',
  },
  {
    id: 'webxr',
    name: 'WebXR (AR/VR)',
    available: false,
    reason: 'No WebXR backend is implemented, and no headset session is requested.',
  },
  {
    id: 'holographic',
    name: 'Holographic display',
    available: false,
    reason: 'No holographic display driver is present.',
  },
];

/**
 * Pick a renderer.
 *
 * Returns the requested one only if it exists. Falling back silently to 2D
 * would let a deployment believe it was rendering in VR, and the operator would
 * have no way to tell from the screen — which is the same class of defect as a
 * ring drawn for an unmeasured number.
 */
export function selectRenderer(requested?: RendererId): { renderer: RendererInfo; fellBack: boolean; reason: string } {
  const fallback = RENDERERS[0] as RendererInfo;
  if (!requested) return { renderer: fallback, fellBack: false, reason: '' };

  const found = RENDERERS.find((r) => r.id === requested);
  if (found?.available) return { renderer: found, fellBack: false, reason: '' };

  return {
    renderer: fallback,
    fellBack: true,
    reason: found ? found.reason : `Unknown renderer ${requested}.`,
  };
}

export function availableRenderers(): RendererInfo[] {
  return RENDERERS.filter((r) => r.available);
}
