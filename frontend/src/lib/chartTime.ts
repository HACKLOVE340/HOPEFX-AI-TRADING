/**
 * chartTime — one conversion from whatever the API sent to a chart timestamp.
 *
 * Four charts each grew their own `toUTC`, and they disagreed four ways:
 *
 *   AIChart              1e12 threshold · handles ISO strings · floors seconds
 *   Trading (/terminal)  1e12 threshold · handles ISO strings · floors seconds
 *   CoreChart            1e10 threshold · numbers only        · does NOT floor
 *   NuclearCandleChart   1e10 threshold · numbers only        · does NOT floor
 *
 * `Trading.tsx` also carried the comment "values > 1e10 are milliseconds"
 * directly above code testing `> 1_000_000_000_000`, so a reader trusting the
 * comment was wrong about the function under it.
 *
 * ## Why 1e10 and not 1e12
 *
 * Unix SECONDS for any date this platform can chart (1970-2100) is at most
 * ~4.1e9. Unix MILLISECONDS from 1973 onward is at least ~1e11. Any threshold
 * between those two separates them; 1e10 does and 1e12 does not:
 *
 *     2000-08-30 in milliseconds = 967,593,600,000 = 9.67e11, UNDER 1e12
 *
 * The 1e12 copies read that as seconds and place the bar in the year 32,633.
 * Not hypothetical: `data/XAUUSD_40Y_clamped.csv`, the bundled history the
 * daily chart falls back to when no live feed exists, starts on that date.
 *
 * ## Why it floors
 *
 * `api/trading.py::OHLCVBar` declares `timestamp: float`, and
 * lightweight-charts wants an integer second. Two of the four copies never
 * floored, so they were one unfloored source away from handing the library a
 * fraction.
 *
 * ## Why it returns NaN
 *
 * Because `AIChart` and `Trading` already filter with
 * `Number.isFinite(toUTC(...))`, and a conversion that cannot be trusted must
 * fail that test rather than return a plausible-looking wrong answer. The two
 * 1e10 copies returned `undefined` for a missing timestamp — not finite either,
 * but not a number, so a caller doing arithmetic on it got NaN one step later
 * and further from the cause.
 */

import type { UTCTimestamp } from 'lightweight-charts';

/**
 * Above this, the value is milliseconds.
 *
 * See the note above: the gap between the largest plausible second (~4.1e9, the
 * year 2100) and the smallest plausible millisecond (~1e11, 1973) is where this
 * has to sit.
 */
const MS_THRESHOLD = 1e10;

/** The latest second this will accept, so a millisecond value cannot slip through as one. */
const MAX_SECONDS = 4.2e9;

/**
 * Whatever the API sent → integer unix seconds, or **NaN** when it cannot be
 * converted. Never a guess.
 */
export function toUTCSeconds(ts: number | string | null | undefined): UTCTimestamp {
  if (typeof ts === 'string') {
    const parsed = Date.parse(ts);
    return (Number.isFinite(parsed) ? Math.floor(parsed / 1000) : Number.NaN) as UTCTimestamp;
  }
  if (typeof ts !== 'number' || !Number.isFinite(ts) || ts < 0) return Number.NaN as UTCTimestamp;

  const seconds = ts > MS_THRESHOLD ? ts / 1000 : ts;
  // A value that is still absurd after conversion is not a timestamp this can
  // repair — microseconds, a duration, a row index. Refuse rather than plot it
  // ten thousand years out and let the operator wonder why the chart is empty.
  if (seconds > MAX_SECONDS) return Number.NaN as UTCTimestamp;
  return Math.floor(seconds) as UTCTimestamp;
}
