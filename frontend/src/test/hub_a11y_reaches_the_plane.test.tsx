/**
 * §27 driven through the real plane.
 *
 * `hub_a11y.test.ts` proves `RovingFocus` decides correctly and
 * `hub_a11y_guard.test.ts` proves `hub/` still uses the contract. Neither
 * proves the caret moves: a group can have perfect tab indices, a correct
 * `role="toolbar"`, and never call `focus()` — which is the ARIA pattern
 * rendered as decoration.
 *
 * So this renders `PresenceStage` with enough surfaces that some collapse, and
 * checks `document.activeElement` after a key. That is the only assertion that
 * distinguishes a working roving group from a convincing one.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { PresenceStage } from '../hub/PresenceStage';
import type { Presence } from '../hub/presence';
import type { Surface } from '../hub/workspace';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(),
    cancelSpeak: vi.fn(),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    speaking: false,
    listening: false,
    sttSupported: false,
    transcript: '',
    status: null,
    spokenText: '',
    speechProgress: null,
  }),
}));

const presence: Presence = {
  state: 'idle',
  tone: 'ok',
  reason: 'Nothing needs attention.',
  intensity: 0.2,
  headroomKnown: true,
};

/**
 * Enough surfaces for the plane to be crowded, most of them background tier.
 *
 * `place()` only collapses when the plane is over its threshold, so a handful
 * of background surfaces renders no stack at all — and a test that asserted
 * against an empty toolbar would pass by finding nothing.
 */
function backgroundSurfaces(count: number): Surface[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `bg-${i}`,
    kind: 'chart' as const,
    meaning: `Background ${i}`,
    // The first two hold the plane above the collapse threshold; the rest fold
    // into the stack this test drives.
    priority: i < 2 ? ('primary' as const) : ('background' as const),
    span: 4,
    pinned: false,
    key: `bg-${i}`,
    openedAt: 1_700_000_000_000 + i,
    order: i,
    data: { value: i, label: `Background ${i}` },
  }));
}

function stackButtons(): HTMLElement[] {
  const toolbar = screen.getByRole('toolbar', { name: /collapsed background surfaces/i });
  return Array.from(toolbar.querySelectorAll('button'));
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('§27 keyboard navigation, on the real plane', () => {
  function renderStage(count = 8, onExit: () => void = vi.fn()) {
    return render(
      <PresenceStage
        presence={presence}
        surfaces={backgroundSurfaces(count)}
        focusedId={null}
        listening={false}
        muted={false}
        sttSupported={false}
        transcript={[]}
        layout="auto"
        onCommand={vi.fn()}
        onTalk={vi.fn()}
        onStop={vi.fn()}
        onToggleMute={vi.fn()}
        onCloseSurface={vi.fn()}
        onPinSurface={vi.fn()}
        onExit={onExit}
      />,
    );
  }

  it('gives the collapsed stack one tab stop, not one per chip', () => {
    renderStage();
    const buttons = stackButtons();
    expect(buttons.length).toBeGreaterThan(1);
    const tabbable = buttons.filter((b) => b.tabIndex === 0);
    expect(tabbable).toHaveLength(1);
    expect(tabbable[0]).toBe(buttons[0]);
  });

  it('moves the caret with the arrow, not only the tab index', () => {
    renderStage();
    const buttons = stackButtons();
    buttons[0]!.focus();
    expect(document.activeElement).toBe(buttons[0]);

    fireEvent.keyDown(buttons[0]!, { key: 'ArrowRight' });
    // The assertion that a correct-looking, non-functioning group fails.
    expect(document.activeElement).toBe(buttons[1]);
    expect(stackButtons()[1]!.tabIndex).toBe(0);
    expect(stackButtons()[0]!.tabIndex).toBe(-1);
  });

  it('wraps at the end rather than stopping dead', () => {
    renderStage();
    const buttons = stackButtons();
    buttons[0]!.focus();
    fireEvent.keyDown(buttons[0]!, { key: 'End' });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(buttons[0]);
  });

  it('ignores the cross-axis arrow, so the plane behind it still scrolls', () => {
    renderStage();
    const buttons = stackButtons();
    buttons[0]!.focus();
    fireEvent.keyDown(buttons[0]!, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(buttons[0]);
  });

  it('lets Escape through to the stage, which is the way out', () => {
    const onExit = vi.fn();
    renderStage(8, onExit);
    stackButtons()[0]!.focus();
    // The stage listens on window; a group that called preventDefault on every
    // key would swallow this and leave a full-screen surface with no way out.
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).toHaveBeenCalled();
  });
});
