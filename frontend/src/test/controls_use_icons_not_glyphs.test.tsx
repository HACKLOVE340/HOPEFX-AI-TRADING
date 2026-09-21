/**
 * A control's icon must be an SVG, not a character.
 *
 * `navConfig.ts` carries the reasoning, written when the sidebar was converted
 * (F170): emoji render differently on every OS, cannot inherit `currentColor`
 * so they ignore theme, hover and disabled state, are announced literally by
 * screen readers, and cannot sit on the optical grid.
 * `scripts/frontend_emoji_ratchet.py` holds the tree-wide count at a baseline
 * that may only fall; this file holds the three controls where the glyph was
 * doing the most work, by rendering them.
 *
 * `Toast` is the clearest case and the reason this is a test rather than a
 * count: `VARIANT_STYLES` types `icon` as `React.ReactNode` and already gave
 * `warning` an `<AlertTriangle/>` and `info` an `<Info/>`, while `success` and
 * `error` — the two a trader sees after an order — were still `'✓'` and `'✕'`
 * in the same table. Half a migration reads as a finished one until something
 * renders all four.
 */

import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import { Modal } from '../components/Modal';
import { ThemeToggle } from '../components/ThemeToggle';
import { ToastProvider, useToast } from '../components/Toast';
import { ThemeProvider } from '../components/ThemeContext';
import React, { useEffect } from 'react';

const GLYPH = /[←-⯿\u{1F000}-\u{1FAFF}]/u;

// jsdom has no matchMedia, and ThemeContext reads it to resolve "system".
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }),
  });
});

describe('Modal', () => {
  it('closes with an icon that keeps its accessible name', () => {
    render(
      <Modal open onClose={() => {}} title="Confirm">
        <p>body</p>
      </Modal>,
    );
    const close = screen.getByRole('button', { name: /close dialog/i });
    expect(close.querySelector('svg'), 'the close control renders no SVG').not.toBeNull();
    expect(close.textContent ?? '').not.toMatch(GLYPH);
  });
});

describe('ThemeToggle', () => {
  it('shows a sun or a moon as an icon, not a character', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const button = screen.getByRole('button');
    expect(button.querySelector('svg')).not.toBeNull();
    expect(button.textContent ?? '').not.toMatch(GLYPH);
  });
});

const Fire: React.FC<{ variant: 'success' | 'error' | 'warning' | 'info' }> = ({ variant }) => {
  const toast = useToast();
  useEffect(() => {
    toast.add({ message: `a ${variant}`, variant });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variant]);
  return null;
};

describe('Toast', () => {
  it.each(['success', 'error', 'warning', 'info'] as const)('renders %s with an icon', async (variant) => {
    const { container } = render(
      <ToastProvider>
        <Fire variant={variant} />
      </ToastProvider>,
    );
    await screen.findByText(`a ${variant}`);
    expect(container.querySelectorAll('svg').length, `${variant} renders no SVG`).toBeGreaterThan(0);
    expect(container.textContent ?? '').not.toMatch(GLYPH);
  });
});

/**
 * An icon-only control must state its name.
 *
 * This is the failure mode of the conversion itself, and it bit twice before it
 * was written down. `AccountBar`'s notification button and five close buttons
 * had an accessible name BY ACCIDENT: the glyph was the button's text content,
 * so a screen reader announced "bell" or the character. Replacing it with an
 * `aria-hidden` icon — which is correct, the icon is decorative — leaves the
 * button with no name at all.
 *
 * `jsx-a11y/control-has-associated-label` does not catch these: it is
 * downgraded to a warning for the 17 files in `a11y-debt.json` and, more to the
 * point, it did not fire on any of the six.
 *
 * Source-level rather than rendered, deliberately: rendering every page that
 * has a close button is a suite, and the shape is exact enough to match.
 */
describe('icon-only buttons', () => {
  it('never rely on a hidden icon for their name', async () => {
    const { readFileSync, readdirSync, statSync } = await import('node:fs');
    const { join, resolve } = await import('node:path');

    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((entry) => {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) return entry === 'test' ? [] : walk(full);
        return full.endsWith('.tsx') ? [full] : [];
      });

    const ICON_ONLY = /<button\b([^>]*)>\s*(<[A-Z]\w*\s[^>]*aria-hidden[^>]*\/>)\s*<\/button>/;
    const unnamed: string[] = [];
    for (const file of walk(resolve(__dirname, '..'))) {
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((line, i) => {
          const m = ICON_ONLY.exec(line);
          if (m && !/aria-label|title=/.test(m[1]!)) unnamed.push(`${file.split('/src/')[1]}:${i + 1}`);
        });
    }
    expect(unnamed, `these buttons have no accessible name:\n${unnamed.join('\n')}`).toEqual([]);
  });
});
