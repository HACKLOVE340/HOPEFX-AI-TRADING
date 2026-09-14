/**
 * Collapsing the sidebar must not lose a single destination.
 *
 * The column listed 61 items and now lists 14; the other 47 moved onto five
 * hub pages. That is a navigation change, not a deletion — every route is
 * untouched and every page still exists. The failure mode is quiet: an item
 * tagged with a hub that has no page, or a hub whose route was never
 * registered, disappears from the sidebar and appears nowhere else, and
 * nothing errors. The page simply becomes unreachable by clicking, and stays
 * that way until a user complains.
 *
 * So this asserts reachability as an invariant rather than trusting the tags:
 * every nav item is either in the column or on exactly one hub page, every hub
 * has a real route, and search still reaches all 61 — because collapsing the
 * column must not make anything harder to find for someone who knows its name.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  NAV_ITEMS,
  NAV_GROUPS,
  HUBS,
  topLevelItems,
  itemsInHub,
  hubByPath,
  type HubId,
} from '../components/sidebar/navConfig';

const APP = readFileSync(resolve(__dirname, '../App.tsx'), 'utf8');
const HUB_PAGE = readFileSync(
  resolve(__dirname, '../components/sidebar/navDescriptions.ts'),
  'utf8',
);

const routePaths = new Set(
  [...APP.matchAll(/path="(\/[^"]*)"/g)].map((m) => m[1]!.split('/:')[0]!),
);

describe('navigation reachability', () => {
  it('still knows about every destination it ever had', () => {
    // The column shrank; the config did not. If this number falls, an item was
    // deleted rather than moved, and the commit that did it should say so.
    expect(NAV_ITEMS.length).toBeGreaterThanOrEqual(61);
  });

  it('puts every item either in the column or on exactly one hub', () => {
    const top = new Set(topLevelItems().map((i) => i.path));
    const onHub = new Map<string, HubId[]>();
    for (const hub of HUBS) {
      for (const item of itemsInHub(hub.id)) {
        onHub.set(item.path, [...(onHub.get(item.path) ?? []), hub.id]);
      }
    }

    const orphans = NAV_ITEMS.filter((i) => !top.has(i.path) && !onHub.has(i.path));
    expect(
      orphans.map((o) => `${o.label} (${o.path})`),
      'these pages are in no sidebar column and on no hub — unreachable by clicking',
    ).toEqual([]);

    const doubled = [...onHub.entries()].filter(([, hubs]) => hubs.length > 1);
    expect(doubled, 'an item on two hubs appears twice and belongs to neither').toEqual([]);
  });

  it('keeps the column short enough to be navigation rather than an index', () => {
    const shown = topLevelItems().length + HUBS.length;
    expect(shown).toBeLessThanOrEqual(20);
    expect(shown).toBeGreaterThan(8);
  });

  it('registers a route for every hub', () => {
    for (const hub of HUBS) {
      expect(routePaths.has(hub.path), `${hub.label} has no <Route path="${hub.path}">`).toBe(true);
      expect(hubByPath(hub.path)?.id).toBe(hub.id);
    }
  });

  it('points every hub at a group the sidebar renders', () => {
    const groups = new Set(NAV_GROUPS.map((g) => g.id));
    for (const hub of HUBS) {
      expect(groups.has(hub.group), `${hub.label} is in group "${hub.group}", which no group renders`).toBe(true);
    }
  });

  it('describes every hubbed page, because a label alone was the old problem', () => {
    // "TCA" and "Walk-Forward" were navigable only by people who already knew
    // what they were. A hub has room for the sentence; a missing one silently
    // falls back to "Open this page", which is the sidebar's problem again.
    const described = new Set(
      [...HUB_PAGE.matchAll(/'(\/[a-z0-9-]+)':\s*'/g)].map((m) => m[1]!),
    );
    const undescribed = NAV_ITEMS.filter((i) => i.hub && !described.has(i.path));
    expect(
      undescribed.map((u) => `${u.label} (${u.path})`),
      'hubbed pages with no description in Hub.tsx',
    ).toEqual([]);
  });

  it('leaves search reaching everything the column no longer lists', () => {
    // Sidebar.tsx filters search over NAV_ITEMS, not over the shortened
    // column. If that ever changes, 47 pages become findable only by URL.
    const sidebar = readFileSync(
      resolve(__dirname, '../components/sidebar/Sidebar.tsx'),
      'utf8',
    );
    const searchBlock = sidebar.slice(
      sidebar.indexOf('const filteredItems'),
      sidebar.indexOf('const filteredItems') + 420,
    );
    expect(searchBlock).toContain('NAV_ITEMS.filter');
    expect(searchBlock).not.toContain('sidebarItems.filter');
  });
});
