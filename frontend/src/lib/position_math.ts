/**
 * Position arithmetic that refuses to invent a contract multiplier.
 *
 * A stop distance in price is easy. Turning it into money needs to know what
 * one price unit is worth for this position, and that depends on the contract
 * size — 100 oz per lot for gold, 100,000 units for a major FX pair, one share
 * for equity. `Position` carries `size` with no unit and the frontend has no
 * contract table, so any multiplier written here would be a guess that looks
 * like a fact, and a wrong risk figure on a trading screen is worse than none.
 *
 * The server already answers it, though, in a number it sends: `unrealized_pnl`
 * IS the price move times the money value of a price unit. Divide one by the
 * other and the multiplier falls out, measured rather than assumed.
 *
 * That division is only safe when the price has actually moved, so when it has
 * not, this returns null and every money figure derived from it is absent
 * rather than zero.
 */

import { positionSide } from './utils';

export interface PositionLike {
  side?: string | null;
  direction?: string | null;
  entry_price?: number | null;
  current_price?: number | null;
  unrealized_pnl?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
}

const num = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/**
 * Money per one unit of price movement, derived from the position's own P&L.
 *
 * The epsilon is a price epsilon, not a money one: below it the division
 * amplifies rounding in `unrealized_pnl` into a wildly wrong multiplier. Gold
 * ticks in cents, so a tenth of a cent is comfortably below any real move and
 * comfortably above float noise.
 */
const PRICE_EPSILON = 0.001;

export function impliedUnitValue(pos: PositionLike | null | undefined): number | null {
  const side = positionSide(pos ?? undefined);
  if (!side || !pos) return null;
  if (!num(pos.entry_price) || !num(pos.current_price) || !num(pos.unrealized_pnl)) return null;

  const move = pos.current_price - pos.entry_price;
  if (Math.abs(move) < PRICE_EPSILON) return null;

  const signed = side === 'long' ? move : -move;
  const units = pos.unrealized_pnl / signed;
  if (!Number.isFinite(units) || units <= 0) return null;
  return units;
}

/** Price distance from the mark to a level, or null when either is unknown. */
export function distanceTo(pos: PositionLike | null | undefined, level: number | null | undefined): number | null {
  if (!pos || !num(pos.current_price) || !num(level)) return null;
  return Math.abs(level - pos.current_price);
}

/**
 * What is risked to the stop and earned to the target, in money.
 *
 * Both are null unless the multiplier could be measured AND the level exists —
 * a position with no stop has unbounded risk, and rendering that as "$0.00"
 * would be the most misleading number on the page.
 */
export function riskReward(pos: PositionLike | null | undefined): {
  risk: number | null;
  reward: number | null;
  ratio: number | null;
} {
  const units = impliedUnitValue(pos);
  const entry = pos?.entry_price;
  if (units === null || !num(entry)) return { risk: null, reward: null, ratio: null };

  const risk = num(pos?.stop_loss) ? Math.abs(entry - pos!.stop_loss!) * units : null;
  const reward = num(pos?.take_profit) ? Math.abs(pos!.take_profit! - entry) * units : null;
  const ratio = risk !== null && reward !== null && risk > 0 ? reward / risk : null;
  return { risk, reward, ratio };
}

/**
 * Where the mark sits between stop and target, as 0–1.
 *
 * Used to place the marker on the ladder. Null unless both levels exist, and
 * clamped, because price can and does trade outside the bracket before the
 * order fills.
 */
export function bracketProgress(pos: PositionLike | null | undefined): number | null {
  if (!pos || !num(pos.current_price) || !num(pos.stop_loss) || !num(pos.take_profit)) return null;
  const span = pos.take_profit - pos.stop_loss;
  if (Math.abs(span) < PRICE_EPSILON) return null;
  const at = (pos.current_price - pos.stop_loss) / span;
  return Math.min(1, Math.max(0, at));
}
