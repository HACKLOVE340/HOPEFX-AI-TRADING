/**
 * A constraint nobody measured must not render as "0% used".
 *
 * `/api/risk/prop-firm-status` is gated to the professional plan, and its own
 * fallback path builds a read-only engine from `prop_firm_mode.json` seeded
 * with a default $100K account when no trades have been recorded. So the
 * frontend can be handed: a 403, a body with fields missing, or a body whose
 * numbers describe a default account rather than this one.
 *
 * Every one of those is *unknown*, and a headroom bar showing an unknown
 * constraint at zero reads as "plenty of room" — the most dangerous possible
 * rendering of "we don't know", on a screen whose whole job is telling a
 * trader how close they are to being stopped out.
 *
 * This is rule 2 of the four governing this repository: an unmeasured value is
 * absent, never zero. `deriveConstraints` drops what it cannot compute, and
 * the caller shows nothing rather than something reassuring.
 */

import { describe, it, expect } from 'vitest';
import { deriveConstraints } from '../lib/risk_headroom';
import { nearestConstraint } from '../components/system/RiskHeadroom';

const FULL = {
  daily_loss_pct: 0.0125,
  daily_loss_limit: 0.05,
  max_drawdown_pct: 0.0519,
  max_drawdown_limit: 0.1,
  starting_equity: 25000,
  current_equity: 24681.6,
};

describe('deriveConstraints — absent is absent', () => {
  it('derives all three when everything is present', () => {
    const cs = deriveConstraints(FULL, { margin_level: 1116.6, margin_free: 22471.29 });
    expect(cs.map((c) => c.name)).toEqual(['Max drawdown', 'Daily loss', 'Margin call']);
  });

  it('computes headroom in money, not in percent', () => {
    const [dd, daily] = deriveConstraints(FULL, {});
    // (0.05 − 0.0125) × 25,000 = 937.50 still available today.
    expect(daily!.remaining).toBeCloseTo(937.5, 2);
    // (0.10 − 0.0519) × 25,000 = 1,202.50 before the account is done.
    expect(dd!.remaining).toBeCloseTo(1202.5, 2);
    expect(daily!.used).toBeCloseTo(0.25, 4);
    expect(dd!.used).toBeCloseTo(0.519, 4);
  });

  it('drops a constraint whose status the server never sent', () => {
    expect(deriveConstraints(null, {})).toEqual([]);
    expect(deriveConstraints(undefined, { margin_level: 1116.6, margin_free: 100 })).toHaveLength(1);
  });

  it('drops a constraint whose limit is missing, rather than showing it at zero', () => {
    const noDaily = deriveConstraints({ ...FULL, daily_loss_limit: undefined }, {});
    expect(noDaily.map((c) => c.name)).toEqual(['Max drawdown']);

    const noneAtAll = deriveConstraints(
      { starting_equity: 25000, current_equity: 24681.6 },
      {},
    );
    expect(noneAtAll).toEqual([]);
  });

  it('drops a constraint whose limit is zero — dividing by it would read as safe', () => {
    // used = pct / 0 is Infinity, and a naive clamp would paint it full; a
    // naive guard would paint it empty. Neither is true, so it is absent.
    const cs = deriveConstraints({ ...FULL, daily_loss_limit: 0 }, {});
    expect(cs.map((c) => c.name)).toEqual(['Max drawdown']);
  });

  it('treats an unusable margin level as unknown', () => {
    // NO_MARGIN_LEVEL (9999) is the sentinel for "no margin in use"; a zero or
    // negative level is not a reading.
    expect(deriveConstraints(null, { margin_level: 0, margin_free: 500 })).toEqual([]);
    expect(deriveConstraints(null, { margin_level: -3, margin_free: 500 })).toEqual([]);
    expect(deriveConstraints(null, { margin_level: 9999, margin_free: 500 })).toEqual([]);
  });

  it('names the binding constraint, which is not the biggest number', () => {
    const cs = deriveConstraints(FULL, { margin_level: 1116.6, margin_free: 22471.29 });
    const worst = nearestConstraint(cs);
    // Daily loss has the smaller remaining balance ($937.50 vs $1,202.50), but
    // drawdown has consumed more of its allowance (51.9% vs 25%). Proximity to
    // the rule is what matters, not the size of the cushion.
    expect(worst?.name).toBe('Max drawdown');
    expect(nearestConstraint([])).toBeNull();
  });
});
