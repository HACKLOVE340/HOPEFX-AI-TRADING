/**
 * Four pages could not reach the shell because the shell had no width for them.
 *
 * `PageWidth` was `wide | standard | narrow`, and all three are `max-w-[…]`
 * constraints. `NuclearDashboardPage`, `AICore`, `Trading` and
 * `TradingDashboard` are workspaces: a chart surface, an order book, a plane.
 * Forcing one into a max-width does not merely restyle it — it letterboxes a
 * chart and takes away screen the operator was using, which is a migration that
 * REMOVES what a page displays.
 *
 * So the shell gains a fourth width rather than the pages losing their layout.
 * It is purely additive: nothing that exists changes, and `full` is opt-in.
 *
 * A workspace also needs its body to FILL the shell and scroll inside itself,
 * which the default body wrapper cannot do — it is a `flex flex-col gap-grid`
 * with no `min-h-0`, so a child asking for `height: 0; flex: 1` gets nothing.
 * That is `fills`, and it is a separate prop rather than being implied by
 * `width="full"`: a full-bleed page that scrolls as one long document is a real
 * shape too, and coupling the two would take it away.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { PageShell } from '../components/system/PageShell';

function shellAt(props: Partial<React.ComponentProps<typeof PageShell>> = {}) {
  const { container } = render(
    <MemoryRouter>
      <PageShell title="Workspace" {...props}>
        <div data-testid="body">content</div>
      </PageShell>
    </MemoryRouter>,
  );
  return container.firstElementChild as HTMLElement;
}

afterEach(() => cleanup());

describe('the fourth width', () => {
  it('constrains nothing at full', () => {
    const root = shellAt({ width: 'full' });
    expect(root.className).toContain('max-w-none');
    expect(root.className).not.toMatch(/max-w-\[var\(--page-/);
  });

  it('leaves the three existing widths exactly as they were', () => {
    // If any of these changes, 56 migrated pages move, and the fourth width was
    // supposed to cost them nothing.
    for (const [width, expectedClass] of [
      ['wide', 'max-w-[var(--page-wide)]'],
      ['standard', 'max-w-[var(--page-standard)]'],
      ['narrow', 'max-w-[var(--page-narrow)]'],
    ] as const) {
      cleanup();
      expect(shellAt({ width }).className).toContain(expectedClass);
    }
  });

  it('still defaults to standard', () => {
    expect(shellAt().className).toContain('max-w-[var(--page-standard)]');
  });

  it('keeps the header and the onward links at full width', () => {
    // A workspace is still a page. Dropping the frame to get the width would be
    // the same defect as not migrating at all.
    cleanup();
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <PageShell title="Workspace" width="full"><div>content</div></PageShell>
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('Workspace');
  });
});

describe('a body that fills the shell', () => {
  it('does not fill by default', () => {
    // Every one of the 56 pages already migrated relies on this.
    const body = shellAt().querySelector('[data-testid="body"]')!.parentElement!;
    expect(body.className).not.toContain('flex-1');
    expect(body.className).not.toContain('min-h-0');
  });

  it('fills and allows an inner scroller when asked', () => {
    // `min-h-0` is the half that is easy to forget: without it a flex child
    // refuses to shrink below its content, so the inner scroller never scrolls
    // and the page grows instead.
    const body = shellAt({ fills: true }).querySelector('[data-testid="body"]')!.parentElement!;
    expect(body.className).toContain('flex-1');
    expect(body.className).toContain('min-h-0');
  });

  it('keeps the one-rhythm gap either way', () => {
    expect(shellAt().querySelector('[data-testid="body"]')!.parentElement!.className).toContain('gap-grid');
    cleanup();
    expect(shellAt({ fills: true }).querySelector('[data-testid="body"]')!.parentElement!.className).toContain('gap-grid');
  });

  it('is independent of the width', () => {
    // A full-bleed page that scrolls as one long document is a real shape, and
    // a standard-width page with an inner scroller is too.
    const wide = shellAt({ width: 'full' }).querySelector('[data-testid="body"]')!.parentElement!;
    expect(wide.className).not.toContain('flex-1');
    cleanup();
    const narrow = shellAt({ width: 'narrow', fills: true }).querySelector('[data-testid="body"]')!.parentElement!;
    expect(narrow.className).toContain('flex-1');
  });
});
