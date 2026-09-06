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
import { api } from '../hooks/useApi';

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
  toDataURL: Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'toDataURL'),
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
  if (originals.toDataURL) {
    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', originals.toDataURL);
  } else {
    Reflect.deleteProperty(HTMLCanvasElement.prototype as object, 'toDataURL');
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
  // jsdom's own toDataURL needs the native `canvas` package, which this repo
  // does not install. Stubbed so capture() can read the frame back.
  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    configurable: true,
    value: () => 'data:image/jpeg;base64,QUJD',
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

  /**
   * The frame was captured to a `const canvas` that nothing ever read, and the
   * request body was literally `{ source: 'camera_frame' }`. So even once the
   * backend existed, the scanner sent no image and the endpoint had nothing to
   * interpret. These cover the other half of the camera path.
   */
  it('sends the captured frame, not just a label', async () => {
    const user = userEvent.setup();
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { reason: 'ok', interpretation: 'Reads as a chart.', detection: { surface_type: 'chart' } },
    } as never);

    await captureAFrame(user);
    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(() => expect(post).toHaveBeenCalled(), { timeout: 3000 });
    const call = post.mock.calls[0];
    expect(call, 'the endpoint was never called').toBeTruthy();
    const body = call![1] as { image_b64?: string; media_type?: string };
    expect(body.image_b64, 'no image was sent').toBeTruthy();
    expect(body.image_b64).toMatch(/^[A-Za-z0-9+/=]+$/);
    expect(body.media_type).toMatch(/^image\//);
  });

  it('sends base64 payload only, never the data-URI prefix', async () => {
    const user = userEvent.setup();
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { reason: 'ok' } } as never);

    await captureAFrame(user);
    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(() => expect(post).toHaveBeenCalled(), { timeout: 3000 });
    const call = post.mock.calls[0];
    expect(call, 'the endpoint was never called').toBeTruthy();
    const body = call![1] as { image_b64?: string };
    expect(body.image_b64 ?? '').not.toMatch(/^data:/);
  });

  it('shows the interpretation the server actually returned', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { reason: 'ok', interpretation: 'Reads as a chart, instrument XAUUSD.', detection: {} },
    } as never);

    await captureAFrame(user);
    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(
      () => expect(screen.getByRole('status').textContent ?? '').toMatch(/XAUUSD/),
      { timeout: 3000 },
    );
  });

  it('does not invent a reading when the server supplies none', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { reason: 'no_frame_supplied', interpretation: null },
    } as never);

    await captureAFrame(user);
    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));

    await waitFor(
      () => expect(screen.getByRole('status').textContent ?? '').toMatch(/no interpretation|not been interpreted/i),
      { timeout: 3000 },
    );
  });

  /**
   * A browser refuses to read back a canvas it considers tainted. That has to
   * leave the panel usable and honest rather than stuck on a frame that does
   * not exist — the same shape as every other failure path here.
   */
  it('stays honest when the frame cannot be read back from the canvas', async () => {
    const user = userEvent.setup();
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { reason: 'ok' } } as never);

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
    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
      configurable: true,
      value: () => {
        throw new Error('tainted canvas');
      },
    });

    render(<VisionScanner />);
    await user.click(screen.getByRole('button', { name: /start camera/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /capture frame/i })).toBeTruthy());
    await user.click(screen.getByRole('button', { name: /capture frame/i }));

    // It must not jam, and must say what happened.
    await waitFor(
      () => expect(screen.getByRole('status').textContent ?? '').toMatch(/could not be read back/i),
      { timeout: 3000 },
    );

    // And scanning an empty frame must not spend a paid model call to be told
    // there is nothing there.
    await user.click(screen.getByRole('button', { name: /scan captured frame/i }));
    await waitFor(
      () => expect(screen.getByRole('status').textContent ?? '').toMatch(/no captured frame/i),
      { timeout: 3000 },
    );
    expect(post).not.toHaveBeenCalled();
  });
});
