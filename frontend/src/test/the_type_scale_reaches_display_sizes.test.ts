/**
 * The scale stops at `--fs-hero`, and the tree does not.
 *
 * `--fs-hero` is 26px at `ultra` — the tier `densityPref.ts` gives a person by
 * default. 44 inline sizes sit above it, and the obvious move was to extend the
 * scale so `frontend_size_codemod.py` could convert them all. Measuring first
 * said no: 31 of the 44 are sizing an EMOJI, where `fontSize` is the only lever
 * a glyph has, and each one disappears when `frontend_emoji_ratchet.py` turns
 * it into an SVG sized by `width`/`height`. A token minted to reach those would
 * be design-system API for debt already scheduled for deletion.
 *
 * 13 were sizing type. Two of those turned out to be dead style entries —
 * `title` and `subtitle` objects left behind when the page moved to `PageShell`
 * — so 11 sites, one of which is `--fs-hero` at 28px and always was.
 *
 * That is what these three tokens are for, and the number is the argument for
 * three rather than one: the sites cluster at 32, 36 and 48, and collapsing
 * them into one step would move six of them at the default density to save two
 * declarations.
 *
 * The guarantee this file holds is the same one the codemod makes: **the ultra
 * value is byte-identical to the literal it replaces**, so adopting the token
 * changes nothing at the tier a person actually gets, and the other two tiers
 * gain a control they did not have. Retuning is allowed; retuning SILENTLY is
 * what this stops.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const CSS = readFileSync(resolve(__dirname, '../index.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, ' ');

/**
 * Index of the rule whose selector LIST contains `selector` as a whole item.
 *
 * `:root` gained a second selector -- `:root, [data-theme="dark"]` -- so a
 * subtree can ask for the dark palette while the document is light. A bare
 * `indexOf(':root {')` stopped finding it and this file reported the type
 * scale as missing, with NaN comparisons that read as a broken scale rather
 * than a broken parser. Same defect, same day, as the one in
 * design_tokens.test.ts.
 */
function ruleStart(selector: string): number {
  let from = 0;
  for (;;) {
    const at = CSS.indexOf(selector, from);
    if (at === -1) return -1;
    const open = CSS.indexOf('{', at);
    if (open === -1) return -1;
    const prev = Math.max(CSS.lastIndexOf('}', at), CSS.lastIndexOf(';', at));
    if (CSS.slice(prev + 1, open).split(',').some((part) => part.trim() === selector.trim())) return at;
    from = at + selector.length;
  }
}

function block(selector: string): string {
  const at = ruleStart(selector);
  if (at === -1) throw new Error(`no rule for ${selector} in index.css`);
  const open = CSS.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < CSS.length; i += 1) {
    if (CSS[i] === '{') depth += 1;
    else if (CSS[i] === '}') {
      depth -= 1;
      if (depth === 0) return CSS.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced block for ${selector}`);
}

function declared(body: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out.set(m[1]!, m[2]!.trim());
  return out;
}

const root = declared(block(':root'));
const promax = declared(block('[data-density="promax"]'));
const ultra = declared(block('[data-density="ultra"]'));
const comfortable = declared(block('[data-density="comfortable"]'));

const DISPLAY = ['--fs-display-sm', '--fs-display', '--fs-display-lg'] as const;
const px = (m: Map<string, string>, k: string) => parseFloat(m.get(k)!);

describe('the display tier', () => {
  it('is declared in the default block and in all three tiers', () => {
    for (const [name, tier] of [
      [':root', root],
      ['promax', promax],
      ['ultra', ultra],
      ['comfortable', comfortable],
    ] as const) {
      const missing = DISPLAY.filter((t) => !tier.has(t));
      expect(missing, `${name} is missing ${missing.join(', ')}`).toEqual([]);
    }
  });

  it('is byte-identical at ultra to the literals it replaces', () => {
    // 32, 36 and 48 are what the eleven sites were written as. If these move,
    // the adoption stops being invisible at the default density and the eleven
    // sites need looking at again — which is a decision, not a retune.
    expect(ultra.get('--fs-display-sm')).toBe('32px');
    expect(ultra.get('--fs-display')).toBe('36px');
    expect(ultra.get('--fs-display-lg')).toBe('48px');
  });

  it('continues the scale rather than restarting it', () => {
    for (const [name, tier] of [
      [':root', root],
      ['promax', promax],
      ['ultra', ultra],
      ['comfortable', comfortable],
    ] as const) {
      const steps = ['--fs-head', '--fs-hero', ...DISPLAY];
      const sizes = steps.map((s) => px(tier, s));
      for (let i = 1; i < sizes.length; i += 1) {
        expect(sizes[i], `${name}: ${steps[i]} (${sizes[i]}px) must exceed ${steps[i - 1]} (${sizes[i - 1]}px)`).toBeGreaterThan(
          sizes[i - 1]!,
        );
      }
    }
  });

  it('orders the tiers the same way the rest of the scale does', () => {
    for (const token of DISPLAY) {
      expect(px(ultra, token), `${token} must be tightest at ultra`).toBeLessThan(px(promax, token));
      expect(px(comfortable, token), `${token} must be loosest at comfortable`).toBeGreaterThan(px(promax, token));
    }
  });

  it('does not restate a size the scale already has', () => {
    // Two names for one size is how the tree got 24 distinct sizes. Checked at
    // every tier, because a collision can appear in one tier alone.
    for (const [name, tier] of [
      [':root', root],
      ['promax', promax],
      ['ultra', ultra],
      ['comfortable', comfortable],
    ] as const) {
      const scale = ['--fs-micro', '--fs-label', '--fs-body', '--fs-value', '--fs-title', '--fs-head', '--fs-hero', ...DISPLAY];
      const sizes = scale.map((s) => px(tier, s));
      expect(new Set(sizes).size, `${name} declares a duplicate size: ${sizes.join(', ')}`).toBe(scale.length);
    }
  });
});
