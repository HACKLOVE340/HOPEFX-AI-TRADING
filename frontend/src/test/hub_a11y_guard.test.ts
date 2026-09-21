/**
 * Phase G — §27, the half that is a mechanism rather than a fix.
 *
 * `hub_a11y.test.ts` checks that the accessibility contract behaves. This file
 * checks that `hub/` still USES it — by reading the source, the way
 * `tests/unit/ai/test_bus_imports_nothing_executable.py` reads the bus package
 * rather than trusting its docstring.
 *
 * Every rule below corresponds to a defect that actually shipped in this
 * session's own work and was caught by reading a diff:
 *
 *   1. no focus ring on the presence overlay
 *   2. a 22px dismiss control
 *   3. `text-slate-500` on a surface where it measures below 4.5:1
 *   4. a second polite live region competing with PresenceCore's
 *
 * Reading a diff is not a mechanism. This is.
 *
 * ## Why source scanning and not a rendered assertion
 *
 * A rendered test proves the component under test. It proves nothing about the
 * next component, which is the one that will repeat the defect. These rules
 * hold across the whole directory, including files that do not exist yet.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { MIN_TARGET_PX } from '../hub/a11yFocus';
import { BREAKPOINTS } from '../hub/a11yBreakpoints';
import { FORBIDDEN_TEXT } from '../hub/a11yContrast';

const HUB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'hub');

/** Where each shared constant is allowed to be declared. */
const OWNERS = {
  focus: 'a11yFocus.ts',
  breakpoints: 'a11yBreakpoints.ts',
  contrast: 'a11yContrast.ts',
  liveRegion: 'a11yLiveRegion.ts',
} as const;

interface SourceFile {
  name: string;
  text: string;
}

function hubSources(extensions: readonly string[]): SourceFile[] {
  return fs
    .readdirSync(HUB)
    .filter((name) => extensions.some((ext) => name.endsWith(ext)))
    .map((name) => ({ name, text: fs.readFileSync(path.join(HUB, name), 'utf8') }));
}

/**
 * Strip block comments and line comments.
 *
 * Without this the rules ban the words their own docstrings use to explain
 * themselves — a mistake made twice already in this session, once in
 * `ai/bus/` and once in `ai/improve/`, and both times the fix was to look at
 * structure instead of text.
 */
function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

/** Every `<button ...>` opening tag in a TSX file, comments removed. */
function buttonTags(text: string): string[] {
  const out: string[] = [];
  const source = withoutComments(text);
  let from = 0;
  for (;;) {
    const start = source.indexOf('<button', from);
    if (start === -1) break;
    // Walk to the end of the opening tag, skipping `>` inside braces and
    // strings — arrow functions in handlers contain both.
    let depth = 0;
    let quote = '';
    let i = start;
    for (; i < source.length; i += 1) {
      const c = source[i];
      if (quote) {
        if (c === quote) quote = '';
        continue;
      }
      if (c === '"' || c === "'" || c === '`') quote = c;
      else if (c === '{') depth += 1;
      else if (c === '}') depth -= 1;
      else if (c === '>' && depth === 0) break;
    }
    out.push(source.slice(start, i + 1));
    from = i + 1;
  }
  return out;
}

const TSX = hubSources(['.tsx']);
const ALL = hubSources(['.ts', '.tsx']);

describe('§27 guard — the focus ring and hit area are declared once', () => {
  it.each([
    ['FOCUS_RING', OWNERS.focus],
    ['HIT_AREA', OWNERS.focus],
    ['MIN_HIT_AREA_PX', OWNERS.focus],
    ['MIN_TARGET_PX', OWNERS.focus],
  ])('%s is declared only in %s', (name, owner) => {
    const declarers = ALL.filter((f) => new RegExp(`^\\s*(export\\s+)?const ${name}\\b`, 'm').test(f.text)).map(
      (f) => f.name,
    );
    expect(declarers).toEqual([owner]);
  });

  it('every classed button in hub carries both', () => {
    const offenders: string[] = [];
    for (const file of TSX) {
      for (const tag of buttonTags(file.text)) {
        // Inline-styled buttons are checked by the pixel rule below instead;
        // a Tailwind class list is what these two constants are written in.
        if (!tag.includes('className')) continue;
        if (!tag.includes('FOCUS_RING')) offenders.push(`${file.name}: a classed button with no FOCUS_RING`);
        if (!tag.includes('HIT_AREA')) offenders.push(`${file.name}: a classed button with no HIT_AREA`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('finds buttons at all, so the rule above cannot pass vacuously', () => {
    // The scanner is the thing most likely to break silently: a change to how
    // these components are written would make it match nothing and report
    // clean. It has to see the ones that exist today.
    const classed = TSX.flatMap((f) => buttonTags(f.text)).filter((t) => t.includes('className'));
    expect(classed.length).toBeGreaterThanOrEqual(4);
    expect(TSX.flatMap((f) => buttonTags(f.text)).length).toBeGreaterThanOrEqual(12);
  });
});

/**
 * Pixel dimensions a button gets, whether written in its own tag or spread in
 * from a shared style object.
 *
 * The first version of this rule read only the tag. It passed, and it was
 * wrong: `SurfaceView`'s icon buttons take their 26px from a `const iconBtn`
 * declared at the top of the file, and every dimension in the codebase that
 * could plausibly be too small is written that way. A rule that only sees the
 * inline case reports clean on the files most likely to be at fault — which is
 * `hopefx-dead-controls` in a test rather than in production.
 */
function buttonDimensions(file: SourceFile): { source: string; property: string; px: number }[] {
  const text = withoutComments(file.text);
  const found: { source: string; property: string; px: number }[] = [];

  const record = (source: string, block: string) => {
    for (const match of block.matchAll(/\b(minHeight|minWidth|height|width)\s*:\s*(\d+)\b/g)) {
      found.push({ source, property: match[1]!, px: Number(match[2]) });
    }
  };

  for (const tag of buttonTags(file.text)) {
    record('inline', tag);
    // `style={{ ...iconBtn, height: 26 }}` — follow the spread to its
    // declaration and measure that too.
    for (const spread of tag.matchAll(/\.\.\.(\w+)/g)) {
      const name = spread[1]!;
      const declaration = new RegExp(`const ${name}\\s*(:[^=]*)?=\\s*\\{([\\s\\S]*?)\\n\\};`, 'm').exec(text);
      if (declaration) record(name, declaration[2]!);
    }
  }
  return found;
}

describe('§27 guard — no hit target below the floor', () => {
  it('every pixel dimension a hub button receives clears it', () => {
    const offenders: string[] = [];
    for (const file of TSX) {
      for (const { source, property, px } of buttonDimensions(file)) {
        if (px < MIN_TARGET_PX) {
          offenders.push(
            `${file.name}: a button gets ${property}: ${px} from ${source}, below the ${MIN_TARGET_PX}px floor`,
          );
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('reaches the shared style objects, not only the inline ones', () => {
    // Without this the rule above passes by measuring nothing on exactly the
    // files where the dimensions live in a shared const.
    const surfaceView = TSX.find((f) => f.name === 'SurfaceView.tsx');
    expect(surfaceView).toBeDefined();
    const sources = new Set(buttonDimensions(surfaceView!).map((d) => d.source));
    expect(sources.has('iconBtn')).toBe(true);
  });
});

describe('§27 guard — the outline is never removed without a replacement', () => {
  it('holds across every hub module', () => {
    const offenders: string[] = [];
    for (const file of ALL) {
      const source = withoutComments(file.text);
      // Tailwind: `outline-none` must appear in a string that also names the
      // ring replacing it.
      for (const line of source.split('\n')) {
        if (line.includes('outline-none') && !line.includes('ring-')) {
          offenders.push(`${file.name}: outline-none with no ring on the same line`);
        }
        if (/outline\s*:\s*(['"`])?\s*(none|0)\b/.test(line)) {
          offenders.push(`${file.name}: outline set to none in a style object, which no :focus-visible can restore`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('§27 guard — one polite live region in the whole hub', () => {
  it('counts the aria-live attributes', () => {
    const regions = TSX.flatMap((f) =>
      [...withoutComments(f.text).matchAll(/aria-live\s*=\s*["'{]?\s*["']?(polite|assertive)/g)].map((m) => ({
        file: f.name,
        politeness: m[1],
      })),
    );
    const polite = regions.filter((r) => r.politeness === 'polite');
    expect(polite.map((r) => r.file)).toEqual(['PresenceCore.tsx']);
  });

  it('the component that renders one claims it by name', () => {
    // A region rendered without a claim is the defect with the registry
    // installed but not used — which reads, in a coverage count, as fixed.
    const core = TSX.find((f) => f.name === 'PresenceCore.tsx');
    expect(core).toBeDefined();
    expect(core!.text).toContain("liveRegions.claim('polite', 'PresenceCore')");
    expect(core!.text).toContain("liveRegions.release('polite', 'PresenceCore')");

    const overlay = TSX.find((f) => f.name === 'PresenceAnywhere.tsx');
    expect(overlay).toBeDefined();
    expect(overlay!.text).toContain("liveRegions.claim('assertive', 'PresenceAnywhere')");
  });
});

describe('§27 guard — one definition of every breakpoint', () => {
  it('no other hub module holds a viewport literal', () => {
    const literals = Object.values(BREAKPOINTS);
    const offenders: string[] = [];
    for (const file of ALL) {
      if (file.name === OWNERS.breakpoints) continue;
      const source = withoutComments(file.text);
      for (const px of literals) {
        // A viewport breakpoint is a number ASSIGNED to a constant. A `640`
        // inside a canvas size or a timing value is not one, so the rule looks
        // for the declaration shape rather than the digits anywhere.
        if (new RegExp(`^\\s*(export\\s+)?const\\s+\\w+\\s*(:[^=]+)?=\\s*${px}\\s*;`, 'm').test(source)) {
          offenders.push(`${file.name}: declares ${px} itself instead of importing BREAKPOINTS`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('the three modules that used to hold their own now import it', () => {
    for (const name of ['layout.ts', 'layoutStrategy.ts', 'presenceDock.ts']) {
      const file = ALL.find((f) => f.name === name);
      expect(file, name).toBeDefined();
      expect(file!.text, name).toContain("from './a11yBreakpoints'");
    }
  });
});

describe('§27 guard — the refused colours stay refused', () => {
  it('no hub module uses one as a text colour', () => {
    const offenders: string[] = [];
    for (const file of ALL) {
      if (file.name === OWNERS.contrast) continue;
      const source = withoutComments(file.text);
      for (const [token, entry] of Object.entries(FORBIDDEN_TEXT)) {
        if (source.includes(token)) offenders.push(`${file.name}: uses ${token} (${entry.reason})`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
