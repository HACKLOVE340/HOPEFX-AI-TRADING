/**
 * Signed-number display contract.
 *
 * A hardcoded '+' in front of a value that can be negative produces `+-15.0%`,
 * and the surrounding colour was usually green because it never consulted the
 * number either. That appeared on a strategy's headline return in the
 * marketplace, a copy-trading leader's 3-month return, and the "Best Trade"
 * figure in the journal — the numbers people decide with.
 *
 * `fmtPnl` and `fmtPctRaw` in lib/utils already did this correctly. The theme of
 * the whole audit is that the right helper usually exists and was not carried
 * across, so this guard names the sites rather than trusting the habit.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fmtPnl, fmtPctRaw } from '../lib/utils';

const PAGES = join(__dirname, '..', 'pages');

describe('shared signed-number formatters', () => {
  it('render a leading + only for non-negative values', () => {
    expect(fmtPctRaw(18.4, 1)).toBe('+18.4%');
    expect(fmtPctRaw(-15, 1)).toBe('-15.0%');
    expect(fmtPnl(50)).toBe('+$50.00');
    expect(fmtPnl(-50)).toBe('-$50.00');
  });

  it('return an em dash rather than NaN for missing values', () => {
    expect(fmtPctRaw(null)).toBe('—');
    expect(fmtPctRaw(Number.NaN)).toBe('—');
    expect(fmtPnl(undefined)).toBe('—');
    expect(fmtPnl(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('pages that display signed performance figures', () => {
  // Sites the audit found rendering "+-15.0%". Each must go through a formatter
  // that derives the sign, not concatenate one.
  const CASES: Array<[string, RegExp]> = [
    ['Marketplace.tsx', /`\+\$\{fmt\(p\.total_return_pct\)\}%`/],
    ['CopyTrading.tsx', /\+\{leader\.return_3m\}%/],
    ['TradeJournal.tsx', /`\+\$\$\{fmt\(stats\.best_trade_pnl\)\}`/],
  ];

  it.each(CASES)('%s does not concatenate a + onto a signed value', (file, pattern) => {
    const src = readFileSync(join(PAGES, file), 'utf8');
    expect(pattern.test(src), `${file} reintroduced a hardcoded + sign`).toBe(false);
  });
});
