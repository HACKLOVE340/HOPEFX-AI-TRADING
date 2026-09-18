/**
 * Win rate and drawdown are percentages, and three screens scaled them twice.
 *
 * `GET /api/trading/account` computes both as `x / n * 100` — percentages
 * 0-100, on both the paper and live paths. Three places then multiplied by 100
 * again:
 *
 *   Dashboard.tsx      `(v * 100).toFixed(1) + '%'`   for win_rate
 *                      `(v * 100).toFixed(2) + '%'`   for max_drawdown
 *   AccountBar.tsx     `fmtPct(account.win_rate, 1)`
 *   RiskDashboard.tsx  `fmtPct(account?.win_rate, 1)`
 *
 * A real 62.5% win rate would have rendered as 6250.0%, and a 12.4% drawdown
 * as 1240.00%. Nobody had seen it, because until the endpoint learned to send
 * null both values were pinned at 0 — and 0 x 100 is still 0.
 *
 * The colour thresholds carried the same error in the other direction:
 * `win_rate >= 0.55` against a 0-100 value passes any win rate above half a
 * percent, and `max_drawdown < 0.1` fails any drawdown above a tenth of a
 * percent. A 20% win rate showed green.
 *
 * `fmtPct` and `fmtPctRaw` both exist for this reason and are easy to pick
 * wrongly, so the first block pins which one takes which unit.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fmtPct, fmtPctRaw } from '../lib/utils';
import { WIN_RATE_GOOD_PCT, SHARPE_GOOD, DRAWDOWN_WARN_PCT } from '../pages/Dashboard';

const read = (relative: string): string =>
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', relative), 'utf8');

describe('which formatter takes which unit', () => {
  it('fmtPct takes a fraction', () => {
    expect(fmtPct(0.625, 1)).toBe('+62.5%');
  });

  it('fmtPctRaw takes a percentage', () => {
    expect(fmtPctRaw(62.5, 1)).toBe('+62.5%');
  });

  it('feeding a percentage to fmtPct is the bug, stated plainly', () => {
    expect(fmtPct(62.5, 1)).toBe('+6250.0%');
  });

  it('both render an absent value as a dash rather than zero', () => {
    expect(fmtPct(null)).toBe('—');
    expect(fmtPctRaw(null)).toBe('—');
    expect(fmtPct(undefined)).toBe('—');
    expect(fmtPctRaw(undefined)).toBe('—');
  });

  it('neither invents a number from a non-finite value', () => {
    expect(fmtPctRaw(Number.NaN)).toBe('—');
    expect(fmtPctRaw(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('the thresholds are in the units the API sends', () => {
  it('a good win rate is 55 percent, not 0.55', () => {
    expect(WIN_RATE_GOOD_PCT).toBe(55);
  });

  it('the drawdown warning is 10 percent, not 0.1', () => {
    expect(DRAWDOWN_WARN_PCT).toBe(10);
  });

  it('Sharpe is unitless and keeps its ratio threshold', () => {
    expect(SHARPE_GOOD).toBe(1.5);
  });

  it('a mediocre win rate no longer clears the bar', () => {
    // Against the old `>= 0.55`, every one of these passed.
    for (const winRate of [1, 12.5, 20, 42, 54.9]) {
      expect(winRate >= WIN_RATE_GOOD_PCT).toBe(false);
    }
  });

  it('a genuinely good win rate still clears it', () => {
    for (const winRate of [55, 58.4, 71.2, 100]) {
      expect(winRate >= WIN_RATE_GOOD_PCT).toBe(true);
    }
  });

  it('an ordinary drawdown no longer reads as a breach', () => {
    // Against the old `< 0.1`, every one of these was red.
    for (const drawdown of [0.5, 2, 4.1, 9.9]) {
      expect(drawdown < DRAWDOWN_WARN_PCT).toBe(true);
    }
  });

  it('a real breach still reads as one', () => {
    for (const drawdown of [10, 12.4, 31]) {
      expect(drawdown < DRAWDOWN_WARN_PCT).toBe(false);
    }
  });
});

describe('no call site scales the value a second time', () => {
  // Wiring, not behaviour: what regressed here was which expression sits at
  // each of the three call sites, and a string check is what catches that.

  it('the dashboard tiles render win rate and drawdown as sent', () => {
    const source = read('pages/Dashboard.tsx');
    expect(source).toContain("orDash(acc.win_rate, v => v.toFixed(1) + '%')");
    expect(source).toContain("orDash(acc.max_drawdown, v => v.toFixed(2) + '%')");
  });

  it('the dashboard compares against the named thresholds, not bare decimals', () => {
    const source = read('pages/Dashboard.tsx');
    expect(source).toContain('acc.win_rate >= WIN_RATE_GOOD_PCT');
    expect(source).toContain('acc.max_drawdown < DRAWDOWN_WARN_PCT');
    expect(source).not.toContain('acc.win_rate >= 0.55');
    expect(source).not.toContain('acc.max_drawdown < 0.1');
  });

  it('the account bar uses the raw formatter', () => {
    expect(read('components/terminal/AccountBar.tsx')).toContain('fmtPctRaw(account.win_rate, 1)');
  });

  it('the risk panel uses the raw formatter', () => {
    expect(read('components/panels/RiskDashboard.tsx')).toContain('fmtPctRaw(account?.win_rate, 1)');
  });

  it('sharpe is not scaled at all', () => {
    const source = read('pages/Dashboard.tsx');
    expect(source).toContain('orDash(acc.sharpe_ratio, v => v.toFixed(2))');
  });
});
