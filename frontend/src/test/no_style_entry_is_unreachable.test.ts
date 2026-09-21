/**
 * A style entry nothing reads is a size the density control will never reach
 * and nobody can retire.
 *
 * Found while assigning the new display tier. Two of the thirteen sites sizing
 * type turned out to be `title: { fontSize: 28 }` entries in a page's own style
 * object, with no reader: both pages moved to `PageShell`, which renders the
 * header from a `title` PROP, and the style objects they used to use were left
 * behind. `scripts/frontend_size_ratchet.py` counted them as debt to convert,
 * and converting them would have put a token on something that never renders —
 * the same shape as `superadmin/ui.tsx::EmptyState`, which carried a
 * `fontSize: 32` sizing an SVG.
 *
 * Deliberately narrow: the two pages this was proved on. A tree-wide version
 * would be a lint rule, and one that has never been run against 168 files is a
 * rule that lands as a hundred failures and gets disabled.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Top-level keys of `const <name> = { ... }`, and the body's span. */
function styleObject(src: string, name: string): { keys: string[]; from: number; to: number } {
  const at = src.search(new RegExp(`^const ${name}(?::[^=]+)?\\s*=\\s*\\{`, 'm'));
  if (at === -1) throw new Error(`no style object named ${name}`);
  const open = src.indexOf('{', at);
  let depth = 0;
  let end = -1;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = src.slice(open + 1, end);
  const keys: string[] = [];
  let d = 0;
  for (const line of body.split('\n')) {
    if (d === 0) {
      const m = /^\s*([A-Za-z_$][\w$]*)\s*:/.exec(line);
      if (m) keys.push(m[1]!);
    }
    for (const ch of line) {
      if (ch === '{' || ch === '[' || ch === '(') d += 1;
      else if (ch === '}' || ch === ']' || ch === ')') d -= 1;
    }
  }
  return { keys, from: open, to: end };
}

describe.each([
  ['pages/WalkForward.tsx', 's'],
  ['pages/CustomIndicators.tsx', 's'],
])('%s', (rel, name) => {
  it(`has no entry in \`${name}\` that nothing reads`, () => {
    const src = readFileSync(resolve(__dirname, '..', rel), 'utf8');
    const { keys, from, to } = styleObject(src, name);
    const outside = src.slice(0, from) + src.slice(to);
    const orphans = keys.filter((k) => !new RegExp(`[.\\['"]${k}\\b`).test(outside));
    expect(orphans, `${rel}: \`${name}\` declares ${orphans.join(', ')} and nothing reads them`).toEqual([]);
  });
});
