/**
 * hub/PresenceAnywhere.tsx — the presence, on every screen in the app.
 *
 * Owner request, 2026-09-07: the AI should be available on any page, able to
 * diagnose the page around it and act on it. Approved for production after
 * `presence.overlay` sat in the registry as `planned` pending that approval.
 *
 * ## It introduces no new visual language
 *
 * `PresenceCore` already draws the presence — canvas `aria-hidden`, everything
 * it expresses also written beside it. `presenceDock` already decides where a
 * floating element may sit. `pageContext` and `pageCapabilities` already decide
 * what it knows and may do. This composes them; it invents nothing, which is
 * why a whole-app overlay could be added without a redesign.
 *
 * ## The three rules it exists to keep
 *
 * **It never sits on what the operator is using.** `avoid` is passed to
 * `dockFor`, which returns a corner that collides with nothing — and when every
 * corner collides, says so instead of covering a form. One of those forms is
 * the order ticket.
 *
 * **It is never a keyboard trap.** No `aria-modal`, no focus capture. A
 * floating panel that swallows Tab makes every page behind it unusable for
 * anyone navigating by keyboard, on a platform where the page behind it places
 * trades.
 *
 * **Dismissal persists.** A presence that returns on the next route change was
 * delayed, not dismissed. It is stored, and storage that throws — Safari's
 * private mode does — is an unread dismissal rather than a page that fails to
 * render.
 *
 * ## The one thing dismissal does not silence
 *
 * An `alerting` presence still appears. Dismissing an assistant is not consent
 * to be uninformed about a kill switch, and §19's critical floor already holds
 * this rule on the notification path.
 *
 * ## Not on the AI Core page
 *
 * That plane already is the presence. Two of them on one screen is not twice
 * the presence; it is a bug that looks like a design decision.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, X } from 'lucide-react';

import { PresenceCore } from './PresenceCore';
import type { Presence } from './presence';
import { describePage, type Landmark, type NavLike } from './pageContext';
import { pageCapabilities, type SurfaceEntry } from './pageCapabilities';
import { DISMISSED, dockFor } from './presenceDock';
import { FOCUS_RING, HIT_AREA } from './a11yFocus';
import { liveRegions } from './a11yLiveRegion';
import type { Rect } from './spatial';

/** One key, so a stuck dismissal can be found and cleared. */
export const DISMISS_KEY = 'hopefx.presence.dismissed';

/**
 * The ring and the hit area come from `a11yFocus.ts`, not from here.
 *
 * They were declared in this file first, after both defects were found in it:
 * no focus ring at all, and a 22px dismiss control. Two files holding their own
 * copy is how the next component gets a third, so the definition moved to one
 * place and `hub_a11y_guard.test.ts` fails a second declaration of either.
 */

/** The plane that is already a presence. */
const OWNS_ITS_OWN_PRESENCE = '/ai-core';

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1';
  } catch {
    // Site data blocked. An unread dismissal, never a thrown render.
    return false;
  }
}

function writeDismissed(value: boolean): void {
  try {
    if (value) localStorage.setItem(DISMISS_KEY, '1');
    else localStorage.removeItem(DISMISS_KEY);
  } catch {
    /* nothing to do: the preference simply does not survive the session */
  }
}

export interface PresenceAnywhereProps {
  pathname: string;
  nav: readonly NavLike[];
  surface: readonly SurfaceEntry[];
  presence: Presence;
  viewport: Rect;
  /** What the operator is interacting with, so the dock stays off it. */
  avoid?: readonly Rect[];
  landmarks?: readonly Landmark[];
  reducedMotion?: boolean;
  /** Set when the capability surface could not be loaded. "Nothing is exposed
   *  to me" and "I could not find out" are different sentences, and only one of
   *  them is true when the request failed. */
  surfaceReason?: string;
}

/* The panel's own geometry, kept here because this is the component that
   draws it. 360 was already the open width; the closed one was never declared
   and defaulted to the dock's orb, which is how a status sentence ended up
   wrapped into a 72px column. The heights are what the two states occupy, and
   they matter because the dock uses them to decide which corner is free. */
const OPEN_WIDTH = 360;
const CLOSED_WIDTH = 268;

/* Heights until the panel has been laid out once. They are a starting guess and
   nothing more: the panel's height depends on how long the status sentence for
   this page is, so a constant is wrong for most pages. Declaring 124 put the
   panel's anchor 124px off the bottom while 276px of it rendered, and 152px
   hung below the fold. The measured height replaces these on the first frame. */
const OPEN_HEIGHT_GUESS = 420;
const CLOSED_HEIGHT_GUESS = 200;

export function PresenceAnywhere(props: PresenceAnywhereProps): React.ReactElement | null {
  const { pathname, nav, surface, presence, viewport } = props;

  const [dismissed, setDismissed] = useState<boolean>(readDismissed);
  const [open, setOpen] = useState(false);

  const alerting = presence.state === 'alerting';

  const page = useMemo(
    () => describePage({ pathname, nav, landmarks: props.landmarks }),
    [pathname, nav, props.landmarks],
  );
  const caps = useMemo(
    () => pageCapabilities({ area: page.area, surface }),
    [page.area, surface],
  );
  // The size the panel will actually be, handed to the dock so it reserves the
  // box it draws rather than an orb it has not been since this component was
  // written. `dock.rect.width` is what the panel is laid out at, so a dock that
  // guesses small does not shrink the panel — it wraps it into a column.
  // Width is declared; height is measured. The panel's width is what the dock
  // hands back, so declaring it is the only way not to chase our own tail. Its
  // height then follows from how much text this page's status runs to, which
  // nothing here can know in advance — so read it off the element. Width does
  // not depend on height, so this settles in one frame rather than oscillating.
  const panelRef = useRef<HTMLElement | null>(null);
  const [measuredHeight, setMeasuredHeight] = useState<number | null>(null);
  useEffect(() => {
    const node = panelRef.current;
    if (node === null) return;
    const observer = new ResizeObserver(() => {
      const height = node.getBoundingClientRect().height;
      if (height > 0) setMeasuredHeight(height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  // A state change that alters the content resets the measurement, so the
  // previous state's height is never used to place the new one.
  useEffect(() => setMeasuredHeight(null), [open]);

  const panelSize = useMemo(
    () => ({
      width: Math.min(open ? OPEN_WIDTH : CLOSED_WIDTH, viewport.width - 32),
      height: measuredHeight ?? (open ? OPEN_HEIGHT_GUESS : CLOSED_HEIGHT_GUESS),
    }),
    [open, viewport.width, measuredHeight],
  );

  const dock = useMemo(
    () =>
      dockFor({
        viewport,
        size: panelSize,
        avoid: props.avoid,
        // An alert overrides a dismissal, so the dock must not report hidden.
        state: dismissed && !alerting ? DISMISSED : 'active',
        reducedMotion: props.reducedMotion,
      }),
    [viewport, panelSize, props.avoid, dismissed, alerting, props.reducedMotion],
  );

  // The overlay owns the ASSERTIVE region only. Its `role="alert"` is what
  // §19's critical floor needs — a kill switch interrupts — and it is a
  // different level from the polite one `PresenceCore` holds, so the two do
  // not interleave. An earlier version of this component rendered a second
  // POLITE region beside PresenceCore's; the claim is what refuses that now.
  useEffect(() => {
    liveRegions.claim('assertive', 'PresenceAnywhere');
    return () => {
      liveRegions.release('assertive', 'PresenceAnywhere');
    };
  }, []);

  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      // Escape closes the panel and does NOT dismiss: an accidental Escape
      // should not remove the assistant until the operator asks for it back.
      if (event.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, close]);

  if (pathname.startsWith(OWNS_ITS_OWN_PRESENCE)) return null;

  if (dismissed && !alerting) {
    return (
      <button
        type="button"
        onClick={() => {
          setDismissed(false);
          writeDismissed(false);
        }}
        className={`fixed bottom-4 right-4 z-40 rounded-full border border-white/15 bg-slate-900/90 px-3 text-xs text-slate-300 transition-colors hover:text-white cursor-pointer ${HIT_AREA} ${FOCUS_RING}`}
      >
        Show assistant
      </button>
    );
  }

  if (!dock.visible) return null;

  const problems = page.problems.length;
  const status = page.known
    ? `${page.label}. ${
        !page.inspected
          ? 'This page has not been inspected.'
          : problems > 0
            ? `${problems} ${problems === 1 ? 'problem' : 'problems'} on this page.`
            : 'Nothing wrong on this page.'
      }`
    : `I don't recognise this page (${page.path}).`;

  return (
    <section
      ref={panelRef}
      role="complementary"
      aria-label="HOPEFX AI assistant"
      data-corner={dock.corner}
      data-mode={dock.mode}
      style={{
        position: 'fixed',
        left: dock.rect.x,
        top: dock.rect.y,
        width: dock.rect.width,
        zIndex: 40,
        transition: dock.transition,
      }}
      className="rounded-2xl border border-white/10 bg-slate-950/90 p-3 text-slate-200 shadow-xl backdrop-blur"
    >
      <div className="flex items-start gap-2">
        <PresenceCore presence={presence} size={open ? 72 : 56} />
        <div className="min-w-0 flex-1">
          {/* Assertive only for an alert. Everything else is polite, because a
              screen reader interrupted by "standing by" is a screen reader
              nobody leaves on. */}
          {/* PresenceCore already owns the polite live region and announces the
              presence's own reason. A second polite region here would announce
              on every navigation AND compete with it — a screen reader saying
              two things at once is one nobody leaves on. So the page line is
              plain text; the route change is already announced by the page's
              own heading.

              An ALERT is the exception and is assertive: §19's critical floor
              is that a kill switch interrupts. */}
          {alerting ? (
            <p role="alert" className="text-sm font-medium text-rose-200">
              {presence.reason}
            </p>
          ) : (
            <p className="text-xs text-slate-300">{status}</p>
          )}
        </div>
        <button
          type="button"
          aria-label="Dismiss assistant"
          onClick={() => {
            setDismissed(true);
            writeDismissed(true);
            setOpen(false);
          }}
          className={`rounded text-slate-400 transition-colors hover:text-white cursor-pointer ${HIT_AREA} ${FOCUS_RING}`}
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>

      {!open && (
        <button
          type="button"
          aria-label="Open assistant"
          onClick={() => setOpen(true)}
          className={`mt-2 flex w-full items-center justify-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-slate-300 transition-colors hover:text-white cursor-pointer ${HIT_AREA} ${FOCUS_RING}`}
        >
          <MessageSquare size={13} aria-hidden="true" /> Ask about this page
        </button>
      )}

      {open && (
        <div className="mt-3 space-y-3 text-xs">
          <div>
            <h3 className="mb-1 font-medium text-slate-400">What I can read here</h3>
            {props.surfaceReason ? (
              <p className="text-amber-300/80">{props.surfaceReason}</p>
            ) : caps.readable.length === 0 ? (
              <p className="text-slate-400">Nothing on this page is exposed to me.</p>
            ) : (
              <ul className="space-y-0.5">
                {caps.readable.map((entry) => (
                  <li key={entry.path} className="text-slate-300">
                    {entry.summary || entry.path}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            {/* A separate heading, deliberately. One merged list would read as
                "the AI can do all of this", which is the misunderstanding
                pageCapabilities exists to prevent. */}
            <h3 className="mb-1 font-medium text-slate-400">What I can do here</h3>
            {caps.requestable.length === 0 ? (
              <p className="text-slate-400">
                Nothing it can do here — this page is read only for me.
                {caps.unavailable.length > 0
                  ? ` ${caps.unavailable.length} action${caps.unavailable.length === 1 ? '' : 's'} exist and have no registered tool.`
                  : ''}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {caps.requestable.map((entry) => (
                  <li key={entry.path} className="text-slate-300">
                    {entry.summary || entry.path}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {dock.overlapping.length > 0 && (
            <p className="text-amber-300/80">
              I could not find a clear corner on this screen, so I may be covering something.
            </p>
          )}

          <button
            type="button"
            onClick={close}
            className={`rounded border border-white/10 px-2 text-slate-400 transition-colors hover:text-white cursor-pointer ${HIT_AREA} ${FOCUS_RING}`}
          >
            Close
          </button>
        </div>
      )}
    </section>
  );
}
