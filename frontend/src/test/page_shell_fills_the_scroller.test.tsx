/**
 * PageShell replaced `.page-content`, so it inherits that class's layout job.
 *
 * `.app-shell-scroller` is `display:flex; flex-direction:column`, and
 * `.page-content` sits in it as `flex: 1 0 auto` — grow to fill the scroller
 * when the page is short, never shrink below content when it is tall. The
 * comment in index.css records why it is not plain `flex: 1`: `1 1 0%` clamped
 * every page to the viewport and trapped taller content.
 *
 * PageShell set no flex rule at all, so its root took the initial
 * `flex: 0 1 auto`. Measured in Chromium at 1440x900, with the app shell's
 * scroller 900px tall:
 *
 *   /observability   540   /support        560   /transparency  701
 *   /elite           540   /strategy-builder 540 /prop-firm     540
 *   /support-console 540
 *
 * — seven migrated pages stopping short, against `/portfolio` 2074,
 * `/dashboard` 2066, `/pnl` 1244 and every other legacy page filling. Nothing
 * was clipped (a flex item's `min-height: auto` floors it at its content), so
 * this is not a broken page; it is a page that ends where its content ends and
 * leaves bare scroller under it, which is exactly the inconsistency the shell
 * exists to remove.
 *
 * jsdom computes no flex layout, so this asserts the contract the browser
 * measurement proved: grow, and do not shrink.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { PageShell } from '../components/system/PageShell';

const root = () => {
  const { container } = render(
    <MemoryRouter>
      <PageShell title="Anything">
        <p>body</p>
      </PageShell>
    </MemoryRouter>,
  );
  return container.firstElementChild as HTMLElement;
};

describe('PageShell fills the scroller it lives in', () => {
  it('grows to fill a scroller taller than its content', () => {
    // `flex-1` would be `1 1 0%` — the clamp index.css warns against.
    expect(root().className).toContain('flex-[1_0_auto]');
    expect(root().className).not.toMatch(/(^|\s)flex-1(\s|$)/);
  });

  it('still lays out its sections as a column', () => {
    expect(root().className).toContain('flex-col');
  });
});
