/**
 * The accessibility debt list must describe today's tree, and may only shrink.
 *
 * F172 — "icon-only buttons without an accessible name" — sat UNVERIFIED in the
 * correction register, and the reason is worth keeping: two attempts to measure
 * it by regex each produced a confident WRONG answer. One reported clean across
 * 552 buttons; the other found 9 files. A JSX opening tag cannot be bracketed by
 * a regex — an attribute may contain `>`, and `onClick={() => nav('/x')}` ends
 * the match at the arrow.
 *
 * A real parser answers it: **138 violations across 67 files**. Classified by
 * the same parser a day later, only ONE of those 138 is a button — input 108,
 * textarea 17, div 5, td 4, th 2, button 1, option 1 — so the entry's name
 * describes 1/138 of what it measures. See `a11y-debt.json`'s `_shape`.
 *
 * This file asserts that the LIST matches the tree. It cannot assert that a
 * cleared file is accessible: the rule going quiet and a screen reader getting
 * a name are different claims, and `auth_flow_controls_have_names.test.tsx`
 * makes the second one by rendering.
 *
 * `eslint.config.js` sets `jsx-a11y/control-has-associated-label` to `error`
 * everywhere and downgrades it to `warn` for exactly the files in
 * `a11y-debt.json`. So a violation in any unlisted file fails `npm run lint` —
 * new debt cannot arrive quietly — while the existing 67 do not wall off the
 * codebase.
 *
 * That leaves one hole a config cannot close: a file that gets FIXED keeps its
 * entry, and the entry is then a standing permission rather than a debt. This
 * test closes it, with the same rule the colour, emoji and model-provenance
 * ratchets use — an entry that no longer describes anything is how a ratchet
 * quietly stops being one.
 */

import { describe, it, expect } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');
const RULE = 'jsx-a11y/control-has-associated-label';

type Debt = { _total: number; files: Record<string, number> };

const debt: Debt = JSON.parse(readFileSync(resolve(ROOT, 'a11y-debt.json'), 'utf8'));

/** Violations per file, from eslint itself rather than from a pattern. */
function measure(): Record<string, number> {
  // spawnSync, not execFileSync: eslint exits non-zero whenever ANY rule
  // errors, and this tree carries 14 pre-existing errors from other rules. A
  // throwing call discarded the JSON on stdout and the test failed with
  // "Command failed" — a red for the wrong reason, which proves nothing about
  // the debt list.
  const run = spawnSync('npx', ['eslint', 'src', '-f', 'json'], {
    cwd: ROOT,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  const out = run.stdout;
  if (!out) {
    throw new Error(`eslint produced no JSON (status ${run.status}): ${run.stderr?.slice(0, 500)}`);
  }
  const counts: Record<string, number> = {};
  for (const result of JSON.parse(out)) {
    const n = result.messages.filter((m: { ruleId?: string }) => m.ruleId === RULE).length;
    if (n) counts[result.filePath.replace(`${ROOT}/`, '')] = n;
  }
  return counts;
}

/** How many files eslint actually examined. Zero means the scan broke. */
function linted(): number {
  const run = spawnSync('npx', ['eslint', 'src', '-f', 'json'], {
    cwd: ROOT,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (!run.stdout) return 0;
  return JSON.parse(run.stdout).length;
}

describe('a11y debt list — F172', () => {
  it('lists files that exist', () => {
    const gone = Object.keys(debt.files).filter((f) => !existsSync(resolve(ROOT, f)));
    expect(gone, `deleted files still listed in a11y-debt.json: ${gone.join(', ')}`).toEqual([]);
  });

  it('states a total that matches its own entries', () => {
    const summed = Object.values(debt.files).reduce((a, b) => a + b, 0);
    expect(summed).toBe(debt._total);
  });

  it('proves the scan ran, rather than that the debt is still large', { timeout: 180_000 }, () => {
    // This was a floor on the DEBT — "more than 40 files, more than 90
    // violations" — written when there were 138 of them to catch the failure
    // mode where a broken measurement reads as a clean tree, the way the
    // coverage gate once reported 361 clean modules it had never looked at.
    //
    // The intent was right and the expression was wrong: a floor on the debt
    // fails when the debt genuinely falls, which is the outcome the whole
    // ratchet exists to produce. It went red at 82 for exactly that reason.
    //
    // What it actually needs to assert is that the SCAN reached the tree. So
    // it counts what eslint looked at, not what it found — that number does
    // not shrink as the debt is paid, and it collapses to zero precisely when
    // the measurement breaks.
    expect(
      linted(),
      'eslint returned almost no files — the scan broke, and zero findings from a broken scan is indistinguishable from success',
    ).toBeGreaterThan(100);
  });

  it('matches what eslint finds, entry for entry', { timeout: 180_000 }, () => {
    const now = measure();

    // A file that reached zero must LEAVE the list. Left behind it is a
    // standing permission for the rule to be a warning there forever.
    const cleared = Object.keys(debt.files).filter((f) => !(f in now));
    expect(
      cleared,
      `these files have no violations left and must be deleted from a11y-debt.json: ${cleared.join(', ')}`,
    ).toEqual([]);

    // A file whose count ROSE is new debt inside an existing entry — invisible
    // to eslint, because the whole file is already downgraded to a warning.
    // `debt.files[f]` is `number | undefined` under noUncheckedIndexedAccess,
    // so it is bound once rather than indexed twice.
    const grew = Object.entries(now)
      .map(([f, n]) => ({ f, n, was: debt.files[f] }))
      .filter(({ n, was }) => was !== undefined && n > was)
      .map(({ f, n, was }) => `${f}: ${n}, was ${was}`);
    expect(grew, `violations increased in a file already on the debt list:\n  ${grew.join('\n  ')}`).toEqual([]);

    // And a file NOT on the list must have none — this one eslint also catches
    // as an error, asserted here so the failure names the file either way.
    const brandNew = Object.keys(now).filter((f) => !(f in debt.files));
    expect(brandNew, `new files with a11y violations: ${brandNew.join(', ')}`).toEqual([]);
  });
});
