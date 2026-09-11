/**
 * The support launcher can be moved, parked, and brought back — and it carries
 * no colour of its own.
 *
 * Two separate problems, one component.
 *
 * **It was in the way.** The launcher was pinned to a fixed bottom-right corner
 * at `zIndex: 1200`, and the presence overlay mounts on every authenticated
 * page in the same corner. On `/dashboard` the two overlap and the words run
 * through each other. Nothing could be done about it from the screen: the
 * launcher had no position anyone could change.
 *
 * **It was coloured by hand.** Fourteen hex literals inline, and not one of
 * them was the platform's: a blue-to-indigo gradient where `--accent` is cyan,
 * and a slate panel one shade off `--surface`. Two greys that look alike at a
 * glance and are not the same colour is the mechanism behind
 * `scripts/frontend_colour_ratchet.py`'s 8,021 literals, and the direct reason
 * the light/dark toggle changes nothing: an inline style cannot answer a
 * `[data-theme]` attribute.
 *
 * The colour test below is the one that keeps the second fix from rotting. A
 * component converted to tokens and then patched inline six months later is
 * back where it started, and the count does not notice one file.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import AISupportWidget, { clampBottom, shouldDock, readPlacement } from '../components/ai/AISupportWidget';

vi.mock('../components/ai/AIChat', () => ({
  default: () => <div data-testid="chat-core" />,
}));

const STORAGE_KEY = 'hopefx.support.launcher';

function launcher(): HTMLElement {
  return screen.getByRole('button', { name: /support chat/i });
}

/** A pointer gesture: press, move, release. */
function drag(element: HTMLElement, from: { x: number; y: number }, to: { x: number; y: number }): void {
  const opts = { pointerId: 1, bubbles: true };
  act(() => {
    element.dispatchEvent(new PointerEvent('pointerdown', { ...opts, clientX: from.x, clientY: from.y }));
    element.dispatchEvent(new PointerEvent('pointermove', { ...opts, clientX: to.x, clientY: to.y }));
    element.dispatchEvent(new PointerEvent('pointerup', { ...opts, clientX: to.x, clientY: to.y }));
  });
}

beforeEach(() => {
  localStorage.clear();
  // jsdom leaves these undefined on the element prototype.
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  window.innerWidth = 1280;
  window.innerHeight = 900;
});

describe('where the launcher is allowed to sit', () => {
  it('keeps it on screen when the window is shorter than the saved position', () => {
    // Saved on a tall monitor, reopened on a laptop: without the clamp it sits
    // below the fold, where it cannot be reached to move it back.
    expect(clampBottom(2000, 700)).toBeLessThanOrEqual(700);
  });

  it('never places it above the bottom margin', () => {
    expect(clampBottom(-500, 900)).toBe(20);
  });

  it('leaves a position that already fits alone', () => {
    expect(clampBottom(300, 900)).toBe(300);
  });

  it('parks when released against the right edge', () => {
    expect(shouldDock(1279, 1280)).toBe(true);
    expect(shouldDock(1250, 1280)).toBe(true);
  });

  it('does not park when released in open space', () => {
    expect(shouldDock(600, 1280)).toBe(false);
    expect(shouldDock(1200, 1280)).toBe(false);
  });
});

describe('moving and parking it', () => {
  it('starts as a launcher, not a sliver', () => {
    render(<AISupportWidget />);
    expect(launcher()).toHaveClass('support-launcher');
  });

  it('opens the chat on a click', () => {
    render(<AISupportWidget />);
    act(() => {
      launcher().dispatchEvent(new PointerEvent('pointerdown', { pointerId: 1, bubbles: true, clientX: 1240, clientY: 860 }));
      launcher().dispatchEvent(new PointerEvent('pointerup', { pointerId: 1, bubbles: true, clientX: 1240, clientY: 860 }));
    });
    expect(screen.getByTestId('chat-core')).toBeTruthy();
  });

  it('moves up the edge when dragged up', () => {
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1240, y: 500 });
    expect(Number.parseInt(launcher().style.bottom, 10)).toBeGreaterThan(20);
  });

  it('a drag does not also open the chat', () => {
    // The launcher is both draggable and clickable. Without a movement
    // threshold, every drop would open the panel on top of where it landed.
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1240, y: 500 });
    expect(screen.queryByTestId('chat-core')).toBeNull();
  });

  it('parks as a sliver when pushed into the edge', () => {
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    expect(screen.getByRole('button', { name: /show support chat/i })).toHaveClass('support-sliver');
  });

  it('the parked sliver says what it is and how to get it back', () => {
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    const sliver = screen.getByRole('button', { name: /show support chat/i });
    expect(sliver.getAttribute('title')).toMatch(/drag out/i);
  });

  it('comes back when the sliver is clicked', () => {
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    const sliver = screen.getByRole('button', { name: /show support chat/i });
    act(() => {
      sliver.dispatchEvent(new PointerEvent('pointerdown', { pointerId: 1, bubbles: true, clientX: 1277, clientY: 700 }));
      sliver.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1, bubbles: true, clientX: 1277, clientY: 700 }));
    });
    expect(launcher()).toHaveClass('support-launcher');
  });

  it('comes back when the sliver is dragged away from the edge', () => {
    render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    const sliver = screen.getByRole('button', { name: /show support chat/i });
    drag(sliver, { x: 1277, y: 700 }, { x: 1180, y: 700 });
    expect(launcher()).toHaveClass('support-launcher');
  });

  it('parking closes an open panel rather than leaving it orphaned', () => {
    render(<AISupportWidget />);
    act(() => {
      launcher().dispatchEvent(new PointerEvent('pointerdown', { pointerId: 1, bubbles: true, clientX: 1240, clientY: 860 }));
      launcher().dispatchEvent(new PointerEvent('pointerup', { pointerId: 1, bubbles: true, clientX: 1240, clientY: 860 }));
    });
    expect(screen.getByTestId('chat-core')).toBeTruthy();
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    expect(screen.queryByTestId('chat-core')).toBeNull();
  });
});

describe('it stays where it was put', () => {
  it('remembers a parked launcher', () => {
    const { unmount } = render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1279, y: 700 });
    unmount();

    render(<AISupportWidget />);
    expect(screen.getByRole('button', { name: /show support chat/i })).toHaveClass('support-sliver');
  });

  it('remembers a moved launcher', () => {
    const { unmount } = render(<AISupportWidget />);
    drag(launcher(), { x: 1240, y: 860 }, { x: 1240, y: 400 });
    const moved = launcher().style.bottom;
    unmount();

    render(<AISupportWidget />);
    expect(launcher().style.bottom).toBe(moved);
  });

  it('a corrupt saved value falls back to the default corner', () => {
    localStorage.setItem(STORAGE_KEY, '{not json');
    expect(readPlacement()).toEqual({ bottom: 20, docked: false });
  });

  it('a saved value missing its fields falls back field by field', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ docked: true }));
    expect(readPlacement()).toEqual({ bottom: 20, docked: true });
  });

  it('a non-numeric position is refused', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ bottom: 'high', docked: false }));
    expect(readPlacement().bottom).toBe(20);
  });

  it('survives storage being unavailable', () => {
    // Private windows and blocked site data both throw here. The launcher
    // forgetting where it was is fine; not rendering is not.
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('access denied');
    });
    expect(() => render(<AISupportWidget />)).not.toThrow();
    getItem.mockRestore();
  });
});

describe('it carries no colour of its own', () => {
  const read = (relative: string): string =>
    readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', relative), 'utf8');

  it('the component source declares no hex literals', () => {
    // The guard that stops this file drifting back. Every colour must come from
    // index.css, where it can read a token and answer a theme.
    const source = read('components/ai/AISupportWidget.tsx');
    const code = source.slice(source.indexOf('import React'));
    expect(code.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
  });

  it('the styles it uses read the platform tokens', () => {
    const block = read('index.css').split('.support-launcher {')[1] ?? '';
    expect(block).toContain('var(--accent)');
    expect(block).toContain('var(--surface)');
    expect(block).toContain('var(--border)');
    expect(block).toContain('var(--text-muted)');
  });

  it('the parked sliver uses the same accent as the presence rings', () => {
    // A parked assistant should still read as the same assistant.
    const css = read('index.css');
    const sliver = css.slice(css.indexOf('.support-sliver {'), css.indexOf('.support-sliver:hover'));
    expect(sliver).toContain('var(--accent)');
  });
});
