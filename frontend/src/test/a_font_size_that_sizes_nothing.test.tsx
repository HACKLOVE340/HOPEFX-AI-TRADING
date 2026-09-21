/**
 * A `fontSize` on a container whose child is an SVG sizes nothing.
 *
 * `pages/superadmin/ui.tsx::EmptyState` used to render an "inbox tray" emoji,
 * and the emoji was replaced by a Lucide `<Inbox size={22} />` during the
 * F170/F175 icon work — correctly, with the reason recorded in a comment above
 * the prop. The `fontSize: 32` that had been sizing that emoji was left behind.
 *
 * It is not a cosmetic leftover. An SVG with an explicit `size` takes its
 * dimensions from `width`/`height` attributes, so the declaration has no effect
 * on anything the component renders — and it is counted by
 * `scripts/frontend_size_ratchet.py` as one of the sizes the density control
 * cannot reach, which reads as debt that must be converted to a token. There is
 * nothing to convert: the right move is deletion, and telling the two apart is
 * only possible by rendering it.
 *
 * Found while classifying the 45 sizes above the top of the type scale, looking
 * for the ones that would justify a `--fs-display` token. This one justified
 * nothing; it was the only site in the band sizing neither a glyph nor type.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EmptyState } from '../pages/superadmin/ui';

describe('EmptyState', () => {
  it('renders its icon as an SVG, not a glyph', () => {
    const { container } = render(<EmptyState message="No rows" />);
    expect(screen.getByText('No rows')).toBeTruthy();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('declares no font size on the element that holds the icon', () => {
    const { container } = render(<EmptyState message="No rows" />);
    const holder = container.querySelector('svg')!.closest('div')!;
    expect(holder.style.fontSize).toBe('');
  });
});
