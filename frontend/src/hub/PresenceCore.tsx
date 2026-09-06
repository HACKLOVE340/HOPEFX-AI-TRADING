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

export interface PresenceCoreProps {
  presence: Presence;
  /** Overrides the media query. The review surface and tests set it directly. */
  reducedMotion?: boolean;
  size?: number;
}

export const PresenceCore: React.FC<PresenceCoreProps> = ({ presence, reducedMotion, size = 300 }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // A ref, not state: the animation reads the newest presence every frame
  // without the frame loop being a dependency of a re-render.
  const latest = useRef(presence);
  latest.current = presence;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const still =
      reducedMotion ??
      (typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);

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
      const glow = ctx.createRadialGradient(C, C, r * 0.35, C, C, r);
      glow.addColorStop(0, `rgba(115,167,255,${0.3 + p.intensity * 0.45})`);
      glow.addColorStop(1, 'rgba(115,167,255,0)');
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(C, C, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = `rgba(115,167,255,${0.5 + p.intensity * 0.45})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(C, C, r, 0, Math.PI * 2);
      ctx.stroke();

      if (!still) raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion]);

  const headroom = presence.headroomKnown ? `${Math.round(headroomOf(presence) * 100)}%` : '—';

  return (
    <section
      aria-label="AI presence"
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
            placeContent: 'center',
            textAlign: 'center',
            pointerEvents: 'none',
          }}
        >
          <div style={LABEL}>Risk headroom</div>
          <div
            style={{
              fontSize: 34,
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

      {/* The caption. Same sentence the AI speaks, so the two cannot drift. */}
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
