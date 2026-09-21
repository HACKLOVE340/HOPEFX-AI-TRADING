/**
 * hub/useHandGestures.ts — the camera, owned by a component lifecycle.
 *
 * Owner's decision, 2026-09-09: camera gestures ship as an **opt-in toggle, off
 * by default**. That default carries the weight here. A trading console that
 * opened a webcam because a page loaded would be watching an operator who never
 * asked, and no later consent undoes the frame already taken. So `enabled:
 * false` does not merely stop reading — it opens nothing, downloads nothing and
 * constructs nothing.
 *
 * ## getUserMedia IS the consent gate
 *
 * There is no second `consented` flag beside it. The toggle is the operator's
 * intent; the browser's grant is their consent, and it is the grant that
 * matters. Two booleans that can disagree would eventually disagree, and the
 * one this code could get wrong is the one that opens a camera.
 *
 * ## Releasing the camera is not cleanup, it is the feature
 *
 * Every track is stopped on disable and on unmount, because the operator's
 * hardware light going out is how they know the console stopped looking. A
 * console that leaked a camera across a route change would be worse than one
 * that never had the feature — it would be one that lies about it.
 *
 * ## It keeps reading when the tab is hidden
 *
 * Owner's request. The loop comes from `backgroundTicker`, not
 * `requestAnimationFrame`, because rAF stops firing entirely in a hidden tab —
 * the camera would stay open, the hardware light would stay on, and nothing
 * would be read. There is no `visibilitychange` handling here at all, which is
 * the point: one loop, no second path that only runs when nobody is watching.
 *
 * ## Errors are states, not exceptions
 *
 * A denied permission, an absent device, a browser that cannot run the runtime:
 * each is something an operator is IN, and each needs a different next move
 * from them. They are reported through the same four states as everything else
 * in `landmarks.ts` rather than thrown.
 */

import { useEffect, useRef, useState } from 'react';

import { startTicker, type Ticker } from './backgroundTicker';
import { HandDetector } from './handDetector';
import { HandGestureSource } from './handGestureSource';
import { DEFAULT_MODEL_PATH } from './handRuntime';
import { landmarkStatus, type LandmarkStatus, type Viewport } from './landmarks';
import type { TrackPoint } from './gestures';

/** Target read interval. Matches what the detector can actually keep up with. */
export const TICK_MS = 33;

export interface UseHandGesturesOptions {
  /** The operator's toggle. False means nothing is opened at all. */
  enabled: boolean;
  /** A same-origin model URL. Absent means none is deployed. */
  modelUrl?: string;
  /** A completed gesture track, in the shape `recogniseGesture` reads. */
  onTrack: (points: TrackPoint[]) => void;
  /** Screen pixels the track is expressed in. Defaults to the window. */
  viewport?: Viewport;
  /** Seams, so the unit suite never opens a camera or loads 36 MB of WASM. */
  openCamera?: () => Promise<MediaStream>;
  makeDetector?: (modelUrl: string, origin: string) => HandDetector;
}

interface DetectorLike {
  start(): Promise<LandmarkStatus>;
  read(input: unknown, at: number): ReturnType<HandDetector['read']>;
  close(): void;
  status(): LandmarkStatus;
}

function defaultCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({ video: true });
}

function defaultDetector(modelUrl: string, origin: string): HandDetector {
  // `consented: true` is honest here and only here: this constructor is reached
  // exactly once getUserMedia has RESOLVED, which is the operator's grant.
  return new HandDetector({ modelUrl, origin, consented: true });
}

export function useHandGestures(options: UseHandGesturesOptions): { status: LandmarkStatus } {
  const { enabled, modelUrl = DEFAULT_MODEL_PATH, onTrack, viewport } = options;
  const [status, setStatus] = useState<LandmarkStatus>(() => landmarkStatus({ modelUrl }));

  // Held in a ref so a re-render with a new callback does not tear the camera
  // down and put the permission prompt back in front of the operator.
  const onTrackRef = useRef(onTrack);
  onTrackRef.current = onTrack;

  useEffect(() => {
    if (!enabled) {
      setStatus(landmarkStatus({ modelUrl }));
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let source: HandGestureSource | null = null;
    let ticker: Ticker | null = null;
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;

    const openCamera = options.openCamera ?? defaultCamera;
    const makeDetector = options.makeDetector ?? defaultDetector;

    (async () => {
      try {
        stream = await openCamera();
      } catch {
        // Denied, or no device. Both are states the operator is in — and the
        // detector is never constructed, so nothing is downloaded for a camera
        // that was refused.
        if (!cancelled) {
          setStatus({
            state: 'unpermitted',
            reason: 'the camera was not available — it may have been declined, or in use elsewhere',
          });
        }
        return;
      }
      if (cancelled) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }

      video.srcObject = stream;
      try {
        await video.play();
      } catch {
        // A play() rejection is not fatal: the element still produces frames in
        // every browser that granted the stream, and refusing to start here
        // would turn an autoplay policy into a broken feature.
      }

      const detector = makeDetector(modelUrl, window.location.origin) as unknown as DetectorLike;
      const started = await detector.start();
      if (cancelled) {
        detector.close();
        return;
      }
      setStatus(started);

      source = new HandGestureSource({
        detector,
        viewport: viewport ?? { width: window.innerWidth, height: window.innerHeight },
        onTrack: (points) => onTrackRef.current(points),
      });

      // ~33ms: the detector runs at roughly 17-20 frames a second, so asking
      // faster only queues work behind itself.
      ticker = startTicker(TICK_MS, () => {
        if (cancelled || source === null) return;
        source.onFrame(video, performance.now());
        setStatus(detector.status());
      });
    })();

    return () => {
      cancelled = true;
      ticker?.stop();
      source?.stop();
      // The hardware light going out is how the operator knows it stopped.
      if (stream) for (const track of stream.getTracks()) track.stop();
      video.srcObject = null;
      setStatus(landmarkStatus({ modelUrl }));
    };
    // `options.openCamera` / `options.makeDetector` are test seams and stable in
    // production; including them would restart the camera on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, modelUrl, viewport]);

  return { status };
}
