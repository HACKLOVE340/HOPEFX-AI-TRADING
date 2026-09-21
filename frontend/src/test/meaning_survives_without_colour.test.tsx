/**
 * F7-01 — direction and P&L sign must survive with the colour removed.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F7: *"Are red/green the only carriers of
 * long/short and P&L sign — and what does that mean for a colour-blind trader?"*
 *
 * The answer, on inspection, is **no**, and this pins it so it stays no:
 *
 *   - `SideBadge` renders `▲ Long` / `▼ Short` — a glyph and a word, with the
 *     colour as reinforcement rather than as the signal.
 *   - `fmtPnl` renders `+$50.00` / `-$50.00`. Its own docstring records the
 *     version where it did not: *"the negative branch previously produced an
 *     empty sign while still taking Math.abs, so every loss rendered as a
 *     positive number … Colour usually carried the meaning; the number did
 *     not."* Under deuteranopia that page had no loss indicator at all.
 *
 * These tests read the text with the styling ignored, which is what a
 * red-green colour-blind trader effectively does for these two hues. Roughly 8%
 * of men have some form of it, and this is a surface where mistaking a short
 * for a long, or a loss for a gain, costs money.
 *
 * Deliberately narrow. The rest of F7 — whether the most decision-relevant
 * number is the most prominent, whether the hierarchy scans in under a second —
 * needs a real screen, and the S10 scope note already recorded that reading
 * components cannot settle it. Not claimed here.
 */

import { describe, it, expect } from 'vitest';
import { fmtPnl, fmtPct, fmtPctRaw, positionSide } from '../lib/utils';

describe('P&L sign is in the text, not only the colour — F7-01', () => {
  it('a loss carries a minus sign', () => {
    expect(fmtPnl(-500)).toContain('-');
    expect(fmtPnl(-500)).toContain('500');
  });

  it('a gain carries a plus sign', () => {
    expect(fmtPnl(500).startsWith('+')).toBe(true);
  });

  it('a gain and a loss of the same magnitude are different strings', () => {
    // The regression that mattered: both rendered "$500.00" and only the colour
    // distinguished them.
    expect(fmtPnl(500)).not.toBe(fmtPnl(-500));
  });

  it('percentages carry their sign too', () => {
    expect(fmtPct(-0.05).startsWith('-')).toBe(true);
    expect(fmtPct(0.05).startsWith('+')).toBe(true);
    expect(fmtPctRaw(-5).startsWith('-')).toBe(true);
    expect(fmtPctRaw(5).startsWith('+')).toBe(true);
  });

  it('zero is not rendered as a loss', () => {
    expect(fmtPnl(0).startsWith('-')).toBe(false);
  });

  it('missing data is not rendered as zero', () => {
    // "—" and "+$0.00" mean very different things to someone deciding whether
    // to close a position.
    expect(fmtPnl(null)).toBe('—');
    expect(fmtPnl(undefined)).toBe('—');
  });
});

describe('long/short is not colour-only — F7-01', () => {
  it('the badge carries a glyph and a word', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.resolve(process.cwd(), 'src/components/panels/PositionsTable.tsx'),
      'utf8',
    );
    const badge = src.slice(src.indexOf('function SideBadge'));
    const body = badge.slice(0, badge.indexOf('\n}'));

    expect(/[▲▼]/.test(body), 'no directional glyph — colour is the only cue').toBe(true);
    expect(/long/i.test(body) && /short/i.test(body), 'no word for the direction').toBe(true);
  });

  it('an unreported direction is shown as unknown, not guessed', () => {
    // A guessed direction is worse than a missing one: it is confidently wrong
    // in the half of cases it gets backwards.
    expect(positionSide({})).toBeNull();
    expect(positionSide(null)).toBeNull();
    expect(positionSide({ side: 'weird' })).toBeNull();
  });

  it('accepts every spelling the API actually sends', () => {
    for (const v of ['long', 'LONG', 'buy', 'b', 'Buy']) {
      expect(positionSide({ side: v }), `side: ${v}`).toBe('long');
    }
    for (const v of ['short', 'SHORT', 'sell', 's', 'Sell']) {
      expect(positionSide({ side: v }), `side: ${v}`).toBe('short');
    }
    expect(positionSide({ direction: 'long' })).toBe('long');
  });
});
