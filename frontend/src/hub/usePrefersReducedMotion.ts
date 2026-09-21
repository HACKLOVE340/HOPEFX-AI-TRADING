/**
 * hub/usePrefersReducedMotion.ts — the other input the layout engine cannot
 * compute for itself.
 *
 * Like `useViewportWidth`, this exists so `hub/spatial.ts` stays a pure
 * function: the media query is read here and handed in as a boolean.
 *
 * Defaults to **true** — no motion — when the query cannot be read. Every other
 * default in this codebase leans towards showing more; this one leans towards
 * moving less, because for some people the setting is medical rather than
 * aesthetic and a wrong guess in that direction causes symptoms rather than
 * disappointment.
 */

import { useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

function read(): boolean {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
    return window.matchMedia(QUERY).matches;
  } catch {
    return true;
  }
}

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(read);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    let list: MediaQueryList;
    try {
      list = window.matchMedia(QUERY);
    } catch {
      return;
    }
    const onChange = () => setReduced(list.matches);
    // Safari below 14 has only the deprecated form, and this runs on iPads.
    if (typeof list.addEventListener === 'function') list.addEventListener('change', onChange);
    else if (typeof list.addListener === 'function') list.addListener(onChange);
    onChange();
    return () => {
      if (typeof list.removeEventListener === 'function') list.removeEventListener('change', onChange);
      else if (typeof list.removeListener === 'function') list.removeListener(onChange);
    };
  }, []);

  return reduced;
}
