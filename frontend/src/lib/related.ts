/**
 * Where to go next, derived rather than hand-authored.
 *
 * 40 of 74 pages end in nothing: no outbound link anywhere in the content
 * area, so a reader who lands on one can only leave by the sidebar. That is
 * what makes a large product feel like a set of unconnected screens — each
 * page is a cul-de-sac, and the only way to discover the page that answers
 * your next question is to already know its name.
 *
 * Writing 74 lists by hand would fix it once and rot immediately: a new page
 * appears in nobody's list, and a renamed one leaves a broken link behind.
 * So the relationships come from `navConfig.ts`, which already knows what
 * exists, who owns it and what unlocks it:
 *
 *   1. the page's own hub, so there is always a way back up;
 *   2. its siblings — the pages that answer adjacent questions;
 *   3. the explicit extras a page passes, which take priority because a
 *      hand-picked link is a statement about meaning and a derived one is a
 *      statement about filing.
 *
 * Siblings are capped and rotated by the current path rather than always
 * showing the first three, so a hub of fifteen does not surface the same
 * three on all fifteen of its pages.
 */

import { HUBS, NAV_ITEMS } from '../components/sidebar/navConfig';
import { NAV_DESCRIPTIONS } from '../components/sidebar/navDescriptions';
import type { RelatedLink } from '../components/RelatedPages';

/** How many derived links to show. Three fills one row and reads as a choice. */
const SIBLINGS = 3;

function toLink(path: string, label: string, icon?: RelatedLink['icon']): RelatedLink {
  return {
    to: path,
    label,
    // The hint is the reason to click. Falling back to the label would restate
    // it, which is the sidebar's problem again in a different place.
    hint: NAV_DESCRIPTIONS[path] ?? 'Open this page.',
    icon,
  };
}

export function relatedFor(pathname: string, extra: readonly RelatedLink[] = []): RelatedLink[] {
  const out: RelatedLink[] = [...extra];
  const seen = new Set<string>([pathname, ...out.map((l) => l.to)]);

  /**
   * The nav item this path belongs to.
   *
   * Longest prefix, not exact match. A detail page like `/positions/P-8841`
   * is in no nav item and never will be, and an exact match left it deriving
   * nothing — so the one kind of page most likely to be a leaf was the one
   * kind that stayed a dead end. Prefix matching gives it its parent's
   * neighbourhood.
   */
  const self = NAV_ITEMS.filter(
    (i) => pathname === i.path || pathname.startsWith(`${i.path}/`),
  ).sort((a, b) => b.path.length - a.path.length)[0];

  // 1. The way back up. A page inside a hub should never be a one-way trip.
  if (self?.hub) {
    const hub = HUBS.find((h) => h.id === self.hub);
    if (hub && !seen.has(hub.path)) {
      out.push({ to: hub.path, label: `All ${hub.label.toLowerCase()}`, hint: hub.description, icon: hub.icon });
      seen.add(hub.path);
    }
  }

  // 2. Siblings. Rotated by where we are, so a hub of fifteen does not show
  //    the same three pages on every one of them.
  const pool = NAV_ITEMS.filter(
    (i) =>
      !seen.has(i.path) &&
      !i.adminOnly &&
      !i.superAdminOnly &&
      (self?.hub ? i.hub === self.hub : i.group === self?.group),
  );

  if (pool.length > 0) {
    const start = Math.abs(hash(pathname)) % pool.length;
    for (let n = 0; n < pool.length && out.length < SIBLINGS + extra.length + 1; n += 1) {
      // Bound-then-check rather than a non-null assertion: the repo's type
      // contract (#38) keeps noUncheckedIndexedAccess honest, and an index
      // that "cannot" be out of range is exactly the one that is after a
      // later edit changes the loop bound.
      const item = pool[(start + n) % pool.length];
      if (!item || seen.has(item.path)) continue;
      out.push(toLink(item.path, item.label, item.icon));
      seen.add(item.path);
    }
  }

  /**
   * Nothing matched: a page outside the nav tree entirely.
   *
   * The hubs are always a correct answer — they are the top of every branch —
   * and "somewhere sensible" beats the cul-de-sac this whole module exists to
   * remove. Admin hubs are excluded because most readers cannot open them.
   */
  if (out.length === 0) {
    for (const hub of HUBS) {
      if (hub.adminOnly || seen.has(hub.path)) continue;
      out.push({ to: hub.path, label: hub.label, hint: hub.description, icon: hub.icon });
    }
  }

  return out;
}

/** Stable across reloads, so a page's footer does not reshuffle on refresh. */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
