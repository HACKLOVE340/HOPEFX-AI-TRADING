/**
 * A link list that renders something the source does not say.
 *
 * Found at runtime on /2fa-setup, by driving the app in a browser rather than
 * by reading it: React logged "Encountered two children with the same key,
 * `/settings`" because the page's CrossLinkBar listed that destination twice —
 * once as "Settings" and once as "API Keys".
 *
 * What that actually does was MEASURED, not inferred from the warning's
 * wording. On first mount both links render and nothing is wrong. On the next
 * re-render that reorders the list, React duplicates the shared key: a
 * three-link bar becomes four anchors, with a stale pill left behind and the
 * order wrong. Nothing throws, and a test that only mounts sees nothing.
 *
 * So these tests re-render. Each states the requirement from the reader's side
 * — the links on screen are exactly the links the caller passed, in order — so
 * they hold whatever key scheme a later edit chooses.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { RelatedPages } from '../components/RelatedPages';
import { EmptyState } from '../components/EmptyState';
import { SubPageGrid } from '../components/system/SubPageGrid';

/** The visible link text, in document order. */
const shown = () => screen.queryAllByRole('link').map((a) => a.textContent?.trim() ?? '');

describe('a list with two links to one destination survives a reorder', () => {
  it('CrossLinkBar', () => {
    const a = [
      { label: 'Settings', href: '/settings' },
      { label: 'API Keys', href: '/settings' },
      { label: 'Profile',  href: '/profile' },
    ];
    const { rerender } = render(<MemoryRouter><CrossLinkBar links={a} /></MemoryRouter>);
    expect(shown()).toEqual(['Settings', 'API Keys', 'Profile']);

    const reordered = [a[2]!, a[0]!, a[1]!];
    rerender(<MemoryRouter><CrossLinkBar links={reordered} /></MemoryRouter>);
    expect(shown()).toEqual(['Profile', 'Settings', 'API Keys']);
  });

  it('RelatedPages', () => {
    const a = [
      { to: '/settings', label: 'Settings', hint: 'Your account' },
      { to: '/settings', label: 'API Keys', hint: 'Developer tokens' },
      { to: '/profile',  label: 'Profile',  hint: 'Who you are' },
    ];
    const { rerender } = render(<MemoryRouter><RelatedPages title="Next" links={a} /></MemoryRouter>);
    rerender(<MemoryRouter><RelatedPages title="Next" links={[a[2]!, a[0]!, a[1]!]} /></MemoryRouter>);
    expect(shown().filter((t) => t.startsWith('Settings'))).toHaveLength(1);
    expect(shown().filter((t) => t.startsWith('API Keys'))).toHaveLength(1);
  });

  it('EmptyState', () => {
    const a = [
      { label: 'Settings', href: '/settings' },
      { label: 'API Keys', href: '/settings' },
      { label: 'Profile',  href: '/profile' },
    ];
    const { rerender } = render(<MemoryRouter><EmptyState title="Nothing here" links={a} /></MemoryRouter>);
    rerender(<MemoryRouter><EmptyState title="Nothing here" links={[a[2]!, a[0]!, a[1]!]} /></MemoryRouter>);
    expect(shown()).toEqual(['Profile', 'Settings', 'API Keys']);
  });

  it('SubPageGrid', () => {
    const a = [
      { to: '/settings', title: 'Settings', description: 'Your account' },
      { to: '/settings', title: 'API Keys', description: 'Developer tokens' },
      { to: '/profile',  title: 'Profile',  description: 'Who you are' },
    ];
    const { rerender } = render(<MemoryRouter><SubPageGrid items={a} /></MemoryRouter>);
    rerender(<MemoryRouter><SubPageGrid items={[a[2]!, a[0]!, a[1]!]} /></MemoryRouter>);
    expect(shown().filter((t) => t.startsWith('Settings'))).toHaveLength(1);
    expect(shown().filter((t) => t.startsWith('API Keys'))).toHaveLength(1);
  });
});

describe('the real call site that failed', () => {
  it('2FA setup offers Settings and API Keys as separate destinations', async () => {
    // Reading the page's own array rather than restating it, so the test keeps
    // describing the shipped page after someone edits the links.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.resolve(process.cwd(), 'src/pages/TwoFactorSetup.tsx'), 'utf8');
    const bar = src.slice(src.indexOf('<CrossLinkBar title="Related"'));
    const hrefs = [...bar.slice(0, bar.indexOf(']}')).matchAll(/href: '([^']+)'/g)].map((m) => m[1]);
    expect(hrefs.length).toBeGreaterThan(0);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
