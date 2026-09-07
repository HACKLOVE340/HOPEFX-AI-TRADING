/**
 * hub/useContrastMode.ts — the consumer the high-contrast palette never had.
 *
 * `a11yContrast.ts` shipped in Phase G with a measured AAA palette and a
 * `prefersHighContrast()` reader, and the registry row said so in words:
 * "NOTHING RENDERS IT YET." Staging it was right — a palette nobody paints
 * with is F176 with a passing contrast test — but a refusal recorded and never
 * acted on is a slower version of the same omission.
 *
 * This is the hook half, split from the pure half exactly as
 * `usePrefersReducedMotion` is split from `motionFor`: the media query is read
 * here, the palette is chosen in `a11yContrast.ts`, and a component receives a
 * mode.
 *
 * ## It defaults the other way from reduced motion, on purpose
 *
 * `usePrefersReducedMotion` defaults to "reduce" when it cannot read the query,
 * because for some people that setting is medical and a wrong guess causes
 * symptoms. Contrast defaults to `standard`, because the standard palette
 * already clears AA on every surface the hub draws on — nobody is harmed by not
 * being upgraded, and forcing AAA on every browser that cannot answer the query
 * would change the product for everyone on the strength of a missing feature.
 *
 * The asymmetry is deliberate and is the same one the consent gate makes:
 * where being wrong harms somebody, unreadable means refuse; where it does not,
 * unreadable means carry on.
 */

import { useEffect, useState } from 'react';

import type { ContrastMode } from './a11yContrast';

/** `forced-colors` first: a forced-colours mode is a stronger statement than a preference. */
const QUERIES = ['(forced-colors: active)', '(prefers-contrast: more)'] as const;

/**
 * Read the preference now.
 *
 * Exported so the decision is testable without mounting a component, and so a
 * non-React caller reads it the same way rather than growing a second copy.
 */
export function readContrastMode(): ContrastMode {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'standard';
    for (const query of QUERIES) {
      if (window.matchMedia(query).matches) return 'high';
    }
    return 'standard';
  } catch {
    return 'standard';
  }
}

export function useContrastMode(): ContrastMode {
  const [mode, setMode] = useState<ContrastMode>(readContrastMode);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const lists: MediaQueryList[] = [];
    const onChange = () => setMode(readContrastMode());
    for (const query of QUERIES) {
      try {
        const list = window.matchMedia(query);
        // Safari below 14 has only the deprecated form, and this runs on iPads.
        if (typeof list.addEventListener === 'function') list.addEventListener('change', onChange);
        else if (typeof list.addListener === 'function') list.addListener(onChange);
        lists.push(list);
      } catch {
        /* one unreadable query does not stop the other */
      }
    }
    onChange();
    return () => {
      for (const list of lists) {
        if (typeof list.removeEventListener === 'function') list.removeEventListener('change', onChange);
        else if (typeof list.removeListener === 'function') list.removeListener(onChange);
      }
    };
  }, []);

  return mode;
}
