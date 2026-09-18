/**
 * hub/visionSource.ts — which source the AI may look through, if any.
 *
 * §18 asks for "screen and camera source selection". The selection is the easy
 * half; the half worth getting right is that **a screen share and a webcam are
 * different consents**.
 *
 * A webcam shows a face. A screen share shows the whole desktop — every other
 * application, every other window, whatever was open behind the browser.
 * Consenting to one is not consenting to the other, and a system that treats
 * them as one permission has quietly widened what it was allowed to see.
 *
 * ## Unknown capability is not unavailable
 *
 * `availableSources({})` reports `available: false` with a reason saying
 * nothing was checked, rather than claiming the browser has no camera. Only one
 * of those two is a fact.
 *
 * ## `none` is always allowed
 *
 * It is how the operator turns it off, and a control that can be refused is not
 * an off switch.
 */

export const SOURCES = ['none', 'camera', 'screen'] as const;
export type VisionSource = (typeof SOURCES)[number];

export interface Capability {
  available: boolean;
  /** Empty only when available. Says "not checked" versus "not present". */
  reason: string;
}

export interface Capabilities {
  camera: Capability;
  screen: Capability;
}

export function availableSources(probe: { hasCamera?: boolean; hasScreenCapture?: boolean }): Capabilities {
  const one = (value: boolean | undefined, name: string): Capability => {
    if (value === undefined) {
      return { available: false, reason: `${name} support was not checked, which is not the same as absent` };
    }
    return value ? { available: true, reason: '' } : { available: false, reason: `this browser offers no ${name}` };
  };
  return {
    camera: one(probe.hasCamera, 'camera'),
    screen: one(probe.hasScreenCapture, 'screen capture'),
  };
}

export interface SourceChoice {
  source: VisionSource;
  allowed: boolean;
  reason: string;
}

export function selectSource(
  requested: VisionSource,
  context: { consent: { camera: boolean; screen: boolean } },
): SourceChoice {
  if (!(SOURCES as readonly string[]).includes(requested)) {
    // Falling back to the camera would open a source nobody asked for.
    throw new Error(`unknown vision source ${requested}; expected one of ${SOURCES.join(', ')}`);
  }

  if (requested === 'none') {
    return { source: 'none', allowed: true, reason: '' };
  }

  const consented = requested === 'camera' ? context.consent.camera : context.consent.screen;
  if (!consented) {
    return {
      source: requested,
      allowed: false,
      reason:
        requested === 'screen'
          ? 'screen capture needs its own consent: a screen share shows every other application, not a face'
          : 'camera consent has not been given',
    };
  }

  return { source: requested, allowed: true, reason: '' };
}
