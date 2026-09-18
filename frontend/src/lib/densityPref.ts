/**
 * densityPref — how tight the person wants the interface.
 *
 * The three tiers already existed and were chosen per route by a table in
 * `PageSurface`. This hands the choice to the person, defaulting to `ultra`.
 *
 * ## It can tighten anything and loosen almost anything
 *
 * The route table stays as the default. A preference overrides it — including
 * upward, so someone who wants the sign-in page dense gets it — with one floor
 * it cannot cross: a data surface never goes below `ultra`.
 *
 * That floor is not the product being precious about its own taste. Density on
 * `/portfolio` decides how many rows of open risk are on screen at once, and
 * "three fewer positions visible" is not a preference — it is less of the
 * account in view during the minute it matters. It is the same argument the
 * platform already makes for keeping the presence off the order ticket and for
 * §19's critical alert floor surviving a dismissal.
 *
 * ## Shape
 *
 * Mirrors `voicePrefs.ts`: localStorage, a custom event for this tab and the
 * native `storage` event for the others, and every access wrapped — Safari's
 * private mode throws on `localStorage` itself, and a page that fails to render
 * because someone has a preference is worse than a page at the default.
 */
import { useCallback, useEffect, useState } from 'react';

import type { Density } from '../components/system/PageSurface';

const KEY = 'hopefx.density';
const EVENT = 'hopefx:density';

/**
 * Validated on the way out, not just on the way in.
 *
 * Anyone can type into localStorage, and the value is stamped onto the document
 * as `data-density`. An unvalidated read puts an attacker-chosen string into an
 * attribute selector's territory; a validated one reads as "no choice".
 */
const VALID: readonly Density[] = ['comfortable', 'promax', 'ultra'];

function isDensity(value: unknown): value is Density {
  return typeof value === 'string' && (VALID as readonly string[]).includes(value);
}

/** The person's choice, or null when they have not made one. */
export function getDensityPref(): Density | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(KEY);
    return isDensity(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Set it, or pass null to go back to the per-route default. */
export function setDensityPref(density: Density | null): void {
  try {
    if (density === null) localStorage.removeItem(KEY);
    else if (isDensity(density)) localStorage.setItem(KEY, density);
  } catch {
    /* private mode / no storage — the choice does not persist, the app runs */
  }
  try {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: density }));
  } catch {
    /* no window */
  }
}

/** React hook: `[density, setDensity]`, kept in sync across components and tabs. */
export function useDensityPref(): [Density | null, (density: Density | null) => void] {
  const [density, setLocal] = useState<Density | null>(getDensityPref);

  useEffect(() => {
    const onCustom = (e: Event) => {
      const next = (e as CustomEvent).detail;
      setLocal(next === null || isDensity(next) ? (next as Density | null) : null);
    };
    // The native event fires in the OTHER tabs; the custom one fires in this.
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY || e.key === null) setLocal(getDensityPref());
    };
    window.addEventListener(EVENT, onCustom);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(EVENT, onCustom);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const set = useCallback((next: Density | null) => {
    setDensityPref(next);
    setLocal(next);
  }, []);

  return [density, set];
}
