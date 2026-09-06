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
  onCommand: (phrase: string) => void;
  onTalk: () => void;
  onStop: () => void;
  onToggleMute: () => void;
  onCloseSurface: (id: string) => void;
  onPinSurface: (id: string) => void;
  onExit: () => void;
}

export const PresenceStage: React.FC<PresenceStageProps> = ({
  presence, surfaces, focusedId, listening, muted, sttSupported, transcript, layout,
  onCommand, onTalk, onStop, onToggleMute, onCloseSurface, onPinSurface, onExit,
}) => {
  const [typed, setTyped] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

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
    () => place(surfaces, { layout, focusedId, viewport: { width } }),
    [surfaces, layout, focusedId, width],
  );
  const shown = placements.filter((p) => p.visible);
  const hidden = placements.length - shown.length;
  const hasSurfaces = shown.length > 0;

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
        <span style={{ fontSize: 14, fontWeight: 800, letterSpacing: '.15em' }}>HOPEFX</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
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
          <PresenceCore presence={presence} size={hasSurfaces ? 220 : 300} />
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
            {shown.map(({ surface, span }) => (
              <SurfaceView
                key={surface.id}
                surface={surface}
                span={span}
                focused={focusedId === surface.id}
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
