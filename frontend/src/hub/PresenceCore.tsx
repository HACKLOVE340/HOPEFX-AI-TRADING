/**
 * hub/PresenceCore.tsx — the AI presence, drawn.
 *
 * Phase 1 of the AI Hub specification (§7 holographic presence, §23 animation
 * engine independent of business logic, §27 accessibility).
 *
 * ## The canvas is decoration; the text is the content
 *
 * Everything the rings express is also written beside them. The canvas is
 * `aria-hidden` and the readout is a polite live region, so the presence is
 * fully usable with the sound off, with a screen reader, or with reduced motion
 * on. §27 requires never relying on colour alone; this goes further and never
 * relies on the drawing at all.
 *
 * ## It computes nothing
 *
 * This component takes a `Presence` and draws it. It does not know what a job
 * is, or what stale means, or when to be alarmed — `hub/presence.ts` decides all
 * of that as a pure function of real inputs. §30-J asks for business logic kept
 * separate from visual animation, and the practical benefit is that every state
 * is reachable in a test without standing up a WebSocket.
 *
 * ## What the three rings mean
 *
 * They are the existing `.ai-hologram-stage` idea — two counter-rotating orbital
 * rings and a scan-line, which already exist in `index.css` and are preserved —
 * redrawn on canvas so they can be driven by numbers rather than by a fixed
 * keyframe:
 *
 *   outer   activity      rotates with `intensity`; stops dead when offline
 *   middle  risk headroom the sweep IS the percentage, drawn only when known
 *   inner   the presence  breathes at rest, pulses while it works
 */

import React, { useEffect, useRef } from 'react';
import type { Presence, PresenceState, PresenceTone } from './presence';
import {
  gazeToward,
  headMesh,
  headOffset,
  headSurface,
  mouthFor,
  particleField,
  type Gaze,
  type HeadMesh,
  type HeadMeshOptions,
  type Strand,
  type SurfaceQuad,
  posePrint,
} from './head';
import {
  blinkAt,
  chooseHeadMode,
  expressionFor,
  signalsFromPresence,
  type HeadMode,
} from './headModes';
import type { Representation } from './projection';
import { liveRegions } from './a11yLiveRegion';

/** Colour per tone, from the platform's own palette (COLOR in AICore.tsx). */
const TONE: Record<PresenceTone, string> = {
  ok: '#42d392',
  info: '#73a7ff',
  warn: '#f5b84b',
  bad: '#f36d78',
  dead: '#70809a',
};

/**
 * A word for every state.
 *
 * §27: never rely on colour alone for critical meaning. A red ring and an amber
 * ring are the same ring to a colourblind operator, and the same ring to anyone
 * looking away when it changed.
 */
const WORD: Record<PresenceState, string> = {
  idle: 'Standing by',
  listening: 'Listening',
  thinking: 'Working',
  speaking: 'Speaking',
  explaining: 'Explaining',
  alerting: 'Needs you',
  degraded: 'Degraded',
  offline: 'Offline',
};

const CORE_BLUE = '#73a7ff';

/**
 * The hologram's own palette, from the owner's reference (2026-09-15).
 *
 * Cyan rather than the rings' periwinkle, and deliberately a different hue from
 * every tone in `TONE`: the head's structure must never be confused with the
 * head's reading. The brows, the mouth and the eyes are drawn in the tone
 * colour and the mesh is drawn in this, so a red brow on a cyan skull is
 * unambiguous where a red brow on a red skull is decoration.
 *
 * It lives in `index.css` as `--holo` / `--holo-bright` and is read from there
 * at runtime. A canvas cannot resolve a `var()` — it is not the cascade — so
 * the value has to be pulled out rather than written into a fill string. Doing
 * it this way is what lets the light theme darken the hologram instead of
 * painting a bright cyan wireframe onto a near-white page.
 *
 * The fallback is `CORE_BLUE`, deliberately rather than a copy of the token's
 * value: a second copy of a colour is a second thing to update, and the colour
 * ratchet counts one in a comment for the same reason — a literal written
 * anywhere is a literal the next contributor copies. The fallback is only
 * reached where computed style reports nothing, which is jsdom and a detached
 * element; in a browser the tokens always win.
 */
let HOLO = CORE_BLUE;
let HOLO_BRIGHT = CORE_BLUE;

function readHoloPalette(el: Element): void {
  try {
    const style = getComputedStyle(el);
    const a = style.getPropertyValue('--holo').trim();
    const b = style.getPropertyValue('--holo-bright').trim();
    if (a) HOLO = a;
    if (b) HOLO_BRIGHT = b;
  } catch {
    // jsdom and a detached element both land here. The fallbacks above are the
    // dark theme, which is the platform's default, so the head still draws.
  }
}

export interface PresenceCoreProps {
  presence: Presence;
  /** Overrides the media query. The review surface and tests set it directly. */
  reducedMotion?: boolean;
  size?: number;
  /**
   * What is being said right now, and how far through synthesis has got (§7
   * lip sync). Progress is a real character index or a playback position;
   * `null` means nobody measured it, and the mouth then holds a steady shape
   * rather than animating from a clock.
   */
  utterance?: string;
  speechProgress?: number | null;
  speaking?: boolean;
  /**
   * Measured rect of the panel being discussed (§7 "move toward the panel being
   * discussed", "pointing overlays"). Null when nothing is, or when it has no
   * measured rect — the head then faces forward and makes no gesture, rather
   * than pointing confidently at the origin.
   */
  targetRect?: { x: number; y: number; width: number; height: number } | null;
  /**
   * §7 contextual transformation. `core` is the head and rings; the others
   * replace the head with a second view of the subject being discussed.
   *
   * The rings are never replaced whatever this says — they carry the activity
   * and risk-headroom measurements, and a transformation that took those off
   * the screen would be a decoration removing data.
   */
  representation?: Representation;
  /**
   * Hold the head at one face, for the review surface only.
   *
   * There is no other way to set the mode. `chooseHeadMode` reads the same
   * measurements the presence machine reads and picks the face they justify —
   * see `hub/headModes.ts` for why a settable mood would be a lie with a face.
   */
  forceMode?: HeadMode;
  /** The microphone is capturing, and a camera is delivering frames. Measured, not permitted. */
  micOpen?: boolean;
  visionLive?: boolean;
  /** The platform declined to act, and recorded why. */
  refused?: boolean;
  /**
   * How much of the core the head takes up, as a multiple of its default.
   *
   * The AI Core plane has room for the head and the rings at their own scales.
   * A 56-pixel dock does not: at 1 the face there is about thirteen pixels
   * across. The rings are never dropped — they carry activity and risk
   * headroom — so the head grows inside them instead.
   */
  headScale?: number;
}

/**
 * The scientific figures §7 asks for, drawn where the head would be.
 *
 * Deliberately schematic rather than plotted from data: this is the presence
 * taking the *shape* of the subject, and the panel beside it holds the real
 * numbers. Drawing a half-size unlabelled copy of a distribution here and
 * calling it the distribution would be two charts disagreeing about which is
 * authoritative.
 */
function drawRepresentation(
  ctx: CanvasRenderingContext2D,
  kind: Representation,
  hr: number,
  hue: string,
  t: number,
): void {
  ctx.strokeStyle = hue;
  ctx.globalAlpha = 0.75;
  ctx.lineWidth = 2;

  if (kind === 'distribution') {
    ctx.beginPath();
    for (let i = 0; i <= 40; i += 1) {
      const x = (i / 40) * 2 - 1;
      const y = -Math.exp(-(x * x) * 4);
      const px = x * hr * 0.8;
      const py = y * hr * 0.7 + hr * 0.4;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
    return;
  }

  if (kind === 'waveform') {
    ctx.beginPath();
    for (let i = 0; i <= 48; i += 1) {
      const x = (i / 48) * 2 - 1;
      const py = Math.sin(x * 5 + t * 0.002) * hr * 0.35;
      const px = x * hr * 0.85;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
    return;
  }

  if (kind === 'timeline') {
    ctx.beginPath();
    ctx.moveTo(-hr * 0.85, 0);
    ctx.lineTo(hr * 0.85, 0);
    ctx.stroke();
    for (let i = 0; i < 5; i += 1) {
      const px = -hr * 0.7 + (i / 4) * hr * 1.4;
      ctx.beginPath();
      ctx.arc(px, 0, hr * 0.07, 0, Math.PI * 2);
      ctx.stroke();
    }
    return;
  }

  // network
  const nodes = 6;
  const points: [number, number][] = [];
  for (let i = 0; i < nodes; i += 1) {
    const a = (i / nodes) * Math.PI * 2 + t * 0.0002;
    points.push([Math.cos(a) * hr * 0.62, Math.sin(a) * hr * 0.62]);
  }
  ctx.globalAlpha = 0.3;
  for (let i = 0; i < nodes; i += 1) {
    for (let j = i + 1; j < nodes; j += 1) {
      if ((i + j) % 2 !== 0) continue;
      ctx.beginPath();
      ctx.moveTo(points[i]![0], points[i]![1]);
      ctx.lineTo(points[j]![0], points[j]![1]);
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 0.85;
  ctx.fillStyle = hue;
  for (const [px, py] of points) {
    ctx.beginPath();
    ctx.arc(px, py, hr * 0.08, 0, Math.PI * 2);
    ctx.fill();
  }
}

/**
 * How far the head may turn to look at a panel, in radians.
 *
 * Bounded small on purpose. §7 asks the presence to "move toward the panel
 * being discussed"; a head that swung a full ninety degrees would present its
 * profile to the operator and take their eye off the panel it is pointing at,
 * which is the opposite of the point.
 */
const MAX_YAW = 0.5;
const MAX_PITCH = 0.3;

/** Alpha for a strand at a given depth: the far side of the skull is dimmer. */
function depthAlpha(depth: number, base: number): number {
  return base * (0.18 + 0.82 * ((Math.max(-1, Math.min(1, depth)) + 1) / 2) ** 1.6);
}

function strokeStrand(ctx: CanvasRenderingContext2D, strand: Strand): void {
  const points = strand.points;
  if (points.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(points[0]!.x, points[0]!.y);
  for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i]!.x, points[i]!.y);
  ctx.stroke();
}

/**
 * Draw the skull, back to front.
 *
 * Painter's order and a depth-driven alpha are what turn a pile of overlapping
 * arcs into something that reads as a volume. Without them the back of the head
 * is drawn exactly as brightly as the face and the mesh looks like a tangle —
 * which is why `headMesh` cuts each latitude ring into a front arc and a back
 * arc rather than returning whole rings that all average to one depth.
 */
/**
 * Paint the head as a solid, then let `drawMesh` lay its contours over it.
 *
 * Three terms, and each is doing a job:
 *
 *   light  the form. Without it the head is a flat cyan cut-out.
 *   rim    the projection. Fresnel-bright where the surface turns away, so the
 *          jaw, the brow and the bridge of the nose light up on their own and
 *          keep doing it when the head turns.
 *   spec   the highlight. Lambert alone is matte, and a matte cyan solid reads
 *          as a tinted silhouette rather than a lit form.
 *
 * ## It is painted once per POSE, not once per frame
 *
 * A head is about 900 visible quads, and canvas has no way to draw them but one
 * fill and one seam-stroke each. At sixty frames a second that is 108,000 draw
 * calls per head per second; a review page holding twelve heads measured
 * **3.1 FPS**, and removing the bloom and caching the geometry only took it to
 * 4.1 — because the geometry was never the cost, the draw calls were.
 *
 * So the surface is painted into an offscreen canvas keyed by the pose and
 * blitted with a single `drawImage` on every frame that did not move it. The
 * pose barely changes between frames — under reduced motion it does not change
 * at all — so the common case is one image copy where there were eighteen
 * hundred calls.
 *
 * The travelling band cannot live in that bitmap, because it moves every frame
 * while the pose does not. It is drawn after the blit, over the few dozen quads
 * it currently covers.
 */
interface SurfaceCache {
  key: string;
  canvas: HTMLCanvasElement | null;
  half: number;
}

/**
 * One cache per component, not one per module.
 *
 * A module-level cache is worse than none when more than one head is on screen:
 * each head's pose evicts the last, so every head repaints every frame and the
 * lookup is pure overhead. Measured on the eleven-mode review page, a shared
 * cache left the frame rate exactly where it was.
 */
function newSurfaceCache(): SurfaceCache {
  return { key: '', canvas: null, half: 0 };
}

/** Colour for one quad, without the travelling band. */
function quadPaint(quad: SurfaceQuad, intensity: number): string {
  // A gentle ramp: with one flat colour per quad, every exponent is also a
  // contrast multiplier on the seams between them.
  const lit = quad.light ** 1.7 * (0.72 + intensity * 0.28);
  // The rim used to be bloomed with `shadowBlur`, the most expensive operation
  // in the 2D context. The edge is brightened by colour instead, which costs
  // nothing and is a difference nobody could point at in the result.
  const edge = quad.rim ** 0.8;
  const spec = quad.spec;
  const r = 4 + lit * 22 + edge * 190 + spec * 110;
  const g = 20 + lit * 122 + edge * 242 + spec * 170;
  const b = 32 + lit * 142 + edge * 252 + spec * 195;
  const alpha = 0.36 + lit * 0.3 + edge * 0.46 + spec * 0.18;
  return `rgba(${Math.round(Math.min(255, r))},${Math.round(Math.min(255, g))},${Math.round(Math.min(255, b))},${Math.min(1, alpha)})`;
}

function fillQuad(ctx: CanvasRenderingContext2D, quad: SurfaceQuad, paint: string): void {
  ctx.fillStyle = paint;
  const [a, b, c, d] = quad.points;
  ctx.beginPath();
  ctx.moveTo(a!.x, a!.y);
  ctx.lineTo(b!.x, b!.y);
  ctx.lineTo(c!.x, c!.y);
  ctx.lineTo(d!.x, d!.y);
  ctx.closePath();
  ctx.fill();
  // Close the seam. A hairline stroke in the fill's own colour costs one extra
  // call and removes the dark grid a pure fill leaves behind.
  ctx.strokeStyle = paint;
  ctx.lineWidth = 0.9;
  ctx.stroke();
}

function drawSurface(
  ctx: CanvasRenderingContext2D,
  cache: SurfaceCache,
  quads: readonly SurfaceQuad[],
  options: HeadMeshOptions,
  intensity: number,
  now: number,
  still: boolean,
): void {
  const half = Math.ceil(options.radius * 2.3) + 2;
  // Intensity is quantised into the key: it only scales the lit term, and
  // repainting nine hundred quads because a measurement moved by a thousandth
  // would defeat the point of caching at all.
  const key = `${posePrint(options)}|${half}|${Math.round(intensity * 8)}`;

  if (cache.key !== key || !cache.canvas) {
    const off = cache.canvas ?? document.createElement('canvas');
    if (off.width !== half * 2 || off.height !== half * 2) {
      off.width = half * 2;
      off.height = half * 2;
    }
    const octx = off.getContext('2d');
    if (!octx) return;
    octx.clearRect(0, 0, off.width, off.height);
    octx.save();
    octx.translate(half, half);
    octx.lineCap = 'round';
    octx.lineJoin = 'round';
    for (const quad of quads) fillQuad(octx, quad, quadPaint(quad, intensity));
    octx.restore();
    cache.key = key;
    cache.canvas = off;
    cache.half = half;
  }

  ctx.globalAlpha = 1;
  ctx.drawImage(cache.canvas, -cache.half, -cache.half);

  // The band, over the top. It moves every frame while the pose does not, so it
  // cannot be baked into the bitmap — and it only ever covers a few dozen
  // quads, which is a rounding error against the nine hundred below it.
  if (still) return;
  const phase = ((now % SCAN_MS) + SCAN_MS) % SCAN_MS / SCAN_MS;
  const bandV = (1 - 2 * Math.abs(phase - 0.5)) * 1.9 - 0.95;
  for (const quad of quads) {
    const d = (quad.v - bandV) / 0.028;
    if (d * d > 9) continue;
    const strength = Math.exp(-(d * d));
    const paint = `rgba(${Math.round(130 + strength * 110)},${Math.round(190 + strength * 60)},${Math.round(205 + strength * 45)},${(0.1 + strength * 0.5).toFixed(3)})`;
    fillQuad(ctx, quad, paint);
  }
}

/** How long the band takes to travel the head and back, in milliseconds. */
const SCAN_MS = 3200;

function drawMesh(
  ctx: CanvasRenderingContext2D,
  mesh: HeadMesh,
  hue: string,
  intensity: number,
  now: number,
): void {
  // Barely there.
  //
  // The contours carried the whole head before there was a surface under them,
  // and at that weight over a shaded solid they are what still reads as
  // "wireframe" rather than "hologram" — a grid drawn ON a face instead of the
  // fine structure OF one. They are kept rather than dropped because they are
  // what the crown and the jaw line are made of where the shading runs flat.
  const base = 0.045 + intensity * 0.05;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // The soft volume that used to be drawn here is now `drawSurface`, which
  // paints the head as a lit solid rather than as a glow behind a cage. The
  // contours below are laid OVER it, so they are the fine structure and no
  // longer carry the form on their own — hence the much lower `base`.

  // Bloom. A hologram is light, and light spills; without this the mesh is a
  // technical drawing of a head rather than a projection of one.
  ctx.shadowColor = HOLO;
  ctx.shadowBlur = 7;

  // The neck, behind and below. Dimmer than the face on purpose — it is what
  // makes the head a person rather than an object, and it is not what anyone is
  // reading.
  ctx.strokeStyle = HOLO;
  for (const strand of mesh.neck) {
    ctx.globalAlpha = depthAlpha(strand.depth, base * 0.5);
    ctx.lineWidth = strand.depth > 0 ? 1 : 0.6;
    strokeStrand(ctx, strand);
  }

  // The skull, back to front. Painter's order plus a depth-driven alpha is what
  // turns a pile of overlapping arcs into a volume — which is why `headMesh`
  // cuts each latitude ring into a front arc and a back arc rather than
  // returning whole rings that all average to one depth.
  const strands = [...mesh.shell, ...mesh.jaw].sort((a, b) => a.depth - b.depth);
  for (const strand of strands) {
    const front = strand.depth > 0;
    ctx.globalAlpha = depthAlpha(strand.depth, base);
    // The rim reads brightest, as it does on a real projection: the surface
    // there is nearly edge-on, so more of it is between you and the light.
    ctx.strokeStyle = strand.depth > 0.72 ? HOLO_BRIGHT : HOLO;
    ctx.lineWidth = front ? 0.8 : 0.45;
    strokeStrand(ctx, strand);
  }

  // The brows carry the reading, so they are drawn in the tone's colour at full
  // weight — they must survive a glance at a thumbnail.
  ctx.strokeStyle = hue;
  ctx.lineWidth = 2.4;
  for (const brow of mesh.brows) {
    ctx.globalAlpha = depthAlpha(brow.depth, 0.98);
    strokeStrand(ctx, brow);
  }

  // Eyes. Squashed by openness rather than scaled: a shut eye is a line across
  // the socket, whereas an eye that shrank to a dot would read as a pupil
  // contracting, which means something else.
  for (const eye of mesh.eyes) {
    if (eye.z < -0.35) continue; // round the far side of the head
    const open = Math.max(0, Math.min(1, eye.openness));
    const height = Math.max(0.5, eye.radius * 0.62 * open);
    ctx.globalAlpha = depthAlpha(eye.z, 0.98);
    ctx.fillStyle = hue;
    ctx.beginPath();
    ctx.ellipse(eye.x, eye.y, eye.radius, height, 0, 0, Math.PI * 2);
    ctx.fill();
    // The pupil, cut back out of the eye. Dilation is a reading — wide when
    // alarmed, narrow while concentrating — and a solid dot cannot carry it.
    if (open > 0.25) {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.ellipse(eye.x, eye.y, eye.pupilRadius, Math.min(height * 0.8, eye.pupilRadius), 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalCompositeOperation = 'source-over';
      ctx.shadowBlur = 7;
    }
  }

  // The mouth. Both halves in the tone's colour at full weight — this is the
  // part of the face that has to survive a glance at a 56-pixel dock, and it is
  // the only one carrying what is actually being said.
  ctx.strokeStyle = hue;
  ctx.lineWidth = 2.4;
  ctx.globalAlpha = depthAlpha(mesh.mouth.upper.depth, 0.98);
  strokeStrand(ctx, mesh.mouth.upper);
  strokeStrand(ctx, mesh.mouth.lower);

  // The scan ring. The one thing here a clock may move, which is why it is the
  // one thing reduced motion removes — `headMesh` returns null for it then.
  if (mesh.scan) {
    ctx.globalAlpha = 0.62 + Math.sin(now * 0.004) * 0.14;
    ctx.strokeStyle = HOLO_BRIGHT;
    ctx.lineWidth = 2;
    ctx.shadowBlur = 12;
    strokeStrand(ctx, mesh.scan);
  }

  ctx.shadowBlur = 0;
  ctx.globalAlpha = 1;
}

export const PresenceCore: React.FC<PresenceCoreProps> = ({
  presence, reducedMotion, size = 300,
  utterance = '', speechProgress = null, speaking = false, targetRect = null,
  representation = 'core',
  forceMode, micOpen = false, visionLive = false, refused = false, headScale = 1,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Read every frame without re-running the animation effect.
  const voice = useRef({
    utterance, speechProgress, speaking, targetRect, representation,
    forceMode, micOpen, visionLive, refused, headScale,
  });
  voice.current = {
    utterance, speechProgress, speaking, targetRect, representation,
    forceMode, micOpen, visionLive, refused, headScale,
  };
  // A ref, not state: the animation reads the newest presence every frame
  // without the frame loop being a dependency of a re-render.
  /** The painted surface, cached per head. See `newSurfaceCache`. */
  const surfaceCache = useRef<SurfaceCache>(newSurfaceCache());
  const latest = useRef(presence);
  latest.current = presence;

  // Take the app's polite live region, and give it back on unmount. Claiming
  // by name is what lets a second claimant be refused with the incumbent's
  // name in the message, instead of quietly rendering a competing region.
  useEffect(() => {
    liveRegions.claim('polite', 'PresenceCore');
    return () => {
      liveRegions.release('polite', 'PresenceCore');
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const still =
      reducedMotion ??
      (typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    readHoloPalette(canvas);

    let raf = 0;
    let spin = 0;
    let last = performance.now();

    const draw = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      const p = latest.current;
      const hue = TONE[p.tone];
      const S = canvas.width;
      const C = S / 2;

      if (!still && p.state !== 'offline') spin += dt * 0.0006 * (0.4 + p.intensity * 1.6);
      ctx.clearRect(0, 0, S, S);

      const v = voice.current;
      const coreRect = canvas.getBoundingClientRect();
      const gaze: Gaze | null = gazeToward(coreRect, v.targetRect ?? null);
      const lean = headOffset(gaze, S, still);

      // §7 particle field, "used with restraint" — none under reduced motion,
      // none when offline, and the count tracks measured intensity so a quiet
      // system looks quiet.
      for (const particle of particleField(now, {
        intensity: p.intensity,
        reducedMotion: still,
        offline: p.state === 'offline',
      })) {
        ctx.globalAlpha = particle.alpha;
        ctx.fillStyle = hue;
        ctx.beginPath();
        ctx.arc(C + particle.x * C * 0.9, C + particle.y * C * 0.9, particle.radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // Outer — activity. Stops dead when offline, which is the honest reading:
      // there is nothing arriving to rotate for.
      ctx.save();
      ctx.translate(C, C);
      ctx.rotate(still ? 0 : spin);
      ctx.strokeStyle = p.state === 'offline' ? TONE.dead : CORE_BLUE;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      for (let i = 0; i < 36; i++) {
        const a = (i / 36) * Math.PI * 2;
        const long = i % 6 === 0;
        ctx.globalAlpha = long ? 0.9 : 0.36;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * (C * 0.84), Math.sin(a) * (C * 0.84));
        ctx.lineTo(Math.cos(a) * (C * (long ? 0.77 : 0.8)), Math.sin(a) * (C * (long ? 0.77 : 0.8)));
        ctx.stroke();
      }
      ctx.restore();

      // Middle — risk headroom. Drawn only when it is known: a full ring for an
      // unmeasured number is a confident claim about nothing.
      ctx.save();
      ctx.translate(C, C);
      ctx.strokeStyle = 'rgba(30,45,71,.9)';
      ctx.lineWidth = 14;
      ctx.globalAlpha = 1;
      ctx.beginPath();
      ctx.arc(0, 0, C * 0.66, 0, Math.PI * 2);
      ctx.stroke();
      if (p.headroomKnown) {
        ctx.strokeStyle = hue;
        ctx.lineCap = 'round';
        ctx.globalAlpha = 0.92;
        ctx.beginPath();
        ctx.arc(0, 0, C * 0.66, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0.02, headroomOf(p)));
        ctx.stroke();
      }
      ctx.restore();

      // Inner — the presence itself. Breathes at rest, pulses while it works.
      const breathe = still ? 0.5 : Math.sin(now * 0.0016) * 0.5 + 0.5;
      const r = C * 0.39 + breathe * 10 * (0.25 + p.intensity * 0.75);
      // A halo behind the head, not a wash over it. At the old peak alpha the
      // wireframe was measurably there and unreadable — the mesh and the glow
      // are the same blue, and the brighter one wins.
      const glow = ctx.createRadialGradient(C, C, r * 0.2, C, C, C * 0.62);
      glow.addColorStop(0, `rgba(115,167,255,${0.1 + p.intensity * 0.16})`);
      glow.addColorStop(0.55, `rgba(115,167,255,${0.05 + p.intensity * 0.08})`);
      glow.addColorStop(1, 'rgba(115,167,255,0)');
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(C, C, C * 0.62, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = `rgba(115,167,255,${0.28 + p.intensity * 0.3})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(C, C, r, 0, Math.PI * 2);
      ctx.stroke();

      // §7 — the head. Drawn inside the core rather than instead of it: the
      // rings carry measurements (activity, risk headroom) and a face that
      // replaced them would be a decoration replacing data.
      const mouth = mouthFor(v.utterance, v.speechProgress, v.speaking);
      const hx = C + lean.x;
      // Lifted clear of the readout, which now sits in the lower band rather
      // than across the face.
      const hy = C + lean.y - C * 0.13;
      // Sized from the canvas, not from the breathing inner disc.
      //
      // It used to be `r * 0.62`, and `r` is the inner glow's radius at about
      // 0.39 of the half-size — so the face came out at roughly a tenth of the
      // canvas, under the headroom readout, inside a glow. Measured in
      // Chromium at size 220: a head 53 pixels wide with the 34-pixel "0%"
      // printed across it. §7 asks for a holographic head, and that was a
      // detail. Clamped so no caller can push the face out through the risk
      // ring, which is at 0.66 of the half-size.
      const hr = C * 0.46 * Math.max(0.2, Math.min(1.35, v.headScale));

      ctx.save();
      ctx.translate(hx, hy);
      ctx.strokeStyle = `rgba(115,167,255,${0.55 + p.intensity * 0.3})`;
      ctx.lineWidth = 2;

      if (v.representation !== 'core') {
        // §7 contextual transformation. The head becomes a second view of the
        // subject — but only for subjects where the representation IS the
        // thing (`hub/projection.ts` decides), so the presence does not reshape
        // constantly and become a distraction wearing the costume of
        // information.
        drawRepresentation(ctx, v.representation, hr, hue, still ? 0 : now);
        ctx.restore();
        if (!still) raf = requestAnimationFrame(draw);
        return;
      }

      // Skull — a wireframe, drawn from `headMesh`.
      //
      // What was here was an ellipse, two dots and a second ellipse for a
      // mouth. It faced forward always, because an outline has no orientation:
      // `gazeToward` measured where to look and `headOffset` slid the whole
      // drawing a few pixels toward it, which is the most a flat shape can do.
      //
      // §7 asks for "professional", and a wireframe skull is still the answer —
      // a rendered human face on a platform that places orders reads as a
      // mascot. This is the same abstraction with volume: it turns to face what
      // it is looking at, its jaw hinges on the character being spoken, and the
      // far side of it is dimmer than the near side because it is further away.
      //
      // The face it wears comes from `chooseHeadMode`, which reads the same
      // measurements the presence machine reads. Nothing here decides a mood.
      const chosen = chooseHeadMode(
        signalsFromPresence(p, {
          speaking: v.speaking,
          micOpen: v.micOpen,
          visionLive: v.visionLive,
          refused: v.refused,
        }),
        v.forceMode,
      );
      const face = expressionFor(chosen.mode, {
        time: still ? 0 : now,
        severity: chosen.severity,
        reducedMotion: still,
      });

      const meshOptions: HeadMeshOptions = {
        radius: hr * 0.66,
        // The head turns toward the panel being discussed. The bounds are
        // small: §7 wants the presence to draw the eye TO the panel, and a head
        // that swung ninety degrees would take the eye off it.
        yaw: (gaze ? gaze.x * MAX_YAW : 0) + face.sweep,
        pitch: gaze ? gaze.y * MAX_PITCH : 0,
        roll: face.tilt,
        mouthOpenness: mouth.openness,
        lidOpen: Math.max(0, 1 - face.lidClosure - blinkAt(still ? 0 : now, still)),
        brow: face.brow,
        pupil: face.pupil,
        time: still ? 0 : now * face.scanRate,
        reducedMotion: still || face.scanRate === 0,
      };
      const mesh = headMesh(meshOptions);

      // Tremor is a real measurement's amplitude, not a flourish: it is zero
      // for every mode but `panicking`, and scales with how far past the floor
      // the breach is.
      const breath = face.breath === 0 ? 0 : Math.sin(now * 0.001 * face.breathHz * Math.PI * 2) * face.breath;
      ctx.translate(face.tremor, face.tremor * 0.6 + breath * hr * 0.03);

      // The solid first, the contours over it. A wireframe alone lets you see
      // the back of the skull through the front of it however dense it gets,
      // because the problem is that nothing is filled.
      drawSurface(ctx, surfaceCache.current, headSurface(meshOptions), meshOptions, p.intensity, now, still);
      drawMesh(ctx, mesh, hue, p.intensity, still ? 0 : now);
      ctx.restore();

      // §7 pointing overlay: a ray from the core toward the panel being
      // discussed. Only when a rect was measured — see `gazeToward`.
      if (gaze && !still && gaze.reach > 0.02) {
        ctx.save();
        ctx.translate(C, C);
        ctx.strokeStyle = hue;
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 8]);
        ctx.lineDashOffset = -now * 0.02;
        const dir = Math.atan2(gaze.y, gaze.x);
        ctx.beginPath();
        ctx.moveTo(Math.cos(dir) * r * 1.05, Math.sin(dir) * r * 1.05);
        ctx.lineTo(Math.cos(dir) * C * 0.97, Math.sin(dir) * C * 0.97);
        ctx.stroke();
        ctx.restore();
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
      }

      if (!still) raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion]);

  const headroom = presence.headroomKnown ? `${Math.round(headroomOf(presence) * 100)}%` : '—';

  return (
    <section
      // Distinct from the stage's own "AI presence" landmark. Two regions with
      // the same accessible name are two indistinguishable stops in a screen
      // reader's landmark list, and this one is the readout inside the other.
      aria-label="Presence core"
      style={{ display: 'grid', justifyItems: 'center', gap: 16, minWidth: 0 }}
    >
      <div style={{ position: 'relative', width: size, height: size }}>
        <canvas
          ref={canvasRef}
          width={size * 2}
          height={size * 2}
          aria-hidden="true"
          style={{ width: size, height: size, display: 'block' }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'grid',
            // The lower band, not the middle.
            //
            // Centred, this printed "RISK HEADROOM / 0% / AT THE LIMIT" across
            // the head's face. Nothing here is removed — the figure, its label
            // and its qualifier all still read, and they still read at a
            // glance; they have moved off the face and scale with the core so
            // they are legible in the 56-pixel dock as well as on the plane.
            alignContent: 'end',
            justifyItems: 'center',
            paddingBottom: Math.round(size * 0.1),
            textAlign: 'center',
            pointerEvents: 'none',
          }}
        >
          <div style={LABEL}>Risk headroom</div>
          <div
            style={{
              fontSize: Math.max(13, Math.round(size * 0.115)),
              fontWeight: 700,
              lineHeight: 1,
              color: '#e7edf7',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {headroom}
          </div>
          {/* The ring's own qualifier, not the state word — the caption below
              already carries that, and saying it twice wastes the one line
              that could tell an operator what the number means. */}
          <div style={{ ...LABEL, marginTop: 6, color: TONE[presence.tone] }}>
            {presence.headroomKnown ? headroomWord(headroomOf(presence)) : 'Not measured'}
          </div>
        </div>
      </div>

      {/*
        The caption. Same sentence the AI speaks, so the two cannot drift.

        This is the app's only polite live region, and it is held under that
        name in `a11yLiveRegion.ts`. The presence overlay added a second one in
        Phase P; two polite regions interleave, and the operator hears half of
        each sentence. The claim below is what makes a third one refused rather
        than merely noticed in review.
      */}
      <div
        role="status"
        aria-live="polite"
        style={{ maxWidth: '62ch', textAlign: 'center', display: 'grid', gap: 6 }}
      >
        <p style={{ margin: 0, fontSize: 17, lineHeight: 1.55, fontWeight: 300, color: '#e7edf7' }}>
          {presence.reason}
        </p>
        <span style={{ ...LABEL, color: TONE[presence.tone] }}>{WORD[presence.state]}</span>
      </div>
    </section>
  );
};

/**
 * What a headroom figure means, in words.
 *
 * §27 again: a ring that is amber instead of green has said nothing to an
 * operator who cannot distinguish them, or who was not watching when it changed.
 */
function headroomWord(fraction: number): string {
  if (fraction <= 0.1) return 'At the limit';
  if (fraction <= 0.3) return 'Running low';
  return 'Within limits';
}

const LABEL: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '.13em',
  textTransform: 'uppercase',
  color: '#70809a',
};

/**
 * The headroom the ring should sweep.
 *
 * `Presence` carries `intensity` for the animation and `headroomKnown` for
 * honesty, but the headroom fraction itself is not on the presence — it is on
 * the inputs. Rather than widen the contract, the reason sentence already
 * contains it, and this reads it back. When it cannot, the ring is not drawn:
 * `headroomKnown` gates that, so an unparsable sentence degrades to no ring
 * rather than to a wrong one.
 */
function headroomOf(p: Presence): number {
  const match = /(\d{1,3})%/.exec(p.reason);
  if (!match) return 0;
  return Math.max(0, Math.min(1, Number(match[1]) / 100));
}
