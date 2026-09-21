/**
 * Four charts each had their own `toUTC`, and they disagreed four ways.
 *
 *   AIChart              1e12 threshold · handles ISO strings · floors seconds
 *   Trading (/terminal)  1e12 threshold · handles ISO strings · floors seconds
 *   CoreChart            1e10 threshold · numbers only        · does NOT floor
 *   NuclearCandleChart   1e10 threshold · numbers only        · does NOT floor
 *
 * And `Trading.tsx` carried the comment "values > 1e10 are milliseconds"
 * directly above code testing `> 1_000_000_000_000`. A reader trusting the
 * comment would have been wrong about the function under it.
 *
 * ## 1e10 is right and 1e12 is not
 *
 * Unix SECONDS for any date this platform can chart (1970-2100) is at most
 * ~4.1e9. Unix MILLISECONDS for 1973 onward is at least ~1e11. So any threshold
 * between those separates them — 1e10 does, 1e12 does not:
 *
 *   2000-08-30 in ms = 967,593,600,000 = 9.67e11, which is UNDER 1e12
 *
 * The 1e12 copies read that as seconds and place the bar in the year 32,633.
 * This is not hypothetical arithmetic: `data/XAUUSD_40Y_clamped.csv`, the
 * bundled history the daily chart falls back to, starts 2000-08-30.
 *
 * ## Floor, because the API declares a float
 *
 * `api/trading.py::OHLCVBar` is `timestamp: float`. lightweight-charts wants an
 * integer second. Two of the four copies never floored, so they were one
 * unfloored source away from handing the library a fraction.
 *
 * ## NaN is the refusal, and callers depend on it
 *
 * `AIChart` and `Trading` already filter with `Number.isFinite(toUTC(...))`.
 * The two `1e10` copies returned `undefined` for a missing timestamp, which is
 * not finite either but is not a number — so a shared version must return NaN
 * for anything it cannot convert, and never a plausible-looking wrong answer.
 */
import { describe, it, expect } from 'vitest';

import { toUTCSeconds } from '../lib/chartTime';

describe('seconds pass through', () => {
  it('keeps a plain unix second', () => {
    expect(toUTCSeconds(1_700_000_000)).toBe(1_700_000_000);
  });

  it('floors a fractional second, because the API declares a float', () => {
    expect(toUTCSeconds(1_700_000_000.75)).toBe(1_700_000_000);
  });

  it('keeps the epoch itself', () => {
    expect(toUTCSeconds(0)).toBe(0);
  });
});

describe('milliseconds are detected', () => {
  it('converts a present-day millisecond timestamp', () => {
    expect(toUTCSeconds(1_700_000_000_000)).toBe(1_700_000_000);
  });

  it('converts a millisecond timestamp from before 2001 — what 1e12 got wrong', () => {
    // 2000-08-30T00:00:00Z. The bundled 40-year gold history starts here.
    const ms = Date.UTC(2000, 7, 30) as number;
    expect(ms).toBeLessThan(1e12);            // under the old threshold
    expect(toUTCSeconds(ms)).toBe(Math.floor(ms / 1000));
    // Sanity: that is the year 2000, not the year 32,633.
    expect(new Date(toUTCSeconds(ms) * 1000).getUTCFullYear()).toBe(2000);
  });

  it('does not mistake a far-future SECOND for a millisecond', () => {
    // Year 2100 in seconds is ~4.1e9, comfortably under 1e10.
    const y2100 = Math.floor(Date.UTC(2100, 0, 1) / 1000);
    expect(y2100).toBeLessThan(1e10);
    expect(toUTCSeconds(y2100)).toBe(y2100);
  });
});

describe('ISO strings', () => {
  it('parses one', () => {
    expect(toUTCSeconds('2024-03-01T00:00:00Z')).toBe(Math.floor(Date.UTC(2024, 2, 1) / 1000));
  });

  it('refuses an unparseable one rather than guessing', () => {
    expect(Number.isNaN(toUTCSeconds('not a date'))).toBe(true);
  });
});

describe('it refuses rather than returning a plausible wrong answer', () => {
  it.each([
    ['undefined', undefined],
    ['null', null],
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
    ['a negative time', -1],
    ['an object', {}],
  ])('returns NaN for %s', (_label, input) => {
    expect(Number.isNaN(toUTCSeconds(input as never))).toBe(true);
  });

  it('is filterable with Number.isFinite, which every caller already does', () => {
    const raw = [1_700_000_000, undefined, 'not a date', 1_700_086_400];
    const kept = raw.map((t) => toUTCSeconds(t as never)).filter(Number.isFinite);
    expect(kept).toEqual([1_700_000_000, 1_700_086_400]);
  });
});
