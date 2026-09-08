/**
 * hub/PresenceStage.tsx — the plane.
 *
 * §1: "Begin with a clean interface centered on a professional advanced
 * holographic AI head or presence." §2: "Do not permanently display every
 * capability... the default interface remains clean."
 *
 * The first build of this put the presence inside the page chrome — sidebar,
 * header, seven tabs — which is the opposite of clean. This takes the whole
 * viewport: a plain dark plane, the core at its centre, nothing else until
 * something is asked for.
 *
 * ## What appears, appears because it was asked for
 *
 * Surfaces are placed by `hub/workspace.ts` and rendered here. The plane holds
 * none of its own: with an empty workspace there is a core and a sentence, and
 * that is the whole screen. §8's ordering — critical dominant, background quiet
 * — is the engine's decision; this reads `span` and lays out to it.
 *
 * ## Escape is always visible
 *
 * A full-screen surface with no way back is a trap. Escape closes it, and a
 * single control says so. Both are always present, never revealed on hover:
 * a way out that has to be discovered is not a way out.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Mic, Minimize2, Send, Square, Volume2, VolumeX, X } from 'lucide-react';

import { PresenceCore } from './PresenceCore';
import { useRovingFocus } from './useRovingFocus';
import { sceneFrom, type Measurement } from './sceneFrom';
import { appendPoint, pointingAt, recogniseGesture, type TrackPoint } from './gestures';
import { useFrameBudget } from './useFrameBudget';
import type { SceneGraph } from './sceneGraph';
import type { Presence } from './presence';
import type { Surface } from './workspace';
import { place, type LayoutName } from './layout';
import { positionOf, type Layer, type Position } from './spatial';
import { singleProjection, type Projection, type Representation } from './projection';
import { SurfaceView } from './SurfaceView';
import { useViewportWidth } from './useViewportWidth';
import { usePrefersReducedMotion } from './usePrefersReducedMotion';

const C = {
  void: '#070c16',
  hull: 'rgba(14,23,40,.82)',
  edge: '#1e2d47',
  edge2: '#2b3d5c',
  text: '#e7edf7',
  dim: '#a7b5c9',
  quiet: '#70809a',
  core: '#73a7ff',
  bad: '#f36d78',
} as const;

const label: React.CSSProperties = {
  fontSize: 9.5,
  fontWeight: 800,
  letterSpacing: '.14em',
  textTransform: 'uppercase',
  color: C.quiet,
};

const control: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 7,
  minHeight: 42,
  padding: '0 14px',
  borderRadius: 9,
  border: `1px solid ${C.edge2}`,
  background: 'linear-gradient(160deg, rgba(24,40,66,.9), rgba(18,30,51,.9))',
  color: C.text,
  fontSize: 12.5,
  fontWeight: 700,
  letterSpacing: '.04em',
  cursor: 'pointer',
};

export interface PresenceStageProps {
  presence: Presence;
  surfaces: readonly Surface[];
  focusedId: string | null;
  listening: boolean;
  muted: boolean;
  sttSupported: boolean;
  transcript: readonly { who: 'ai' | 'user'; text: string; at: number; interrupted?: boolean }[];
  /**
   * How the plane is arranged (§8). The stage does not choose it — the panel
   * does, from what was said or from what is on the plane — so that the same
   * decision is not made in two places with two different answers.
   */
  layout: LayoutName;
  /**
   * Surface ids the AI is talking about right now (§9 target highlighting,
   * §10 "what is being explained receives visual focus").
   *
   * Separate from `focusedId`, which is what the OPERATOR selected. Merging
   * them would make the AI mentioning a panel look like the operator having
   * chosen it, and closing the "focused" panel would then behave differently
   * depending on who was speaking.
   */
  spokenAbout?: readonly string[];
  /** §9 breadcrumbs: where the operator has drilled to. Root first. */
  trail?: readonly Layer[];
  onBreadcrumb?: (index: number) => void;
  /**
   * Measured positions of the rendered panels, reported upward (§9 coordinate
   * and viewport awareness).
   *
   * Measured, never derived from the grid the layout engine asked for: that
   * would be wrong the moment anything wrapped, scrolled, or folded into the
   * background stack, and wrong in the direction that has the AI pointing an
   * operator at the wrong corner of their own screen.
   */
  onPositions?: (positions: Record<string, Position>) => void;
  /**
   * The measured scene (§9), from the same pass that produces `onPositions`.
   *
   * Separate from `onPositions` because the two answer different questions and
   * one of them was being thrown away: `positionOf` reduces a rectangle to
   * which ninth of the screen it is in, which cannot answer "the panel to the
   * left of that one". The rectangles were already being read; until this,
   * nothing kept them, and `sceneGraph.ts` had no producer at all.
   */
  onScene?: (scene: SceneGraph) => void;
  /**
   * §6: which register the AI is speaking in. Named on screen, always.
   *
   * A mode that changes how much scaffolding goes round a number, without
   * saying which mode is in force, leaves an operator unable to tell whether
   * "you have used most of your room" is the whole story.
   */
  modeName?: string;
  accent?: string;
  /** §7 lip sync — a real character index or playback position, or null. */
  utterance?: string;
  speechProgress?: number | null;
  speaking?: boolean;
  /** §7: how many projections there are, where, and how large. */
  projections?: readonly Projection[];
  /** §7: what shape the presence takes for what is being discussed. */
  representation?: Representation;
  onCommand: (phrase: string) => void;
  onTalk: () => void;
  onStop: () => void;
  onToggleMute: () => void;
  onCloseSurface: (id: string) => void;
  onPinSurface: (id: string) => void;
  /** §21 drill-down: a mark inside a panel was clicked. */
  onDrillSurface?: (surface: Surface, label: string) => void;
  onExit: () => void;
}

export const PresenceStage: React.FC<PresenceStageProps> = ({
  presence, surfaces, focusedId, listening, muted, sttSupported, transcript, layout, spokenAbout = [],
  trail = [], onBreadcrumb, onPositions, modeName, accent,
  utterance = '', speechProgress = null, speaking = false, onScene,
  projections, representation = 'core',
  onCommand, onTalk, onStop, onToggleMute, onCloseSurface, onPinSurface, onDrillSurface, onExit,
}) => {
  const [typed, setTyped] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const planeRef = useRef<HTMLDivElement>(null);

  // Escape leaves. A full-screen surface with no way out is a trap, and the
  // keyboard route matters more than the button for anyone not using a mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onExit();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onExit]);

  const submit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const phrase = typed.trim();
      if (!phrase) return;
      onCommand(phrase);
      setTyped('');
    },
    [typed, onCommand],
  );

  const lastFew = useMemo(() => transcript.slice(-3), [transcript]);

  // Measured, not assumed. A three-of-twelve panel is ninety pixels wide on a
  // phone: it renders, it passes a screenshot test, and nobody can read it.
  const width = useViewportWidth();

  // §7 projections. The first one drives the main presence; a split adds the
  // rest as smaller companions beside it.
  const shownProjections = projections && projections.length > 0 ? projections : singleProjection();
  const primary = shownProjections[0] ?? singleProjection()[0]!;
  const anchor = primary.anchor;
  const scale = primary.scale;
  // Focus moved by a gesture. Held here rather than pushed up so the stage
  // works standalone; a parent that owns focus is followed the moment it
  // changes `focusedId`.
  const [gestureFocus, setGestureFocus] = useState<string | null>(null);
  useEffect(() => {
    setGestureFocus(null);
  }, [focusedId]);
  /**
   * The one focus the plane draws itself around.
   *
   * Everything that asks "which surface is focused" reads THIS, layout
   * included. Leaving `place()` on the raw prop gave the plane two notions of
   * focus at once: a focus layout went on enlarging the panel the operator had
   * selected while outlining the one they had just swiped to.
   */
  const shownFocus = gestureFocus ?? focusedId;

  const placements = useMemo(
    () => place(surfaces, { layout, focusedId: shownFocus, viewport: { width }, collapseBackground: true }),
    [surfaces, layout, shownFocus, width],
  );
  const visible = placements.filter((p) => p.visible);
  const shown = visible.filter((p) => !p.collapsed);
  const stacked = visible.filter((p) => p.collapsed);
  const hidden = placements.length - visible.length;
  const hasSurfaces = visible.length > 0;

  /**
   * §18's pointer half, given the caller it never had.
   *
   * `recogniseGesture` and `pointingAt` were written in Phase E2 and imported
   * by nothing outside their own tests — the dead control this file's own
   * docstring warns about, on the input side. `pointingAt` could not have been
   * wired then: the scene graph had no producer until `sceneFrom` landed here.
   *
   * **Only reversible actions are bound.** `gestures.ts` says a wrongly
   * recognised swipe moves a panel somebody was reading, so a swipe changes
   * FOCUS — reversible, and already reachable by clicking — and a long press
   * pins, which is a toggle with a button beside it. Nothing here closes a
   * panel, leaves the plane, or touches an order.
   */
  const sceneRef = useRef<SceneGraph | null>(null);
  const track = useRef<TrackPoint[] | null>(null);
  const trackStart = useRef(0);

  const onPlanePointerDown = useCallback((event: React.PointerEvent) => {
    trackStart.current = performance.now();
    track.current = [{ x: event.clientX, y: event.clientY, t: 0 }];
  }, []);

  const onPlanePointerMove = useCallback((event: React.PointerEvent) => {
    if (track.current === null) return;
    // Bounded. A pointer held down emits a move per frame, and `appendPoint`
    // is where the ceiling lives because that is where the recogniser says
    // what it actually reads.
    appendPoint(track.current, {
      x: event.clientX,
      y: event.clientY,
      t: performance.now() - trackStart.current,
    });
  }, []);

  const onGesture = useCallback(
    (event: React.PointerEvent) => {
      const points = track.current;
      track.current = null;
      if (points === null) return;
      appendPoint(points, { x: event.clientX, y: event.clientY, t: performance.now() - trackStart.current });

      const gesture = recogniseGesture(points);
      // Null is the common case and the safe one: a movement that is not
      // clearly anything does nothing at all.
      if (gesture === null) return;
      const scene = sceneRef.current;
      if (scene === null) return;

      const first = points[0]!;
      if (gesture === 'long_press') {
        const under = pointingAt(scene, first.x, first.y);
        if (under !== null) onPinSurface(under);
        return;
      }

      const anchor = shownFocus ?? pointingAt(scene, first.x, first.y);
      if (anchor === null || !scene.ids().includes(anchor)) return;
      const direction =
        gesture === 'swipe_left'
          ? 'left'
          : gesture === 'swipe_right'
            ? 'right'
            : gesture === 'swipe_up'
              ? 'above'
              : 'below';
      const next = scene.neighbour(anchor, direction);
      // Never wraps. `resolveReference` holds the same rule: a reference that
      // wrapped would move an operator's attention to the far side of the
      // plane, which is the opposite of what they asked for.
      if (next !== null) setGestureFocus(next);
    },
    [onPinSurface, shownFocus],
  );

  /**
   * §26. What the machine can currently afford, measured rather than assumed.
   *
   * The plane is the heaviest thing this app draws — a canvas presence, a grid
   * of live panels, and a projection layer. `nextFidelity` has decided how much
   * of that to draw since Phase D1 and, until this call, was asked by nobody.
   *
   * Reduced motion is passed straight through rather than applied here:
   * `nextFidelity` owns the rule that it is a cap and not one input among
   * several, and applying it twice in two places is how the two come to
   * disagree.
   */
  const reducedMotion = usePrefersReducedMotion();
  const budget = useFrameBudget({ reducedMotion });

  // The collapsed stack is a horizontal toolbar: one tab stop, arrows within.
  // Declaring the axis matters here — the plane scrolls vertically behind it,
  // and swallowing ArrowUp would stop that scroll from a focused chip.
  const stackKeys = useRovingFocus(
    stacked.map(({ surface }) => surface.id),
    { orientation: 'horizontal' },
  );

  /**
   * Measure where the panels ended up.
   *
   * After paint, and again whenever the plane changes shape. A rect read before
   * layout is zero, and `positionOf` returns null for a zero rect rather than
   * calling it "top left" — so a too-early measurement produces no claim rather
   * than a wrong one.
   */
  useEffect(() => {
    // Always measured, even when nobody asked for the reports. §18's gestures
    // resolve through `sceneRef`, so a plane that only measured for an
    // interested parent would answer "what am I pointing at" with nothing on
    // every screen that did not happen to pass `onScene`.
    const measure = () => {
      const root = planeRef.current;
      if (!root) return;
      const viewport = root.getBoundingClientRect();
      const found: Record<string, Position> = {};
      // Document order is paint order, which is what `sceneFrom` turns into z.
      const measurements: Measurement[] = [];
      for (const el of Array.from(root.querySelectorAll('[data-surface-id]'))) {
        const id = el.getAttribute('data-surface-id');
        if (!id) continue;
        const rect = el.getBoundingClientRect();
        const position = positionOf(rect, viewport);
        if (position) found[id] = position;
        // Kept in viewport coordinates, the same frame of reference the
        // rectangles were measured in. Converting to plane-relative here would
        // put two coordinate systems in one scene the first time the plane
        // scrolls.
        measurements.push({ id, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } });
      }
      sceneRef.current = sceneFrom(measurements);
      onPositions?.(found);
      // No containment is declared: these are grid siblings. `sceneFrom`
      // refuses to infer it, and this is the caller that would have been
      // tempted to.
      onScene?.(sceneRef.current);
    };
    const frame = requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', measure);
    };
  }, [onPositions, onScene, surfaces, layout, width]);

  return (
    <div
      role="region"
      aria-label="AI presence"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 60,
        display: 'grid',
        gridTemplateRows: 'auto 1fr auto',
        background: `
          radial-gradient(120% 80% at 50% 32%, rgba(115,167,255,.11), transparent 62%),
          radial-gradient(90% 60% at 50% 100%, rgba(66,211,146,.045), transparent 70%),
          ${C.void}`,
        color: C.text,
        overflow: 'hidden',
      }}
    >
      {/* Scanline. The one piece of pure atmosphere, kept faint enough that it
          never competes with a number. Preserves the existing hologram stage's
          texture (index.css:231) rather than inventing a new one. */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          background: 'repeating-linear-gradient(0deg, rgba(255,255,255,.028) 0 1px, transparent 1px 3px)',
        }}
      />

      {/* Edge rail — identity and link state, pushed to the border so the middle
          stays quiet. */}
      <header
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 14,
          padding: '13px 18px',
          borderBottom: `1px solid ${C.edge}`,
          background: 'linear-gradient(180deg, rgba(16,26,44,.6), transparent)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 800, letterSpacing: '.15em' }}>HOPEFX</span>
          {trail.length > 1 && (
            // §9 layer navigation. Rendered only when there is somewhere to go
            // back to — a breadcrumb trail of one is a label.
            <nav aria-label="Breadcrumbs" style={{ display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 }}>
              {trail.map((layer, i) => (
                <React.Fragment key={`${layer.surfaceId ?? 'root'}-${i}`}>
                  {i > 0 && <span aria-hidden style={{ ...label, color: C.edge2 }}>/</span>}
                  <button
                    type="button"
                    onClick={() => onBreadcrumb?.(i)}
                    aria-current={i === trail.length - 1 ? 'page' : undefined}
                    style={{
                      border: 'none',
                      background: 'none',
                      padding: 0,
                      cursor: 'pointer',
                      fontSize: 11.5,
                      color: i === trail.length - 1 ? C.text : C.quiet,
                      fontWeight: i === trail.length - 1 ? 700 : 500,
                      maxWidth: 160,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {layer.label}
                  </button>
                </React.Fragment>
              ))}
            </nav>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {modeName && (
            <span style={{ ...label, color: accent ?? C.quiet }}>{modeName}</span>
          )}
          <span style={label}>
            {surfaces.length ? `${layout.replace('_', ' ')} · ${surfaces.length} on the plane` : 'clear'}
            {hidden > 0 && ` · ${hidden} hidden`}
          </span>
          {budget.fidelity !== 'full' && (
            // §26 with §22's honesty and §27's rule about colour: a plane that
            // degrades silently teaches an operator that the screen is just
            // slow. The level is a word, the cause is in the title, and both
            // are text rather than a dimmed animation nobody can name.
            <span
              title={budget.reason}
              style={{ ...label, color: C.bad }}
            >
              {`${budget.fidelity} fidelity`}
            </span>
          )}
          <button
            type="button"
            onClick={onExit}
            style={{ ...control, minHeight: 34, padding: '0 11px', fontSize: 11 }}
          >
            <Minimize2 size={12} aria-hidden /> Exit <kbd style={{ ...label, marginLeft: 2 }}>esc</kbd>
          </button>
        </div>
      </header>

      {/* The plane. Core centred when empty; core and surfaces side by side
          once anything has been summoned. */}
      <div
        ref={planeRef}
        // §18. The plane is where a pointer gesture is made; the individual
        // panels see it by bubbling, which is what lets `pointingAt` decide
        // which one was meant rather than trusting where the event landed.
        onPointerDown={onPlanePointerDown}
        onPointerMove={onPlanePointerMove}
        onPointerUp={onGesture}
        onPointerCancel={() => {
          // A gesture the browser took away is not a gesture. Leaving the
          // points behind would let the next press finish somebody else's.
          track.current = null;
        }}
        style={{
          position: 'relative',
          display: 'grid',
          gridTemplateColumns: hasSurfaces ? 'minmax(280px, 360px) 1fr' : '1fr',
          gap: 22,
          alignItems: 'center',
          padding: hasSurfaces ? '18px 20px' : '10px 20px',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'grid',
            justifyItems:
              anchor === 'left' ? 'start' : anchor === 'right' || anchor === 'bottom_right' ? 'end' : 'center',
            alignContent: anchor === 'top_left' ? 'start' : anchor === 'bottom_right' ? 'end' : 'center',
            gap: 14,
            minWidth: 0,
          }}
        >
          <PresenceCore
            presence={presence}
            // §26. The heaviest thing on this screen is the animated canvas, so
            // it is the first thing the frame budget takes away. Anything below
            // full fidelity stops it — the presence still draws, it stops
            // moving, which is what "pause or reduce animation under load"
            // asks for. `nextFidelity` has already folded the reduced-motion
            // preference in, so it is not re-applied here.
            reducedMotion={budget.fidelity !== 'full'}
            size={Math.round((hasSurfaces ? 220 : 300) * scale)}
            representation={representation}
            utterance={utterance}
            speechProgress={speechProgress}
            speaking={speaking}
            // §7: the head turns toward the panel being discussed. Measured
            // here, from the DOM, so an unlaid-out panel yields null and the
            // head faces forward rather than pointing at the origin.
            targetRect={(() => {
              const id = spokenAbout[0];
              if (!id || !planeRef.current) return null;
              const el = planeRef.current.querySelector(`[data-surface-id="${id}"]`);
              return el ? el.getBoundingClientRect() : null;
            })()}
          />
          {lastFew.length > 0 && (
            <ol
              aria-label="Recent conversation"
              style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: 4, maxWidth: '46ch' }}
            >
              {lastFew.map((line, i) => (
                <li key={`${line.at}-${i}`} style={{ fontSize: 12, color: C.dim, textAlign: 'center' }}>
                  <span style={{ color: line.who === 'ai' ? C.core : C.quiet, fontWeight: 700 }}>
                    {line.who === 'ai' ? '' : 'You: '}
                  </span>
                  {line.text}
                  {line.interrupted && <em style={{ color: C.quiet }}> — interrupted</em>}
                </li>
              ))}
            </ol>
          )}
        </div>

        {hasSurfaces && (
          <div
            aria-label="Workspace"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(12, 1fr)',
              gap: 12,
              alignContent: 'start',
              maxHeight: '100%',
              overflowY: 'auto',
              paddingRight: 4,
            }}
          >
            {stacked.length > 0 && (
              // §10: "background information collapses into stacks or
              // summaries." Still listed, still closable — a collapsed surface
              // the operator cannot see the name of is one they cannot get back.
              //
              // §27: one tab stop, arrows inside. A war-room workspace collapses
              // most of its surfaces here, so a tab stop each would put a dozen
              // presses between the operator and the composer below.
              <div
                role="toolbar"
                aria-orientation="horizontal"
                aria-label="Collapsed background surfaces"
                onKeyDown={stackKeys.onKeyDown}
                style={{
                  gridColumn: 'span 12',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                  alignItems: 'center',
                  padding: '8px 10px',
                  borderRadius: 9,
                  border: `1px dashed ${C.edge}`,
                  background: 'rgba(12,20,35,.55)',
                }}
              >
                <span style={label}>background · {stacked.length}</span>
                {stacked.map(({ surface }) => (
                  <button
                    key={surface.id}
                    ref={stackKeys.register(surface.id)}
                    tabIndex={stackKeys.tabIndexFor(surface.id)}
                    type="button"
                    onClick={() => onPinSurface(surface.id)}
                    title="Pin to bring it back out of the stack"
                    style={{
                      minHeight: 28,
                      padding: '0 9px',
                      borderRadius: 7,
                      border: `1px solid ${C.edge}`,
                      background: 'rgba(10,17,30,.85)',
                      color: C.dim,
                      fontSize: 11.5,
                      cursor: 'pointer',
                    }}
                  >
                    {surface.meaning}
                  </button>
                ))}
              </div>
            )}
            {shown.map(({ surface, span }) => (
              <SurfaceView
                key={surface.id}
                surface={surface}
                span={span}
                focused={shownFocus === surface.id}
                spokenAbout={spokenAbout.includes(surface.id)}
                onClose={() => onCloseSurface(surface.id)}
                onPin={() => onPinSurface(surface.id)}
                onDrill={onDrillSurface}
              />
            ))}
          </div>
        )}
      </div>

      {/* Ask. One line, always here, because the way to make something appear
          should never be hidden behind a menu. */}
      <form
        onSubmit={submit}
        style={{
          position: 'relative',
          display: 'flex',
          gap: 9,
          flexWrap: 'wrap',
          alignItems: 'center',
          padding: '14px 18px 18px',
          borderTop: `1px solid ${C.edge}`,
          background: 'linear-gradient(0deg, rgba(16,26,44,.62), transparent)',
        }}
      >
        <label htmlFor="hub-ask" style={{ ...label, flex: '0 0 auto' }}>
          Ask
        </label>
        <input
          id="hub-ask"
          ref={inputRef}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Show me everything affecting gold · focus on risk · simplify this"
          style={{
            flex: '1 1 320px',
            minHeight: 42,
            padding: '0 13px',
            borderRadius: 9,
            border: `1px solid ${C.edge}`,
            background: 'rgba(10,17,30,.9)',
            color: C.text,
            fontSize: 13,
            boxSizing: 'border-box',
          }}
        />
        <button type="submit" style={control} disabled={!typed.trim()}>
          <Send size={13} aria-hidden /> Send
        </button>
        <button
          type="button"
          onClick={onTalk}
          disabled={!sttSupported}
          style={{ ...control, borderColor: listening ? C.bad : C.edge2, opacity: sttSupported ? 1 : 0.5 }}
        >
          <Mic size={13} aria-hidden /> {listening ? 'Stop listening' : 'Talk'}
        </button>
        <button type="button" onClick={onStop} style={control}>
          <Square size={12} aria-hidden /> Stop
        </button>
        <button type="button" onClick={onToggleMute} aria-pressed={muted} style={control}>
          {muted ? <VolumeX size={13} aria-hidden /> : <Volume2 size={13} aria-hidden />}
          {muted ? 'Muted' : 'Aloud'}
        </button>
      </form>
    </div>
  );
};

/** Re-exported so `SurfaceView` and the stage share one close affordance. */
export const CloseIcon = X;
