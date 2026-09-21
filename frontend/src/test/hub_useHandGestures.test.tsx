/**
 * `useHandGestures` — the camera, owned by a component lifecycle.
 *
 * The owner's decision (2026-09-09): camera gestures ship as an opt-in toggle,
 * **off by default**. That default is not a nicety. A trading console that
 * opened a webcam because the page loaded would be watching an operator who
 * never asked, and no amount of later consent undoes the frame already taken.
 *
 * So the properties worth testing are mostly about NOT doing things:
 *
 *   * disabled means the camera is never opened, and nothing is downloaded;
 *   * a denied permission is a state the operator is told about, not a crash;
 *   * turning it off releases the camera track, so the hardware light goes out;
 *   * unmounting does the same, because a console that leaks a camera across a
 *     route change is worse than one that never had the feature.
 *
 * `getUserMedia` IS the consent gate here rather than a second flag beside it.
 * The toggle is the operator's intent; the browser's grant is their consent.
 * Keeping a separate `consented` boolean would let the two disagree, and the
 * one that matters is the grant.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useHandGestures } from '../hub/useHandGestures';
import { HAND_LANDMARK_COUNT } from '../hub/landmarks';

const MODEL = '/models/hand_landmarker.task';

function hand(x = 0.5) {
  return Array.from({ length: HAND_LANDMARK_COUNT }, (_, i) => (i === 8 ? { x, y: 0.5 } : { x: 0.4, y: 0.6 }));
}

function fakeStream() {
  const stop = vi.fn();
  return {
    stop,
    stream: { getTracks: () => [{ stop, kind: 'video' }] } as unknown as MediaStream,
  };
}

function fakeDetector(landmarks: Array<ReturnType<typeof hand> | null> = [hand()]) {
  let i = 0;
  return {
    start: vi.fn(async () => ({ state: 'unpermitted' as const, reason: 'starting' })),
    read: vi.fn((_input: unknown, at: number) => {
      const l = landmarks[Math.min(i++, landmarks.length - 1)];
      return l ? { landmarks: l, at } : null;
    }),
    close: vi.fn(),
    status: vi.fn(() => ({ state: 'measured' as const, reason: '' })),
  };
}

describe('off by default means nothing happens', () => {
  it('does not open the camera when disabled', async () => {
    const openCamera = vi.fn();
    const makeDetector = vi.fn();
    renderHook(() =>
      useHandGestures({ enabled: false, modelUrl: MODEL, onTrack: () => {}, openCamera, makeDetector }),
    );
    await waitFor(() => expect(openCamera).not.toHaveBeenCalled());
    expect(makeDetector).not.toHaveBeenCalled();
  });

  it('reports the off state without claiming a fault', () => {
    const { result } = renderHook(() =>
      useHandGestures({ enabled: false, modelUrl: MODEL, onTrack: () => {}, openCamera: vi.fn(), makeDetector: vi.fn() }),
    );
    expect(result.current.status.state).not.toBe('measured');
    expect(result.current.status.reason).not.toContain('cannot run it');
  });
});

describe('turning it on', () => {
  it('opens the camera and starts the detector', async () => {
    const camera = fakeStream();
    const openCamera = vi.fn(async () => camera.stream);
    const detector = fakeDetector();
    const { result } = renderHook(() =>
      useHandGestures({
        enabled: true,
        modelUrl: MODEL,
        onTrack: () => {},
        openCamera,
        makeDetector: () => detector as never,
      }),
    );
    await waitFor(() => expect(openCamera).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(detector.start).toHaveBeenCalled());
    // `measured` arrives with the first animation frame, not with start():
    // starting proves the runtime loaded and says nothing about whether the
    // camera is pointed at a wall.
    await waitFor(() => expect(result.current.status.state).toBe('measured'));
  });

  it('a denied camera is reported, not thrown', async () => {
    const openCamera = vi.fn(async () => {
      throw new DOMException('Permission denied', 'NotAllowedError');
    });
    const { result } = renderHook(() =>
      useHandGestures({ enabled: true, modelUrl: MODEL, onTrack: () => {}, openCamera, makeDetector: vi.fn() }),
    );
    await waitFor(() => expect(result.current.status.state).toBe('unpermitted'));
    expect(result.current.status.reason).toMatch(/camera/i);
  });

  it('does not start a detector when the camera was refused', async () => {
    const makeDetector = vi.fn();
    renderHook(() =>
      useHandGestures({
        enabled: true,
        modelUrl: MODEL,
        onTrack: () => {},
        openCamera: async () => {
          throw new Error('no device');
        },
        makeDetector,
      }),
    );
    await waitFor(() => expect(makeDetector).not.toHaveBeenCalled());
  });
});

describe('turning it off releases the hardware', () => {
  it('stops every camera track', async () => {
    const camera = fakeStream();
    const detector = fakeDetector();
    const { rerender } = renderHook(
      ({ enabled }) =>
        useHandGestures({
          enabled,
          modelUrl: MODEL,
          onTrack: () => {},
          openCamera: async () => camera.stream,
          makeDetector: () => detector as never,
        }),
      { initialProps: { enabled: true } },
    );
    await waitFor(() => expect(detector.start).toHaveBeenCalled());

    await act(async () => {
      rerender({ enabled: false });
    });
    await waitFor(() => expect(camera.stop).toHaveBeenCalled());
    expect(detector.close).toHaveBeenCalled();
  });

  it('unmounting does the same', async () => {
    const camera = fakeStream();
    const detector = fakeDetector();
    const { unmount } = renderHook(() =>
      useHandGestures({
        enabled: true,
        modelUrl: MODEL,
        onTrack: () => {},
        openCamera: async () => camera.stream,
        makeDetector: () => detector as never,
      }),
    );
    await waitFor(() => expect(detector.start).toHaveBeenCalled());
    await act(async () => {
      unmount();
    });
    await waitFor(() => expect(camera.stop).toHaveBeenCalled());
  });
});
