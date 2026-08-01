/**
 * Nav / route contract.
 *
 * Three separate lists have to agree — the routes registered in App.tsx, the
 * feature keys passed to gated(), and PLAN_FEATURES — and nothing checked that
 * they did. The audit found the consequences: Leaderboard linked to
 * `/trader/:id`, which is not a route at all (`/profile/:id` is), and `/docs`
 * was registered twice, the outer copy shadowing the AppShell one so logged-in
 * users never got the sidebar version its comment promised.
 *
 * These read App.tsx as text on purpose. Rendering the router would need the
 * whole app; the goal here is to catch a link or a gate that points at nothing,
 * which is a property of the source.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { PLAN_FEATURES } from '../lib/subscription';

const SRC = join(__dirname, '..');
const APP_TSX = readFileSync(join(SRC, 'App.tsx'), 'utf8');

/** Every `path="..."` registered in App.tsx. */
function registeredPaths(): string[] {
  return [...APP_TSX.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]!);
}

/** Every `gated('key', …)` feature key used in App.tsx. */
function gatedFeatureKeys(): string[] {
  return [...APP_TSX.matchAll(/gated\(\s*'([^']+)'/g)].map((m) => m[1]!);
}

/** Static internal link targets across the pages tree, ignoring template vars. */
function internalLinkTargets(): Array<{ file: string; to: string }> {
  const out: Array<{ file: string; to: string }> = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) { walk(full); continue; }
      if (!entry.name.endsWith('.tsx')) continue;
      const src = readFileSync(full, 'utf8');
      // `to="/x"` and navigate('/x') — literal paths only.
      for (const m of src.matchAll(/(?:to=|navigate\()\s*['"](\/[a-z0-9\-/]*)['"]/gi)) {
        out.push({ file: entry.name, to: m[1]! });
      }
      // Template literals: capture the leading static segment, e.g. `/profile/${id}`.
      for (const m of src.matchAll(/(?:to=\{|navigate\()\s*`(\/[a-z0-9\-]+)\/\$\{/gi)) {
        out.push({ file: entry.name, to: `${m[1]!}/:param` });
      }
    }
  };
  walk(join(SRC, 'pages'));
  return out;
}

describe('routes', () => {
  it('registers each path exactly once', () => {
    const counts = new Map<string, number>();
    for (const p of registeredPaths()) counts.set(p, (counts.get(p) ?? 0) + 1);

    const duplicates = [...counts.entries()].filter(([, n]) => n > 1).map(([p]) => p);
    expect(
      duplicates,
      'A path registered twice is matched by whichever <Routes> group comes ' +
        'first; the other registration is dead code that looks live.',
    ).toEqual([]);
  });
});

describe('feature gates', () => {
  it('every gated() key has an entry in PLAN_FEATURES', () => {
    const missing = gatedFeatureKeys().filter((k) => !(k in PLAN_FEATURES));
    expect(
      missing,
      'An unlisted key silently falls through to free, so a paid feature ' +
        'becomes free without anyone changing a plan.',
    ).toEqual([]);
  });
});

describe('internal links', () => {
  it('point at registered routes', () => {
    const paths = registeredPaths();
    const staticPaths = new Set(paths.filter((p) => !p.includes(':') && !p.includes('*')));
    // '/profile/:id' → prefix '/profile'
    const paramPrefixes = new Set(
      paths.filter((p) => p.includes(':')).map((p) => p.slice(0, p.indexOf('/:'))),
    );

    const broken = internalLinkTargets().filter(({ to }) => {
      if (to === '/' || to === '') return false;
      if (staticPaths.has(to)) return false;
      if (to.endsWith('/:param')) return !paramPrefixes.has(to.slice(0, -'/:param'.length));
      // Nested static path under a registered parent, e.g. /settings/foo.
      return ![...staticPaths].some((p) => p !== '/' && to.startsWith(`${p}/`));
    });

    expect(
      broken.map(({ file, to }) => `${file} → ${to}`),
      'These links resolve to the catch-all, which sends anonymous visitors to ' +
        '/login and authenticated ones to 404.',
    ).toEqual([]);
  });
});
