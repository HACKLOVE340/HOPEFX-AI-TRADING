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
import type { Presence } from './presence';
import type { Surface } from './workspace';
import { place, type LayoutName } from './layout';
import { positionOf, type Layer, type Position } from './spatial';
import { SurfaceView } from './SurfaceView';
import { useViewportWidth } from './useViewportWidth';

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
  onCommand: (phrase: string) => void;
  onTalk: () => void;
  onStop: () => void;
  onToggleMute: () => void;
  onCloseSurface: (id: string) => void;
  onPinSurface: (id: string) => void;
  onExit: () => void;
}

export const PresenceStage: React.FC<PresenceStageProps> = ({
  presence, surfaces, focusedId, listening, muted, sttSupported, transcript, layout, spokenAbout = [],
  trail = [], onBreadcrumb, onPositions, modeName, accent,
  utterance = '', speechProgress = null, speaking = false,
  onCommand, onTalk, onStop, onToggleMute, onCloseSurface, onPinSurface, onExit,
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
  const placements = useMemo(
    () => place(surfaces, { layout, focusedId, viewport: { width }, collapseBackground: true }),
    [surfaces, layout, focusedId, width],
  );
  const visible = placements.filter((p) => p.visible);
  const shown = visible.filter((p) => !p.collapsed);
  const stacked = visible.filter((p) => p.collapsed);
  const hidden = placements.length - visible.length;
  const hasSurfaces = visible.length > 0;

  /**
   * Measure where the panels ended up.
   *
   * After paint, and again whenever the plane changes shape. A rect read before
   * layout is zero, and `positionOf` returns null for a zero rect rather than
   * calling it "top left" — so a too-early measurement produces no claim rather
   * than a wrong one.
   */
  useEffect(() => {
    if (!onPositions) return;
    const measure = () => {
      const root = planeRef.current;
      if (!root) return;
      const viewport = root.getBoundingClientRect();
      const found: Record<string, Position> = {};
      for (const el of Array.from(root.querySelectorAll('[data-surface-id]'))) {
        const id = el.getAttribute('data-surface-id');
        if (!id) continue;
        const position = positionOf(el.getBoundingClientRect(), viewport);
        if (position) found[id] = position;
      }
      onPositions(found);
    };
    const frame = requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', measure);
    };
  }, [onPositions, surfaces, layout, width]);

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
        <div style={{ display: 'grid', justifyItems: 'center', gap: 14, minWidth: 0 }}>
          <PresenceCore
            presence={presence}
            size={hasSurfaces ? 220 : 300}
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
              <div
                aria-label="Collapsed background surfaces"
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
                focused={focusedId === surface.id}
                spokenAbout={spokenAbout.includes(surface.id)}
                onClose={() => onCloseSurface(surface.id)}
                onPin={() => onPinSurface(surface.id)}
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
