/**
 * Type accuracy — the root cause behind every crash vector in the audit (#37–#40).
 *
 * `tsconfig.json` has had `"strict": true` all along, and `build` runs
 * `tsc --noEmit`. The compiler was fully in the loop. So why did this compile?
 *
 *     acc.sharpe_ratio.toFixed(2)      // TypeError when the API omits it
 *
 * Because `types/trading.ts` declared `sharpe_ratio: number` — required. `strict`
 * was working perfectly; it was faithfully enforcing an *optimistic description
 * of the API*. Every crash vector in this audit is a hand-written interface
 * promising a field the server can legitimately omit.
 *
 * `Profile.tsx` proved it outright: the same file declared `stats` required and
 * wrote `profile.stats ?? {zeros}` a hundred lines later. The author knew the
 * type was wrong and worked around it rather than correcting it — then did not
 * apply the same care to `sig.confidence` and `sig.pnl`.
 *
 * These are source assertions because the property under test is what the type
 * *says*, and a type that has been re-tightened compiles perfectly well until a
 * user hits the missing field in production.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(__dirname, '..');
const read = (...seg: string[]) => readFileSync(join(SRC, ...seg), 'utf8');

/**
 * Source with comments stripped. The fixes document themselves by quoting the
 * expression they replaced — `subscription.features.length`, `pos.direction
 * .toLowerCase()` — so a naive text search finds the bug in the very comment
 * explaining that it is gone.
 */
const readCode = (...seg: string[]) =>
  read(...seg)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

/** Extract a named interface body from a source file. */
function interfaceBody(src: string, name: string): string {
  const m = new RegExp(`interface\\s+${name}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(src);
  if (!m) throw new Error(`interface ${name} not found`);
  return m[1]!;
}

describe('API types describe what the server actually guarantees', () => {
  const trading = read('types', 'trading.ts');

  it.each([
    'balance', 'equity', 'daily_pnl', 'total_pnl',
    'win_rate', 'sharpe_ratio', 'max_drawdown', 'open_trades',
  ])('AccountMetrics.%s is optional', (field) => {
    const body = interfaceBody(trading, 'AccountMetrics');
    expect(body, `${field} must be optional — it is absent on a new account`).toMatch(
      new RegExp(`readonly\\s+${field}\\?:`),
    );
  });

  it.each([
    'total_return_pct', 'sharpe_ratio', 'sortino_ratio', 'max_drawdown_pct',
    'win_rate', 'profit_factor', 'total_trades', 'avg_trade_pnl',
    'best_trade', 'worst_trade', 'cvar_95',
  ])('PerformanceSummary.%s is optional', (field) => {
    const body = interfaceBody(trading, 'PerformanceSummary');
    expect(body, `${field} is derived from closed trades and absent before the first close`)
      .toMatch(new RegExp(`readonly\\s+${field}\\?:`));
  });

  it('Position carries both side and direction, both optional', () => {
    const body = interfaceBody(trading, 'Position');
    // Some endpoints return `direction` rather than `side`. Declaring `side`
    // required did not make the server send it.
    expect(body).toMatch(/readonly\s+side\?:/);
    expect(body).toMatch(/readonly\s+direction\?:/);
  });
});

describe('the crash vectors the audit named stay fixed', () => {
  it.each([
    ['Dashboard.tsx', /acc\.sharpe_ratio\.toFixed/, 'acc.sharpe_ratio.toFixed(2)'],
    ['PnLDashboard.tsx', /pos\.direction\.toLowerCase\(\)/, 'pos.direction.toLowerCase()'],
    ['Profile.tsx', /\(sig\.confidence\s*\*\s*100\)/, 'sig.confidence * 100'],
    ['PriceAlerts.tsx', /alert\.notification_channels\.join/, 'alert.notification_channels.join()'],
    ['PricingPage.tsx', /plan\.limits\.signals_per_day/, 'plan.limits.signals_per_day'],
    ['Wallet.tsx', /subscription\.features\.length/, 'subscription.features.length'],
  ])('%s no longer contains an unguarded %s', (file, pattern) => {
    expect(readCode('pages', file)).not.toMatch(pattern);
  });

  it('no crash site was silenced with a non-null assertion or a cast', () => {
    // `!` and `as` re-create the bug with extra steps: the compiler stops
    // complaining and the runtime still throws.
    const files = [
      ['pages', 'Dashboard.tsx'],
      ['components', 'terminal', 'AccountBar.tsx'],
      ['components', 'panels', 'RiskDashboard.tsx'],
    ] as const;

    for (const seg of files) {
      const src = readCode(...seg);
      for (const field of ['sharpe_ratio', 'win_rate', 'max_drawdown', 'balance', 'equity']) {
        expect(src, `${seg.join('/')} silences ${field} with ! instead of guarding it`)
          .not.toMatch(new RegExp(`\\.${field}!`));
        expect(src, `${seg.join('/')} casts ${field} instead of guarding it`)
          .not.toMatch(new RegExp(`${field}\\s+as\\s+number`));
      }
    }
  });
});

describe('positionSide normalises the side/direction split in one place', () => {
  it('is used rather than re-implemented at each call site', () => {
    // Four sites each wrote their own slightly different comparison against
    // 'long' / 'buy'. One of them crashed.
    for (const seg of [
      ['pages', 'PnLDashboard.tsx'],
      ['pages', 'Portfolio.tsx'],
      ['components', 'panels', 'PositionsTable.tsx'],
    ] as const) {
      expect(read(...seg), `${seg.join('/')} should use positionSide()`).toContain('positionSide');
    }
  });
});

describe('noUncheckedIndexedAccess stays on (#38)', () => {
  it('is enabled in tsconfig', () => {
    // Without it, `array[i]` is typed as always-defined, so `bins[idx]!.count`
    // reads as safe and non-null assertions pass review unchallenged. Turning it
    // back off would silently re-admit that whole class of bug — and the 100+
    // guards added alongside it would look like redundant noise to the next
    // reader.
    const tsconfig = readFileSync(join(__dirname, '..', '..', 'tsconfig.json'), 'utf8');
    expect(tsconfig).toMatch(/"noUncheckedIndexedAccess"\s*:\s*true/);
    expect(tsconfig).toMatch(/"strict"\s*:\s*true/);
  });

  it('production code does not silence index access with a non-null assertion', () => {
    // `!` is tolerated in test files, where the failure mode is a failing test.
    // In production it re-creates the crash with extra steps.
    const dirs = ['pages', 'components', 'lib', 'hooks', 'features', 'types'];
    const offenders: string[] = [];

    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) { walk(full); continue; }
        if (!/\.tsx?$/.test(entry.name)) continue;
        readFileSync(full, 'utf8')
          // Strip comments first: the fixes document themselves by quoting the
          // assertion they replaced.
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .replace(/^\s*\/\/.*$/gm, '')
          .split('\n')
          .forEach((line, i) => {
            // `something[expr]!` — a bang directly after an index access.
            if (/\[[^\]]*\]!/.test(line)) offenders.push(`${full}:${i + 1}  ${line.trim().slice(0, 90)}`);
          });
      }
    };
    for (const d of dirs) walk(join(SRC, d));

    expect(
      offenders,
      'Guard the access (?? fallback, bind-then-check, or a named constant) ' +
        'instead of asserting it is present:\n' + offenders.join('\n'),
    ).toEqual([]);
  });
});
