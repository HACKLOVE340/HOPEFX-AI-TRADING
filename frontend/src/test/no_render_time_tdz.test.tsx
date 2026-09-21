/**
 * src/test/no_render_time_tdz.test.tsx
 * ====================================
 * Project-wide guard against the Watchlist crash class.
 *
 * `Watchlist.tsx` read `tickHistory` inside a render-time `.map()` callback
 * ~24 lines above `const [tickHistory, setTickHistory] = useState({})`. That is
 * a temporal dead zone violation, and it threw
 * `Cannot access 'N' before initialization` — a blank page for every user whose
 * watchlist was not empty and whose feed was live.
 *
 * It reached production because nothing in this repo could see it:
 *
 *  * `tsc` raises TS2448 only for a direct reference in the same scope. The
 *    read was inside a callback, whose call time TypeScript will not assume, so
 *    `npm run typecheck` and `npm run build` were both green.
 *  * There is no ESLint config in this project — `no-use-before-define` has
 *    never run here.
 *  * Ten Watchlist tests existed. All rendered an empty list against a dead
 *    feed, and the throwing line sits behind `if (!feedLive) return item;`
 *    inside `items.map(...)`, so none of them could reach it.
 *
 * `scripts/find_tdz_reads.mjs` closes that gap. This test runs it in CI.
 */

import { describe, it, expect } from 'vitest';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';
import { scan } from '../../scripts/find_tdz_reads.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..');
const FIXTURES = join(HERE, '..', '..', 'scripts', '__fixtures__', 'tdz');

describe('no variable is read before its declaration during render', () => {
  it('finds none in src/', () => {
    const findings = scan(SRC);
    const report = findings
      .map((f) => `  ${relative(SRC, f.file)}:${f.readLine} reads '${f.name}', declared at line ${f.declLine}`)
      .join('\n');

    expect(findings, `render-time temporal dead zone read(s):\n${report}`).toEqual([]);
  });
});

describe('the checker is not blind', () => {
  // A clean report means nothing unless the checker can still fail. These two
  // fixtures are the checker's own regression tests: Bad.tsx is the exact shape
  // that shipped, Good.tsx is every legal pattern that the first version of the
  // checker wrongly flagged.

  it('reports the shape that shipped in Watchlist.tsx', () => {
    const findings = scan(FIXTURES).filter((f) => f.file.endsWith('Bad.tsx'));
    expect(findings).toHaveLength(1);
    expect(findings[0]?.name).toBe('tickHistory');
    expect(findings[0]?.readLine).toBeLessThan(findings[0]?.declLine ?? 0);
  });

  it('clears the legal patterns it used to report', () => {
    // Handlers closing over a later const, names in type positions, and
    // block-shadowed bindings are all legal. Each was a false positive once.
    const findings = scan(FIXTURES).filter((f) => f.file.endsWith('Good.tsx'));
    expect(findings).toEqual([]);
  });
});
