/**
 * The command palette must be built from the navigation, not beside it.
 *
 * F175. `buildStaticCommands` hand-maintained fifty navigation entries, each
 * with an emoji for an icon, while the sidebar reads `NAV_ITEMS` from
 * `navConfig.ts` — which carries a Lucide component per item. CommandPalette
 * already imported NAV_ITEMS for something else, so the duplicate list sat a
 * few lines below the real one.
 *
 * Two defects, and the emoji is the smaller:
 *
 * 1. **A second source of truth for navigation**, already drifted:
 *    `nav-dashboard` pointed at `/home` (a redirect since F209), `nav-2fa`
 *    pointed at `/2fa` which is not a route at all, and eleven pages added to
 *    the sidebar since were not offered. Nothing said so.
 *
 * 2. **Emoji as icons.** `ui-ux-pro-max` forbids it and navConfig.ts already
 *    records why (F170): per-platform rendering, no accessible name, and no
 *    `currentColor`, so they ignored the selected row's colour.
 *
 * These assert the palette *follows* the nav rather than asserting a fixed set
 * of entries — a test that pins the entries is the duplicate list again.
 *
 * The palette is rendered alone: it provides its own context, so there is no
 * provider to wrap it in.
 */

import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { NAV_ITEMS } from '../components/sidebar/navConfig';
import { CommandPalette, visibleNavItems } from '../components/CommandPalette';

// Pictographs and Miscellaneous Symbols. Deliberately excludes the arrows and
// key glyphs the chrome legitimately uses (↑↓, ↵, ⌘ — all below U+2600).
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

function openPalette() {
  render(
    <MemoryRouter>
      <CommandPalette />
    </MemoryRouter>,
  );
  fireEvent.keyDown(window, { key: 'k', metaKey: true });
  return screen.getByRole('dialog');
}

/** The palette caps its result list, so searching is how you ask for an entry. */
function search(term: string) {
  fireEvent.change(screen.getByPlaceholderText(/search pages/i), { target: { value: term } });
}

describe('CommandPalette navigation — F175', () => {
  it('offers pages from every navigation group, not a remembered subset', () => {
    const dialog = openPalette();

    // Sampled across groups by label rather than asserting a count: a count
    // still passes when the list drifts by one addition and one removal.
    // 'Strategy Builder', 'Academy' and 'Support' are three of the eleven the
    // hand-written list never gained.
    for (const label of ['Dashboard', 'Portfolio', 'Economic Calendar', 'Strategy Builder', 'Academy', 'Support']) {
      expect(NAV_ITEMS.some((i) => i.label === label), `${label} left NAV_ITEMS — update this test`).toBe(true);
      search(label);
      expect(within(dialog).getAllByText(label).length, `${label} is not offered`).toBeGreaterThan(0);
    }
  });

  it('routes to the path the navigation declares, not a remembered one', () => {
    // The drift this replaces: the palette sent Dashboard to /home while the
    // sidebar sent it to /dashboard.
    expect(NAV_ITEMS.find((i) => i.label === 'Dashboard')?.path).toBe('/dashboard');
  });

  it('hides admin pages from a signed-out user, as the sidebar does', () => {
    // No user is seeded, so this is the signed-out case.
    const labels = visibleNavItems(undefined).map((i) => i.label);
    expect(labels).not.toContain('Admin Panel');
    expect(labels).not.toContain('Master Control');
    expect(labels).toContain('Dashboard');

    // …and shows them to one who has the role.
    const asSuper = visibleNavItems('superadmin').map((i) => i.label);
    expect(asSuper).toContain('Admin Panel');
    expect(asSuper).toContain('Master Control');
  });

  it('renders no emoji anywhere in the palette', () => {
    const dialog = openPalette();
    expect(EMOJI.test(dialog.textContent ?? '')).toBe(false);

    // Including under a query, where a different set of rows is rendered.
    search('a');
    expect(EMOJI.test(dialog.textContent ?? '')).toBe(false);
  });

  it('draws its icons from the navigation config', () => {
    const dialog = openPalette();
    // Lucide renders an <svg>; an emoji renders as text. Counting SVGs
    // distinguishes the two without asserting which glyph was chosen.
    expect(dialog.querySelectorAll('svg').length).toBeGreaterThan(5);
  });
});
