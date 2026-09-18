/**
 * Turn what the server actually sent into the constraints a trader is under.
 *
 * Three rules can end a session on this platform: the prop-firm daily loss
 * limit, the prop-firm maximum drawdown, and a margin call.
 * `prop_firm_mode.json` ships with `enabled: true` and the FTMO ruleset, so
 * the first two are live on a fresh deployment and none of the three appeared
 * anywhere in the UI.
 *
 * The hard part is not the arithmetic, it is what to do when a number is
 * missing. `/api/risk/prop-firm-status` is gated to the professional plan, and
 * its own fallback builds a read-only engine from the config file seeded with
 * a default $100K account when no trades have been recorded. So "no answer",
 * "partial answer" and "an answer about a different account" are all reachable.
 *
 * Every one of them means unknown, and the repository's second rule applies:
 * an unmeasured value is absent, never zero. A constraint that cannot be
 * computed is dropped, so the bar shows nothing rather than showing an empty
 * segment — which on this screen would read as "plenty of room".
 */

import { NO_MARGIN_LEVEL } from './utils';
import type { Constraint } from '../components/system/RiskHeadroom';

/** The fields of `PropFirmStatus` this derivation needs. All optional. */
export interface PropFirmHeadroom {
  /** Fraction 0–1 of starting equity lost today. */
  daily_loss_pct?: number;
  /** Fraction 0–1 allowed to be lost in a day before trading pauses. */
  daily_loss_limit?: number;
  /** Fraction 0–1 drawn down from the challenge's starting equity. */
  max_drawdown_pct?: number;
  /** Fraction 0–1 allowed before the challenge is failed. */
  max_drawdown_limit?: number;
  starting_equity?: number;
  current_equity?: number;
}

/** The fields of `AccountMetrics` this derivation needs. All optional. */
export interface AccountHeadroom {
  /** Percentage: equity / margin × 100. 9999 is the "no margin used" sentinel. */
  margin_level?: number;
  margin_free?: number;
}

const usable = (n: unknown): n is number =>
  typeof n === 'number' && Number.isFinite(n);

/**
 * A ratio of spent allowance, or null when it cannot be known.
 *
 * A zero limit is not a limit: `pct / 0` is Infinity, which a clamp would
 * paint as full and a guard would paint as empty, and neither is a reading.
 */
function spent(pct: unknown, limit: unknown): number | null {
  if (!usable(pct) || !usable(limit) || limit <= 0) return null;
  return pct / limit;
}

export function deriveConstraints(
  prop: PropFirmHeadroom | null | undefined,
  account: AccountHeadroom | null | undefined,
): Constraint[] {
  const out: Constraint[] = [];
  const equity = prop?.starting_equity;

  // Order is the tiebreak when two constraints are equally close, so the more
  // consequential rule is listed first: losing the account beats losing the day.
  const drawdownUsed = spent(prop?.max_drawdown_pct, prop?.max_drawdown_limit);
  if (drawdownUsed !== null && usable(equity)) {
    out.push({
      name: 'Max drawdown',
      used: drawdownUsed,
      remaining: (prop!.max_drawdown_limit! - prop!.max_drawdown_pct!) * equity,
      tone: 'loss',
    });
  }

  const dailyUsed = spent(prop?.daily_loss_pct, prop?.daily_loss_limit);
  if (dailyUsed !== null && usable(equity)) {
    out.push({
      name: 'Daily loss',
      used: dailyUsed,
      remaining: (prop!.daily_loss_limit! - prop!.daily_loss_pct!) * equity,
      tone: 'warn',
    });
  }

  // A margin call lands at 100%. Level is equity/margin × 100, so the share of
  // the cushion spent is 100 / level. The sentinel means no margin is in use,
  // which is not the same as being safe by a measured amount — it is simply
  // not a constraint yet.
  const level = account?.margin_level;
  if (usable(level) && level > 0 && level !== NO_MARGIN_LEVEL && usable(account?.margin_free)) {
    out.push({
      name: 'Margin call',
      used: 100 / level,
      remaining: account!.margin_free!,
      tone: 'accent',
    });
  }

  return out;
}
