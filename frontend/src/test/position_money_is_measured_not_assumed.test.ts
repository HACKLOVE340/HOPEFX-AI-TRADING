/**
 * Risk in money must be derived from the server's own numbers, or absent.
 *
 * `Position.size` carries no unit, and the frontend has no contract table —
 * 100 oz per lot for gold, 100,000 for a major FX pair, one for a share. Any
 * multiplier hardcoded in the UI is a guess that renders as a fact, and "you
 * are risking $410" is a worse thing to be wrong about than most.
 *
 * `unrealized_pnl` already encodes it: it is the price move times the money
 * value of one price unit. So the multiplier is measured, and when it cannot
 * be — the price has not moved off the entry yet — every figure that depends
 * on it is absent instead of zero.
 *
 * The gold case below is arithmetic anyone can check: 0.50 lots is 50 oz, the
 * mark is 8.25 above the entry, and 8.25 × 50 = $412.50.
 */

import { describe, it, expect } from 'vitest';
import { impliedUnitValue, riskReward, bracketProgress, distanceTo } from '../lib/position_math';

const GOLD_LONG = {
  side: 'long',
  entry_price: 2318.4,
  current_price: 2326.65,
  unrealized_pnl: 412.5,
  stop_loss: 2310.2,
  take_profit: 2342.8,
};

const GOLD_SHORT = {
  side: 'short',
  entry_price: 2309.8,
  current_price: 2326.65,
  unrealized_pnl: -421.25, // 16.85 against, 25 oz
  stop_loss: 2318.6,
  take_profit: 2294.5,
};

describe('position money — measured, never assumed', () => {
  it('recovers the contract multiplier from the position itself', () => {
    expect(impliedUnitValue(GOLD_LONG)).toBeCloseTo(50, 6);
    expect(impliedUnitValue(GOLD_SHORT)).toBeCloseTo(25, 6);
  });

  it('prices the stop and the target with that multiplier', () => {
    const { risk, reward, ratio } = riskReward(GOLD_LONG);
    expect(risk).toBeCloseTo(410, 2); // (2318.40 − 2310.20) × 50
    expect(reward).toBeCloseTo(1220, 2); // (2342.80 − 2318.40) × 50
    expect(ratio).toBeCloseTo(2.9756, 3);
  });

  it('handles a short without flipping the sign of the multiplier', () => {
    const { risk, reward } = riskReward(GOLD_SHORT);
    expect(risk).toBeCloseTo(220, 2); // (2318.60 − 2309.80) × 25
    expect(reward).toBeCloseTo(382.5, 2); // (2309.80 − 2294.50) × 25
  });

  it('is absent, not zero, when the price has not moved off the entry', () => {
    const flat = { ...GOLD_LONG, current_price: 2318.4, unrealized_pnl: 0 };
    expect(impliedUnitValue(flat)).toBeNull();
    expect(riskReward(flat)).toEqual({ risk: null, reward: null, ratio: null });
  });

  it('is absent when a level the figure depends on does not exist', () => {
    // A position with no stop has unbounded risk. Rendering that as $0.00
    // would be the most misleading number on the page.
    const noStop = { ...GOLD_LONG, stop_loss: undefined };
    const { risk, reward, ratio } = riskReward(noStop);
    expect(risk).toBeNull();
    expect(ratio).toBeNull();
    expect(reward).toBeCloseTo(1220, 2);
  });

  it('refuses a multiplier the arithmetic says is impossible', () => {
    // P&L disagreeing in sign with the move means the two numbers are not
    // describing the same position. A negative multiplier is not a reading.
    expect(impliedUnitValue({ ...GOLD_LONG, unrealized_pnl: -412.5 })).toBeNull();
    expect(impliedUnitValue({ ...GOLD_LONG, side: 'sideways' })).toBeNull();
    expect(impliedUnitValue(null)).toBeNull();
  });

  it('places the mark within its bracket, clamped', () => {
    // 2326.65 sits (2326.65 − 2310.20) / (2342.80 − 2310.20) = 0.5046 along.
    expect(bracketProgress(GOLD_LONG)).toBeCloseTo(0.5046, 3);
    expect(bracketProgress({ ...GOLD_LONG, current_price: 2400 })).toBe(1);
    expect(bracketProgress({ ...GOLD_LONG, current_price: 2000 })).toBe(0);
    expect(bracketProgress({ ...GOLD_LONG, stop_loss: undefined })).toBeNull();
  });

  it('measures distance to a level without caring which side it is on', () => {
    expect(distanceTo(GOLD_LONG, 2342.8)).toBeCloseTo(16.15, 4);
    expect(distanceTo(GOLD_LONG, 2310.2)).toBeCloseTo(16.45, 4);
    expect(distanceTo(GOLD_LONG, undefined)).toBeNull();
  });
});
