/**
 * The camera control exists, and it is OFF until an operator says otherwise.
 *
 * Owner's decision, 2026-09-09: camera gestures ship as an opt-in toggle, off by
 * default. This is the test that keeps the default honest, because "off by
 * default" is the kind of property that survives review and dies to a later
 * one-line change nobody reads.
 *
 * The two things worth holding:
 *
 *   1. rendering the stage opens NO camera — not "opens and immediately closes",
 *      and not "asks for permission and gets refused". A trading console that
 *      prompted for a webcam because a page loaded has already told the
 *      operator something false about what it is for.
 *   2. the control says which state it is in, and the reason is the one
 *      `landmarkStatus` gives, so an operator whose gesture does nothing learns
 *      WHICH of the four absences it is rather than "not working".
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { PresenceStage } from '../hub/PresenceStage';

const noop = () => {};

function renderStage() {
  return render(
    <PresenceStage
      presence={{ state: 'idle' } as never}
      surfaces={[]}
      focusedId={null}
      listening={false}
      muted={false}
      sttSupported
      transcript={[]}
      layout={'focus' as never}
      onCommand={noop}
      onTalk={noop}
      onStop={noop}
      onToggleMute={noop}
      onCloseSurface={noop}
      onPinSurface={noop}
      onExit={noop}
    />,
  );
}

describe('the camera is not opened by rendering a page', () => {
  let getUserMedia: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    getUserMedia = vi.fn(async () => {
      throw new Error('the console must not ask for a camera on load');
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('never calls getUserMedia', () => {
    renderStage();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('offers the control, unpressed', () => {
    renderStage();
    const button = screen.getByRole('button', { name: /hands/i });
    expect(button).toHaveAttribute('aria-pressed', 'false');
  });

  it('the control says what it would do rather than claiming a fault', () => {
    renderStage();
    const button = screen.getByRole('button', { name: /hands/i });
    expect(button.getAttribute('title') ?? '').toMatch(/camera/i);
    expect(button.getAttribute('title') ?? '').not.toMatch(/cannot run it/i);
  });
});
