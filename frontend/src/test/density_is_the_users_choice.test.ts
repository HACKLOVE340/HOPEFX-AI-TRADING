/**
 * Owner, 2026-09-15: "I want a very very attractive density" — and, asked
 * whether density should be fixed or chosen: user-controlled, with ultra as the
 * default.
 *
 * The three tiers already existed and were picked per route by a table. This
 * hands the choice to the person and keeps one rule the person cannot override:
 * a data surface never loosens below `ultra`.
 *
 * That is not the product being precious about its own taste. Density on
 * /portfolio decides how many rows of open risk are on screen at once, and
 * "three fewer positions visible" is not a preference, it is less of the
 * account in view during the minute it matters. The same argument the platform
 * already makes for the order ticket's dock and for the critical alert floor.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import { densityFor } from '../components/system/PageSurface';
import { getDensityPref, setDensityPref } from '../lib/densityPref';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* storage blocked; the module copes */ }
});

describe('density preference', () => {
  it('defaults to ultra when the person has not chosen', () => {
    expect(getDensityPref()).toBeNull();
    expect(densityFor('/notifications', null)).toBe('ultra');
  });

  it('honours the choice on an ordinary page', () => {
    expect(densityFor('/notifications', 'comfortable')).toBe('comfortable');
    expect(densityFor('/notifications', 'promax')).toBe('promax');
    expect(densityFor('/notifications', 'ultra')).toBe('ultra');
  });

  it('never loosens a data surface below ultra', () => {
    // Seeing three more rows of open risk is not a taste question.
    expect(densityFor('/portfolio', 'comfortable')).toBe('ultra');
    expect(densityFor('/pnl', 'promax')).toBe('ultra');
    expect(densityFor('/trade', 'comfortable')).toBe('ultra');
  });

  it('still honours the comfortable list when the person asked for nothing', () => {
    // The route table is the default, not a thing the preference replaced.
    expect(densityFor('/docs', null)).toBe('comfortable');
  });

  it('lets the person tighten a page the table had left comfortable', () => {
    // The floor is a floor. Nothing stops anyone tightening a page the table had
    // left loose — the docs pages are comfortable by default, not by decree.
    expect(densityFor('/docs', 'ultra')).toBe('ultra');
  });

  it('round-trips through storage, and clearing returns to the default', () => {
    setDensityPref('promax');
    expect(getDensityPref()).toBe('promax');
    setDensityPref('comfortable');
    expect(getDensityPref()).toBe('comfortable');
    setDensityPref(null);
    expect(getDensityPref()).toBeNull();
  });

  it('ignores a stored value that is not a density', () => {
    // Anyone can type into localStorage. A junk value must read as "no choice",
    // not stamp `data-density="'; DROP"` onto every page.
    try { localStorage.setItem('hopefx.density', 'enormous'); } catch { /* ignore */ }
    expect(getDensityPref()).toBeNull();
  });

  it('survives a store that throws', () => {
    // Safari private mode. The page must render, at the default.
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() { throw new Error('storage blocked'); },
    });
    try {
      expect(getDensityPref()).toBeNull();
      expect(() => setDensityPref('ultra')).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, 'localStorage', original);
    }
  });

  it('tells the app when the choice changes, so a live page restyles', () => {
    let heard: unknown = 'nothing';
    const listener = (e: Event) => { heard = (e as CustomEvent).detail; };
    window.addEventListener('hopefx:density', listener);
    try {
      setDensityPref('promax');
      expect(heard).toBe('promax');
    } finally {
      window.removeEventListener('hopefx:density', listener);
    }
  });
});
