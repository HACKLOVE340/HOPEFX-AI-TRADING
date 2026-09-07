/**
 * hub/useDisplays.ts — §10's display snapshot, bound to the browser.
 *
 * `displays.ts` stays pure so every placement rule is testable without a
 * browser and without two monitors; this is the hook, the same split
 * `useViewportWidth` and `layout.ts` already hold.
 *
 * ## It probes on mount and never prompts
 *
 * The first read passes `probe: true`, which reports what can be known without
 * asking. `request()` is the only thing that calls `getScreenDetails()` for
 * real, and it exists to be wired to a button an operator presses — because a
 * permission prompt raised by a component mounting is one people learn to
 * dismiss, and then the prompt they meant to accept is dismissed too.
 *
 * ## It listens for the layout changing
 *
 * A monitor unplugged mid-session is a plane spread across a screen that is no
 * longer there. `screenschange` fires on the details object once permission is
 * held, and `resize` is the fallback signal on browsers that have neither.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { readDisplays, type DisplaySnapshot } from './displays';

const UNREAD: DisplaySnapshot = {
  state: 'unpermitted',
  screens: [],
  count: null,
  reason: 'the screen layout has not been read yet',
};

export interface Displays {
  snapshot: DisplaySnapshot;
  /** Ask the operator. The ONLY path that can raise a permission prompt. */
  request: () => Promise<void>;
}

export function useDisplays(): Displays {
  const [snapshot, setSnapshot] = useState<DisplaySnapshot>(UNREAD);
  // Set once the operator has granted, so a later re-read does not prompt
  // again and does not silently fall back to the probe answer either.
  const granted = useRef(false);

  const refresh = useCallback(async (probe: boolean) => {
    const next = await readDisplays({ probe });
    setSnapshot(next);
    if (next.state === 'measured') granted.current = true;
  }, []);

  const request = useCallback(async () => {
    await refresh(false);
  }, [refresh]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const next = await readDisplays({ probe: true });
      if (alive) setSnapshot(next);
    })();

    // Re-read only once permission is already held: a layout change must not
    // become a second prompt.
    const onChange = () => {
      if (granted.current) void refresh(false);
    };
    if (typeof window !== 'undefined') window.addEventListener('resize', onChange);
    return () => {
      alive = false;
      if (typeof window !== 'undefined') window.removeEventListener('resize', onChange);
    };
  }, [refresh]);

  return { snapshot, request };
}
