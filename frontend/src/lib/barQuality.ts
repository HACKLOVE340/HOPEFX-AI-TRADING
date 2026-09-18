/**
 * barQuality — is this series of bars actually candles?
 *
 * ## Why this exists
 *
 * Measured 2026-09-15 against what `/api/trading/ohlcv/XAUUSD?timeframe=1d`
 * serves from the bundled history — the one timeframe that renders with no live
 * feed configured:
 *
 *     500 bars
 *      20  (4.0%)  open == high == low == close   — no body, no wick
 *      62 (12.4%)  high == max(o,c) and low == min(o,c)  — no wicks at all
 *       0          internally impossible
 *
 * Four charts drew those faithfully and said nothing. A flat line in a
 * candlestick series reads as "the market did not move in this session"; what
 * it actually means is "this bar was built from a single print". On a platform
 * that sizes positions off what the operator sees, that is §22's decorative
 * live value wearing a candlestick body — precise-looking, and not a
 * measurement of anything.
 *
 * ## What is NOT the fix
 *
 * The backend is not at fault and must not be changed to compensate. It already
 * refuses to fabricate: when no real source exists it returns a 503 naming the
 * symbol, the timeframe and the feed to configure, rather than inventing
 * movement. `_get_ohlcv_from_broker` says so in its own docstring — "price is
 * constant (no movement fabricated)". Filling the gaps would be the one thing
 * the pipeline has been careful not to do.
 *
 * The gap is that nothing told the operator when the bars that DID arrive were
 * degenerate. This closes that, and only that.
 *
 * ## Shared on purpose
 *
 * `CandleChart`, `AIChart`, `CoreChart` and `NuclearCandleChart` each draw
 * candles. Four private opinions of what a bad bar is would drift, and the one
 * that drifted would be the chart nobody opened. It is also pure, so every rule
 * below is testable without a canvas.
 */

export interface RawBar {
  /** Unix seconds. */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface BarQuality {
  total: number;
  /** open == high == low == close. No body, no wick — a single print. */
  flat: number;
  /** A body, but nothing traded outside it. Counted separately from `flat`. */
  wickless: number;
  /** high < max(o,c) or low > min(o,c). Not a thin bar — a wrong one. */
  impossible: number;
  /** lightweight-charts needs strictly ascending, finite times. */
  duplicateTimes: number;
  outOfOrder: number;
  unusableTimes: number;
  /** False when the series cannot be handed to the chart as it stands. */
  usable: boolean;
  /**
   * One sentence for the operator, or null when there is nothing to say.
   *
   * Null for an empty series too: that is the 503 path, and the endpoint's own
   * message already names the symbol, the timeframe and the feed to configure.
   * Printing "0% of 0 bars are flat" over the top of it would bury the one
   * sentence that tells them what to do.
   */
  notice: string | null;
}

/**
 * Below this share of degenerate bars, say nothing.
 *
 * A notice on every chart is a notice nobody reads, and one odd session in two
 * hundred is not worth interrupting for. 4% — what the daily series actually
 * carries — is above it, which is the point.
 */
const DEGENERATE_SHARE = 0.03;
/** …but never stay quiet about a short series, where a few bars IS the series. */
const SHORT_SERIES = 20;

export function assessBars(bars: readonly RawBar[]): BarQuality {
  let flat = 0;
  let wickless = 0;
  let impossible = 0;
  let duplicateTimes = 0;
  let outOfOrder = 0;
  let unusableTimes = 0;

  let previous: number | null = null;
  for (const b of bars) {
    if (!Number.isFinite(b.time) || !Number.isFinite(b.open) || !Number.isFinite(b.high)
        || !Number.isFinite(b.low) || !Number.isFinite(b.close)) {
      unusableTimes += 1;
      continue;
    }
    if (previous !== null) {
      if (b.time === previous) duplicateTimes += 1;
      else if (b.time < previous) outOfOrder += 1;
    }
    previous = b.time;

    const bodyHigh = Math.max(b.open, b.close);
    const bodyLow = Math.min(b.open, b.close);
    if (b.high < bodyHigh || b.low < 0 || b.low > bodyLow) {
      impossible += 1;
      continue;
    }
    // A flat bar satisfies the wickless test as well. Counting it in both would
    // overstate the damage, and a number that overstates gets ignored.
    if (b.open === b.high && b.high === b.low && b.low === b.close) flat += 1;
    else if (b.high === bodyHigh && b.low === bodyLow) wickless += 1;
  }

  const total = bars.length;
  const usable = total > 0 && duplicateTimes === 0 && outOfOrder === 0 && unusableTimes === 0;

  return {
    total, flat, wickless, impossible,
    duplicateTimes, outOfOrder, unusableTimes, usable,
    notice: noticeFor({ total, flat, wickless, impossible, duplicateTimes, outOfOrder, unusableTimes }),
  };
}

function noticeFor(q: Omit<BarQuality, 'usable' | 'notice'>): string | null {
  // An empty series is the 503 path; the endpoint's message is the one to show.
  if (q.total === 0) return null;

  // No tolerance for a bar that cannot be true. One means the SOURCE is wrong,
  // and the operator should not have to spot it by eye.
  if (q.impossible > 0) {
    return `${q.impossible} of ${q.total} bars are impossible — the high is below the body or the low above it. `
      + 'This is a data fault, not a thin market; do not read structure from this chart.';
  }

  if (q.unusableTimes > 0 || q.duplicateTimes > 0 || q.outOfOrder > 0) {
    const parts = [
      q.unusableTimes ? `${q.unusableTimes} with no usable timestamp` : '',
      q.duplicateTimes ? `${q.duplicateTimes} duplicated` : '',
      q.outOfOrder ? `${q.outOfOrder} out of order` : '',
    ].filter(Boolean);
    return `Timestamps are not a clean ascending series (${parts.join(', ')}). Some bars may be dropped or misplaced.`;
  }

  const degenerate = q.flat + q.wickless;
  const loud = q.total < SHORT_SERIES ? degenerate > 0 : degenerate / q.total > DEGENERATE_SHARE;
  if (!loud) return null;

  const bits: string[] = [];
  if (q.flat) bits.push(`${q.flat} with no range at all (a single print)`);
  if (q.wickless) bits.push(`${q.wickless} with no wicks`);
  return `${degenerate} of ${q.total} bars are not full candles — ${bits.join(', ')}. `
    + 'They are drawn as they arrived; the flat ones mean thin or missing data, not a still market.';
}
