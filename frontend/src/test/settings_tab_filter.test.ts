/**
 * Settings tab filtering — visibility and search are independent. (Audit #23.)
 *
 * The original predicate returned on the role check before it ever looked at the
 * query:
 *
 *   if (t.superAdminOnly) return superAdmin;
 *   if (t.adminOnly)      return admin;
 *   if (search) return t.label.toLowerCase().includes(search.toLowerCase());
 *
 * So typing "broker" as a superadmin still listed all 39 tabs across 11 groups.
 * The one person with enough tabs to need search was the one person search
 * refused to help.
 *
 * The predicate is reimplemented here rather than imported because it is inline
 * in Settings.tsx's render. The source assertion at the bottom is what stops the
 * two from drifting apart.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

interface Tab {
  id: string;
  label: string;
  adminOnly?: boolean;
  superAdminOnly?: boolean;
  keywords?: string;
}

/** Mirrors the predicate in Settings.tsx. */
const visible = (tabs: Tab[], search: string, admin: boolean, superAdmin: boolean) =>
  tabs.filter((t) => {
    if (t.superAdminOnly && !superAdmin) return false;
    if (t.adminOnly && !admin) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return t.label.toLowerCase().includes(q) || (t.keywords ?? '').toLowerCase().includes(q);
  });

const TABS: Tab[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'security', label: 'Security', keywords: '2fa two-factor password' },
  { id: 'broker', label: 'Broker', keywords: 'oanda alpaca' },
  { id: 'system', label: 'System', adminOnly: true },
  { id: 'sa-broker-mgmt', label: 'Broker Mgmt', superAdminOnly: true },
  { id: 'sa-nuclear', label: 'Nuclear Controls', superAdminOnly: true },
];

describe('settings tab filter', () => {
  it('hides privileged tabs from a normal user', () => {
    const ids = visible(TABS, '', false, false).map((t) => t.id);
    expect(ids).toEqual(['profile', 'security', 'broker']);
  });

  it('applies the search to superadmin tabs too', () => {
    // The regression: this used to return all six.
    const ids = visible(TABS, 'broker', true, true).map((t) => t.id);
    expect(ids).toEqual(['broker', 'sa-broker-mgmt']);
  });

  it('applies the search to admin tabs too', () => {
    const ids = visible(TABS, 'system', true, false).map((t) => t.id);
    expect(ids).toEqual(['system']);
  });

  it('never reveals a privileged tab through search', () => {
    // Search widens what you can find, never what you are allowed to see.
    const ids = visible(TABS, 'nuclear', false, false).map((t) => t.id);
    expect(ids).toEqual([]);
  });

  it('matches on keywords so tabs are findable by the word users type', () => {
    expect(visible(TABS, '2fa', false, false).map((t) => t.id)).toEqual(['security']);
    expect(visible(TABS, 'oanda', false, false).map((t) => t.id)).toEqual(['broker']);
  });

  it('an empty query shows everything the role allows', () => {
    expect(visible(TABS, '', true, true)).toHaveLength(TABS.length);
  });

  it('Settings.tsx still uses the non-short-circuiting predicate', () => {
    const src = readFileSync(join(__dirname, '..', 'pages', 'Settings.tsx'), 'utf8');
    expect(src).toContain('if (t.superAdminOnly && !superAdmin) return false;');
    expect(src).toContain('if (t.adminOnly && !admin)           return false;');
    // The early-returning form must not come back.
    expect(src).not.toMatch(/if \(t\.superAdminOnly\) return superAdmin;/);
    expect(src).not.toMatch(/if \(t\.adminOnly\)\s+return admin;/);
  });
});
