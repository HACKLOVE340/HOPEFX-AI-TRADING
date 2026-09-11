/**
 * AISupportWidget — floating AI support chat, available on every authenticated
 * page. A launcher in the bottom-right corner opens a compact support assistant.
 *
 * Uses the shared <AIChat> core with a dedicated "support" session so its
 * history stays separate from the full-page assistant. Backed by POST /api/chat
 * (Claude/OpenAI, with offline fallback), so it always responds.
 *
 * ## It can be moved and parked
 *
 * The launcher sat at a fixed bottom-right corner and overlapped the presence
 * overlay on every authenticated page — two things in one place, neither
 * readable. It can now be dragged up and down the right edge, and pushed *into*
 * the edge, where it parks as a thin accent line. Clicking that line, or
 * dragging it back out, restores it.
 *
 * Position and parked state persist per browser, because a control someone
 * moved out of their way should stay out of their way on the next page.
 *
 * ## Every colour comes from a token
 *
 * This component carried fourteen hex literals inline, and not one of them was
 * the platform's: a blue-to-indigo gradient where `--accent` is cyan, and a
 * slate panel one shade off `--surface`. Inline styles also cannot
 * participate in a cascade — they cannot answer a `[data-theme]` attribute or a
 * media query — which is the direct reason the light/dark toggle changes
 * nothing. The styles now live in `index.css` and read the tokens, so this
 * component follows a theme the moment the tokens gain one.
 * See `scripts/frontend_colour_ratchet.py` for the measurement behind that.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import AIChat from './AIChat';

const SUPPORT_INTRO =
  '**HOPEFX Support.** I can help with logging in, subscriptions and billing, ' +
  'connecting a broker, KYC, deposits/withdrawals, and finding features. How can I help?';

const SUPPORT_SUGGESTIONS = [
  'How do I connect my broker account?',
  'How do I upgrade my plan?',
  'Where do I complete KYC verification?',
  'How do deposits and withdrawals work?',
];

/** Where the launcher sits when nobody has moved it, measured from the bottom. */
const DEFAULT_BOTTOM = 20;

/** Drop this close to the right edge and it parks. */
const DOCK_THRESHOLD_PX = 40;

/** Pointer movement under this is a click, not a drag. */
const DRAG_SLOP_PX = 5;

const STORAGE_KEY = 'hopefx.support.launcher';

interface Placement {
  /** Distance from the bottom of the viewport, in px. */
  bottom: number;
  /** Parked against the right edge as a sliver. */
  docked: boolean;
}

const DEFAULT_PLACEMENT: Placement = { bottom: DEFAULT_BOTTOM, docked: false };

/**
 * Keep the launcher on screen.
 *
 * A position saved on a tall window would otherwise place it past the bottom of
 * a short one, where it cannot be reached to move it back.
 */
export function clampBottom(bottom: number, viewportHeight: number): number {
  const highest = Math.max(DEFAULT_BOTTOM, viewportHeight - 96);
  return Math.min(Math.max(bottom, DEFAULT_BOTTOM), highest);
}

/** Would a pointer released here park the launcher? */
export function shouldDock(clientX: number, viewportWidth: number): boolean {
  return clientX >= viewportWidth - DOCK_THRESHOLD_PX;
}

export function readPlacement(): Placement {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PLACEMENT;
    const parsed = JSON.parse(raw) as Partial<Placement>;
    return {
      bottom: typeof parsed.bottom === 'number' && Number.isFinite(parsed.bottom) ? parsed.bottom : DEFAULT_BOTTOM,
      docked: parsed.docked === true,
    };
  } catch {
    // Private windows, cleared site data, a half-written value: the launcher
    // appearing in its default corner is a better outcome than not appearing.
    return DEFAULT_PLACEMENT;
  }
}

function writePlacement(placement: Placement): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(placement));
  } catch {
    // Nothing to do — the launcher still works, it just forgets where it was.
  }
}

const AISupportWidget: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement>(DEFAULT_PLACEMENT);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointerId: number; startX: number; startY: number; startBottom: number; moved: boolean } | null>(
    null,
  );

  // Read the saved placement after mount so server-rendered and first-paint
  // markup agree, and clamp it to the window it is actually opening in.
  useEffect(() => {
    const saved = readPlacement();
    setPlacement({ ...saved, bottom: clampBottom(saved.bottom, window.innerHeight) });
  }, []);

  const commit = useCallback((next: Placement) => {
    setPlacement(next);
    writePlacement(next);
  }, []);

  const onPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startBottom: placement.bottom,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    const state = drag.current;
    if (!state || state.pointerId !== event.pointerId) return;

    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    if (!state.moved && Math.hypot(dx, dy) < DRAG_SLOP_PX) return;

    state.moved = true;
    setDragging(true);
    // Dragging up increases the distance from the bottom.
    setPlacement((current) => ({ ...current, bottom: clampBottom(state.startBottom - dy, window.innerHeight) }));
  };

  const endDrag = (event: React.PointerEvent<HTMLButtonElement>, wasDocked: boolean) => {
    const state = drag.current;
    drag.current = null;
    setDragging(false);
    if (!state || state.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }

    if (!state.moved) {
      // A click, not a drag.
      if (wasDocked) {
        commit({ ...placement, docked: false });
      } else {
        setOpen((o) => !o);
      }
      return;
    }

    const bottom = clampBottom(state.startBottom - (event.clientY - state.startY), window.innerHeight);
    const docked = wasDocked
      ? // Parked already: dragging left by more than the slop pulls it back out.
        !(state.startX - event.clientX > DRAG_SLOP_PX)
      : shouldDock(event.clientX, window.innerWidth);

    if (docked && open) setOpen(false);
    commit({ bottom, docked });
  };

  if (placement.docked) {
    return (
      <button
        type="button"
        className="support-sliver"
        style={{ bottom: placement.bottom }}
        aria-label="Show support chat"
        title="Support — click or drag out"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => endDrag(event, true)}
        onPointerCancel={(event) => endDrag(event, true)}
      />
    );
  }

  const panelBottom = placement.bottom + 68;

  return (
    <>
      <button
        type="button"
        className="support-launcher"
        data-open={open}
        data-dragging={dragging}
        style={{ bottom: placement.bottom }}
        aria-label={open ? 'Close support chat' : 'Open support chat'}
        title="Support — drag to move, push to the edge to park"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => endDrag(event, false)}
        onPointerCancel={(event) => endDrag(event, false)}
      >
        <span aria-hidden="true">{open ? '✕' : '💬'}</span>
      </button>

      {open && (
        <div className="support-panel" style={{ bottom: panelBottom }} role="dialog" aria-label="AI Support">
          <div className="support-panel-head">
            <span aria-hidden="true" style={{ fontSize: 18 }}>
              🎧
            </span>
            <div style={{ flex: 1 }}>
              <div className="support-panel-title">AI Support</div>
              <div className="support-panel-sub">Typically replies instantly</div>
            </div>
            <button type="button" className="support-panel-close" onClick={() => setOpen(false)} aria-label="Close">
              ✕
            </button>
          </div>
          <div className="support-panel-body">
            <AIChat
              sessionId="support"
              intro={SUPPORT_INTRO}
              suggestions={SUPPORT_SUGGESTIONS}
              placeholder="Ask support…"
              compact
            />
          </div>
        </div>
      )}
    </>
  );
};

export default AISupportWidget;
