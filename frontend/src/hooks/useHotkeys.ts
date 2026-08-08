/**
 * hooks/useHotkeys.ts
 *
 * Keyboard shortcuts for the trading surface (audit S10-04).
 *
 * S10-04 recorded that there is "no keyboard-shortcut affordance for order entry
 * or for the kill switch". The kill switch is the sharper half: its only
 * triggers live in Settings and the superadmin panel, so a trader watching a
 * position go against them has to navigate away from the trading screen to halt
 * trading.
 *
 * A shortcut layer on a capital-committing UI has three duties, and all three
 * are the reason this is a hook rather than a bare `addEventListener`:
 *
 * 1. **Never fire while the user is typing.** A bare `b` for "buy" that also
 *    triggers inside the quantity field would arm a direction every time
 *    someone types a number containing that letter. Events originating in an
 *    input, textarea, select or contenteditable are ignored outright.
 *
 * 2. **Never fire while a dialog is open.** A confirmation is a question; the
 *    answer must come from the dialog, not from a shortcut that reaches past
 *    it and does something else.
 *
 * 3. **Never bypass a confirmation.** A shortcut is an accelerator for reaching
 *    a control, not a way around the guard on it. The kill-switch binding opens
 *    the same confirmation the button does.
 *
 * Bindings are written as `'b'`, `'shift+k'`, `'mod+enter'` — `mod` is ⌘ on
 * macOS and Ctrl elsewhere. Destructive bindings take a modifier deliberately:
 * a bare letter is one stray keystroke away from being pressed by accident, and
 * "halt all trading" is not something to leave one keystroke away.
 */

import { useEffect, useRef } from 'react';

export type HotkeyMap = Record<string, (e: KeyboardEvent) => void>;

/** True when the keystroke came from somewhere the user is typing. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  return el.isContentEditable === true;
}

/** Canonical form of a keyboard event: 'shift+k', 'mod+enter', 'b'. */
export function eventToBinding(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.metaKey || e.ctrlKey) parts.push('mod');
  if (e.altKey) parts.push('alt');
  if (e.shiftKey) parts.push('shift');
  parts.push((e.key || '').toLowerCase());
  return parts.join('+');
}

export function useHotkeys(map: HotkeyMap, enabled = true): void {
  // Held in a ref so a caller can pass an object literal without re-binding the
  // listener on every render — the F1-01 lesson about unstable identities.
  const mapRef = useRef(map);
  mapRef.current = map;

  useEffect(() => {
    if (!enabled) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      // A dialog owns the keyboard while it is open. `[role="dialog"]` covers
      // ConfirmDialog and anything else following the same convention.
      if (document.querySelector('[role="dialog"]')) return;

      const handler = mapRef.current[eventToBinding(e)];
      if (!handler) return;
      e.preventDefault();
      handler(e);
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
}

export default useHotkeys;
