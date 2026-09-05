/**
 * D6 — the camera scanner must not fabricate a result, and must not jam.
 *
 * `VisionScanner.scan()` was five lines with two defects:
 *
 *     const scan = async () => {
 *       setStatus('processing');
 *       await new Promise((resolve) => window.setTimeout(resolve, 650));
 *       if (status !== 'processing') return;
 *       setResult('Visual interpretation is ready for review. ...');
 *       setStatus('captured');
 *     };
 *
 * The result string is fabricated: it sleeps 650ms and declares an
 * interpretation ready, having analysed nothing. And it never runs — `status`
 * is captured by the closure at render time, so after `setStatus('processing')`
 * the awaited check still reads the previous value `'captured'`, the guard is
 * true, and the function returns early. The panel jams on "Processing" with a
 * disabled button, permanently.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { VisionScanner } from '../components/intelligence/VisualIntelligenceWorkspaces';

/**
 * Globals this file replaces, restored after every test.
 *
 * `HTMLCanvasElement.prototype.getContext` in particular is shared across every
 * test file that lands in the same vitest worker, and several components draw
 * sparklines on a canvas. Leaving a stub that only implements `drawImage` in
 * place made an unrelated watchlist test render an empty row in CI while
 * passing locally, because file ordering across workers differs. A test that
 * mutates a prototype has to put it back.
 */
const originals = {
  mediaDevices: Object.getOwnPropertyDescriptor(globalThis.navigator, 'mediaDevices'),
  play: Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'play'),
  getContext: Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'getContext'),
};

afterEach(() => {
  cleanup();
  if (originals.mediaDevices) {
    Object.defineProperty(globalThis.navigator, 'mediaDevices', originals.mediaDevices);
  } else {
    Reflect.deleteProperty(globalThis.navigator as object, 'mediaDevices');
  }
  if (originals.play) {
    Object.defineProperty(HTMLMediaElement.prototype, 'play', originals.play);
  } else {
    Reflect.deleteProperty(HTMLMediaElement.prototype as object, 'play');
  }
  if (originals.getContext) {
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', originals.getContext);
  } else {
    Reflect.deleteProperty(HTMLCanvasElement.prototype as object, 'getContext');
  }
  vi.restoreAllMocks();
});

/** Put the component in the `captured` state without needing a real camera. */
async function captureAFrame(user: ReturnType<typeof userEvent.setup>) {
  const track = { stop: vi.fn() };
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value: () => ({ drawImage: vi.fn() }),
  });

  render(<VisionScanner />);
  await user.click(screen.getByRole('button', { name: /start camera/i }));
  await waitFor(() => expect(screen.getByRole('button', { name: /capture frame/i })).toBeTruthy());
  await user.click(screen.getByRole('button', { name: /capture frame/i }));
}

describe('VisionScanner', () => {
  it('does not jam on Processing after a scan', async () => {
    const user = userEvent.setup();
    await captureAFrame(user);

    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    // The stale-closure guard returned early, so the panel stayed on
    // "Processing" for ever with a disabled button.
    await waitFor(
      () => {
        expect(screen.queryByRole('button', { name: /processing/i })).toBeNull();
      },
      { timeout: 3000 },
    );
  });

  it('does not claim an interpretation it did not perform', async () => {
    const user = userEvent.setup();
    await captureAFrame(user);

    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(
      () => {
        expect(screen.queryByRole('button', { name: /processing/i })).toBeNull();
      },
      { timeout: 3000 },
    );

    const status = screen.getByRole('status');
    expect(status.textContent ?? '').not.toMatch(/interpretation is ready/i);
  });

  it('says plainly that no analysis backend is connected', async () => {
    const user = userEvent.setup();
    await captureAFrame(user);

    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(
      () => {
        expect((screen.getByRole('status').textContent ?? '')).toMatch(/not connected|unavailable/i);
      },
      { timeout: 3000 },
    );
  });
});
