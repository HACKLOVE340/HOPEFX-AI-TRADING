/**
 * Three pages could not reach the shell because the shell had one header.
 *
 * `PageHeader` renders a title, a subtitle, a breadcrumb, a badge, an actions
 * slot and tabs — which is every page in this app except three:
 *
 *   * `DocsPage` opens on a full-bleed brand band: a bordered strip across the
 *     page carrying the HOPE/FX wordmark at hero size, a status pill and the
 *     documentation search box. The search is the page's primary control and
 *     it lives IN the header.
 *   * `SuperAdminDashboard` opens on a card with a red top border, a gradient
 *     icon tile, a MASTER CONTROL badge and a live engine-health pill that
 *     changes colour on the kill switch. The red is the signal; a page that
 *     can stop the platform trading does not look like the ledger.
 *   * `Trading` (/terminal) carries a TopBar, and the owner has said to leave
 *     it alone for now.
 *
 * Migrating those by flattening them into `PageHeader` would REMOVE what the
 * pages display — the brand band, the search, the danger signal — which is the
 * one thing this work may not do. So the shell gains a slot rather than the
 * pages losing their headers.
 *
 * `hero` replaces the standard header. Everything else the shell gives a page
 * — the width, the section rhythm, and the derived "Where to next" footer that
 * stops a page being a dead end — it still gives.
 *
 * `title` therefore becomes optional, because on the hero path the shell does
 * not render it and a prop the shell ignores is a dead control. Exactly one of
 * the two is the contract, and the shell says so in development when a caller
 * gives both or neither.
 */
import React from 'react';
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { PageShell } from '../components/system/PageShell';

function shell(props: Partial<React.ComponentProps<typeof PageShell>> = {}) {
  const { container } = render(
    <MemoryRouter initialEntries={['/docs']}>
      <PageShell {...(props as React.ComponentProps<typeof PageShell>)}>
        <div data-testid="body">content</div>
      </PageShell>
    </MemoryRouter>,
  );
  return container.firstElementChild as HTMLElement;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('a page may bring its own header', () => {
  it('renders the hero in place of the standard header', () => {
    shell({ hero: <div data-testid="brand-band">HOPEFX Documentation</div> });
    expect(screen.getByTestId('brand-band')).toBeTruthy();
    // The standard header's h1 is what it must NOT also render — two page
    // headings is worse than the header it replaced.
    expect(document.querySelectorAll('h1').length).toBe(0);
  });

  it('still renders the body', () => {
    shell({ hero: <div>band</div> });
    expect(screen.getByTestId('body')).toBeTruthy();
  });

  it('still derives the footer, so a hero page is not a dead end', () => {
    shell({ hero: <div>band</div> });
    // relatedFor('/docs') derives links from navConfig; the shell renders them
    // exactly as it does for every other page.
    expect(screen.getByRole('navigation', { name: /where to next/i })).toBeTruthy();
  });

  it('still honours the width the page asked for', () => {
    expect(shell({ hero: <div>band</div>, width: 'narrow' }).className)
      .toContain('max-w-[var(--page-narrow)]');
  });

  it('still honours related={false}', () => {
    shell({ hero: <div>band</div>, related: false });
    expect(screen.queryByRole('navigation', { name: /where to next/i })).toBeNull();
  });
});

describe('the standard header is untouched', () => {
  it('renders as before when title is given and hero is not', () => {
    shell({ title: 'Ledger', subtitle: 'every fill' });
    expect(screen.getByRole('heading', { level: 1, name: 'Ledger' })).toBeTruthy();
    expect(screen.getByText('every fill')).toBeTruthy();
  });
});

describe('exactly one of title and hero', () => {
  it('warns in development when a caller gives both', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    shell({ title: 'Ledger', hero: <div data-testid="band">band</div> });
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('PageShell'));
    // and the hero wins, because the page that wrote a header meant it
    expect(screen.getByTestId('band')).toBeTruthy();
    expect(document.querySelectorAll('h1').length).toBe(0);
  });

  it('warns in development when a caller gives neither', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    shell({});
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('PageShell'));
  });

  it('does not warn on either legitimate shape', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    shell({ title: 'Ledger' });
    cleanup();
    shell({ hero: <div>band</div> });
    expect(warn).not.toHaveBeenCalled();
  });
});
