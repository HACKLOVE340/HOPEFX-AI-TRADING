/**
 * hub/useRovingFocus.ts — `RovingFocus` bound to the DOM.
 *
 * `a11yFocus.ts` stays pure, like `layout.ts` and `spatial.ts`: it decides
 * which item holds the group's tab stop and what a key does. That decision has
 * to become a real `element.focus()` somewhere, and this is the only place it
 * does — the same split as `useViewportWidth` and `usePrefersReducedMotion`.
 *
 * ## Moving the tab stop is not moving focus
 *
 * Setting `tabIndex={0}` on the next item and stopping there leaves the caret
 * where it was: the operator presses ArrowRight, the markup changes, nothing
 * visible happens, and the next Tab jumps somewhere unrelated. So the hook
 * holds a node per id and focuses it. A roving group that updates its tab
 * indices and never calls `focus()` is `hopefx-dead-controls` with an ARIA
 * pattern on top.
 *
 * ## Keys this group does not own still bubble
 *
 * `onKey` returns null for anything but the arrows, Home and End, and this
 * hook calls `preventDefault` only when it returned an id. Escape has to reach
 * the surface above — `PresenceStage` closes on it, and a full-screen surface
 * with no way out is a trap.
 */

import { useCallback, useRef, useState } from 'react';
import type React from 'react';

import { RovingFocus, type RovingOptions } from './a11yFocus';

export interface RovingBinding {
  /** The item holding the group's single tab stop. */
  activeId: string;
  /** `0` for that item, `-1` for the rest. Throws on an id not in the group. */
  tabIndexFor(id: string): 0 | -1;
  /** Attach to the group container, not to each item. */
  onKeyDown(event: React.KeyboardEvent): void;
  /** `ref={register(id)}` on each item, so the hook can focus it. */
  register(id: string): (element: HTMLElement | null) => void;
}

export function useRovingFocus(ids: readonly string[], options: RovingOptions = {}): RovingBinding {
  const roving = useRef<RovingFocus | null>(null);
  if (roving.current === null) roving.current = new RovingFocus(ids, undefined, options);

  // Re-sync during render rather than in an effect. An effect runs after the
  // children have already asked for their tab indices, so a list that just
  // changed would be queried against the previous one — and `tabIndexFor`
  // throws on an unknown id, which would turn a normal update into a crash.
  const signature = ids.join(' ');
  const lastSignature = useRef(signature);
  if (lastSignature.current !== signature) {
    roving.current.setItems(ids);
    lastSignature.current = signature;
  }

  const nodes = useRef(new Map<string, HTMLElement | null>());
  const [, forceRender] = useState(0);

  const onKeyDown = useCallback((event: React.KeyboardEvent) => {
    const next = roving.current!.onKey(event.key);
    if (next === null) return;
    event.preventDefault();
    nodes.current.get(next)?.focus();
    forceRender((n) => n + 1);
  }, []);

  const register = useCallback(
    (id: string) => (element: HTMLElement | null) => {
      if (element === null) nodes.current.delete(id);
      else nodes.current.set(id, element);
    },
    [],
  );

  return {
    activeId: roving.current.active,
    tabIndexFor: (id: string) => roving.current!.tabIndexFor(id),
    onKeyDown,
    register,
  };
}
