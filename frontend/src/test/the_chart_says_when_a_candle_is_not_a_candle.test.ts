/**
 * A candle chart drawn from degenerate bars looks like market structure and is
 * not one.
 *
 * Measured 2026-09-15 against the bars `/api/trading/ohlcv/XAUUSD?timeframe=1d`
 * actually serves from the bundled history — the one timeframe that renders
 * with no live feed:
 *
 *     500 bars
 *      20  (4.0%)  open == high == low == close   — no body, no wick
 *      62 (12.4%)  high == max(o,c) and low == min(o,c)  — no wicks at all
 *       0          internally impossible
 *
 * Every chart draws those faithfully and says nothing, so a flat line reads as
 * "the market did not move in this session" when it actually means "this bar
 * was built from a single print". On a platform that sizes positions off what
 * the operator sees, that is §22's decorative live value with a candlestick
 * body: precise-looking, and not a measurement of anything.
 *
 * The backend is NOT at fault here and must not be changed to compensate. It
 * already refuses to fabricate — when no real source exists it returns a 503
 * naming the symbol, the timeframe and the feed to configure, rather than
 * inventing movement. The gap is that nothing tells the operator when the bars
 * that DID arrive are degenerate.
 *
 * This is the assessment, kept pure so it can be tested without a canvas, and
 * shared so four charts cannot each grow their own opinion of what a bad bar is.
 */
import { describe, it, expect } from 'vitest';

import { assessBars, type RawBar } from '../lib/barQuality';

const bar = (o: number, h: number, l: number, c: number, time = 1_700_000_000, volume = 1): RawBar =>
  ({ time, open: o, high: h, low: l, close: c, volume });

describe('assessBars — a real series', () => {
  it('reports nothing wrong with ordinary candles', () => {
    const q = assessBars([
      bar(100, 105, 99, 104, 1_700_000_000),
      bar(104, 108, 103, 107, 1_700_086_400),
      bar(107, 110, 101, 102, 1_700_172_800),
    ]);
    expect(q.total).toBe(3);
    expect(q.flat).toBe(0);
    expect(q.wickless).toBe(0);
    expect(q.impossible).toBe(0);
    expect(q.usable).toBe(true);
    expect(q.notice).toBeNull();
  });

  it('says nothing for an empty series — that is the 503 path, not a quality problem', () => {
    // The endpoint returns a 503 naming the reason when it has no real data.
    // Reporting "0% of 0 bars are flat" over the top of that would bury it.
    const q = assessBars([]);
    expect(q.total).toBe(0);
    expect(q.notice).toBeNull();
    expect(q.usable).toBe(false);
  });
});

describe('assessBars — degenerate bars', () => {
  it('counts a bar with no body and no wick', () => {
    const q = assessBars([bar(100, 100, 100, 100), bar(101, 105, 99, 104, 1_700_086_400)]);
    expect(q.flat).toBe(1);
  });

  it('counts a bar with a body but no wicks', () => {
    // high == max(o,c), low == min(o,c). Real bars almost never do this: it
    // means nothing traded outside the open and the close.
    const q = assessBars([bar(100, 104, 100, 104), bar(104, 108, 103, 107, 1_700_086_400)]);
    expect(q.wickless).toBe(1);
    expect(q.flat).toBe(0);
  });

  it('does not double-count a flat bar as wickless', () => {
    // A flat bar satisfies the wickless test too. Counting it twice would
    // overstate the damage, and a number that overstates gets ignored.
    const q = assessBars([bar(100, 100, 100, 100)]);
    expect(q.flat).toBe(1);
    expect(q.wickless).toBe(0);
  });

  it('raises a notice once degeneracy passes the threshold', () => {
    const mostlyFlat = Array.from({ length: 10 }, (_, i) =>
      i < 4 ? bar(100 + i, 100 + i, 100 + i, 100 + i, 1_700_000_000 + i * 86_400)
            : bar(100 + i, 105 + i, 99 + i, 104 + i, 1_700_000_000 + i * 86_400));
    const q = assessBars(mostlyFlat);
    expect(q.flat).toBe(4);
    expect(q.notice).toMatch(/single print|no range|flat/i);
    // The sentence must carry the NUMBER. "Some bars are flat" is not a
    // measurement and an operator cannot act on it.
    expect(q.notice).toMatch(/4/);
  });

  it('stays quiet about one odd bar in a long, healthy series', () => {
    // A notice on every chart is a notice nobody reads.
    const bars = Array.from({ length: 200 }, (_, i) =>
      i === 7 ? bar(100, 100, 100, 100, 1_700_000_000 + i * 86_400)
              : bar(100, 105, 99, 104, 1_700_000_000 + i * 86_400));
    expect(assessBars(bars).notice).toBeNull();
  });
});

describe('assessBars — bars that cannot be true', () => {
  it('flags a high below the body', () => {
    // high < max(open, close) is not a thin bar, it is a wrong one. Nothing in
    // the pipeline produces it today (measured: 0 of 500), which is exactly
    // when a guard is cheap to add.
    const q = assessBars([bar(100, 102, 99, 104)]);
    expect(q.impossible).toBe(1);
    expect(q.notice).toMatch(/impossible|cannot be/i);
  });

  it('flags a low above the body', () => {
    expect(assessBars([bar(100, 105, 101, 100)]).impossible).toBe(1);
  });

  it('flags one impossible bar however long the series', () => {
    // Unlike flatness, this has no tolerance: one wrong bar means the source is
    // wrong, and the operator should not have to spot it by eye.
    const bars = Array.from({ length: 500 }, (_, i) =>
      i === 300 ? bar(100, 102, 99, 104, 1_700_000_000 + i * 86_400)
                : bar(100, 105, 99, 104, 1_700_000_000 + i * 86_400));
    const q = assessBars(bars);
    expect(q.impossible).toBe(1);
    expect(q.notice).toMatch(/impossible|cannot be/i);
  });
});

describe('assessBars — what lightweight-charts requires', () => {
  it('flags duplicate timestamps', () => {
    // The library needs strictly ascending times. Duplicates make it throw or
    // silently drop bars, and neither tells the operator anything.
    const q = assessBars([bar(100, 105, 99, 104, 1_700_000_000), bar(104, 108, 103, 107, 1_700_000_000)]);
    expect(q.duplicateTimes).toBe(1);
    expect(q.usable).toBe(false);
  });

  it('flags bars out of order', () => {
    const q = assessBars([bar(100, 105, 99, 104, 1_700_086_400), bar(104, 108, 103, 107, 1_700_000_000)]);
    expect(q.outOfOrder).toBe(1);
    expect(q.usable).toBe(false);
  });

  it('flags a non-finite timestamp rather than handing it to the chart', () => {
    const q = assessBars([bar(100, 105, 99, 104, Number.NaN)]);
    expect(q.unusableTimes).toBe(1);
    expect(q.usable).toBe(false);
  });
});
