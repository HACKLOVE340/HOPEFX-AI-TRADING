/**
 * An `aria-labelledby` that names an id nothing renders is not a label.
 *
 * It is the strongest source in the accessible-name algorithm — it beats a
 * `<label for>`, a `title` and the element's own text — so pointing it at
 * nothing is worse than leaving it off: the control it was meant to name is the
 * one whose name is now in question.
 *
 * Found while verifying a pass that added 74 of these correctly. The 75th was
 * pre-existing: `RiskCalculator`'s symbol select carries `id="risk-symbol"` and
 * a matching `<Label htmlFor="risk-symbol">`, and then an
 * `aria-labelledby="risk-symbol-label"` for an element that has never existed.
 * `eslint-plugin-jsx-a11y` does not resolve ids across a file, so nothing had
 * ever checked one.
 *
 * Source-level and whole-tree: these ids are static strings, and rendering
 * every page that has a form is a suite, not a test.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const SRC = resolve(__dirname, '..');

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === 'test' ? [] : walk(full);
    return full.endsWith('.tsx') ? [full] : [];
  });
}

describe('aria-labelledby', () => {
  it('never names an id the same file does not render', () => {
    const dangling: string[] = [];
    let checked = 0;

    for (const file of walk(SRC)) {
      const text = readFileSync(file, 'utf8');
      for (const m of text.matchAll(/aria-labelledby=(?:"([^"]+)"|\{`([^`]+)`\})/g)) {
        checked += 1;
        const raw = (m[1] ?? m[2])!;
        // A templated id — `journal-notes-${id}-label` — is checked by its
        // literal stem, which is as far as a static reading can go.
        const needle = raw.includes('${') ? raw.split('${')[0]! : raw;
        const rendered =
          text.includes(`id="${needle}`) || text.includes(`id='${needle}`) || text.includes(`id={\`${needle}`);
        if (!rendered) dangling.push(`${file.split('/src/')[1]}: ${raw}`);
      }
    }

    // The sanity floor: a walk that stopped matching would report none.
    expect(checked).toBeGreaterThan(50);
    expect(dangling, `these name an id nothing renders:\n${dangling.join('\n')}`).toEqual([]);
  });
});
