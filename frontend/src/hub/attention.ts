/**
 * hub/attention.ts — whether anybody is looking, answered without a camera.
 *
 * §18 asks for "optional attention-aware interaction". The expensive way to
 * build it is gaze tracking from a webcam. The cheap way answers most of the
 * question from three things the browser already knows: is the tab visible, is
 * the window focused, and how long since the operator touched anything.
 *
 * The cheap way is built first on purpose. **The cheapest way to respect
 * somebody's privacy is not to need their permission** — this needs no camera,
 * no consent conversation, and nothing leaves the machine.
 *
 * ## Unknown is not "away"
 *
 * §22's rule, arriving where it matters most. An attention state derived from
 * inputs nobody supplied is not "the operator has left" — it is "nobody
 * looked". Reporting the first would have the presence go quiet on somebody
 * sitting right in front of it, on any browser that does not report
 * visibility.
 *
 * ## §7's idle movement reads from here
 *
 * `presence.idle_attention` said "breathes at rest and pulses under load; no
 * attention tracking yet". `idleMotion` is that tracking: still when the
 * operator is genuinely away, breathing when they are present, and breathing
 * when nobody knows — because a presence that goes still on unknown looks
 * broken rather than tactful.
 */

export const ATTENTION_STATES = ['engaged', 'present', 'away', 'unknown'] as const;
export type AttentionState = (typeof ATTENTION_STATES)[number];

/** Beyond this without input, the operator is present but not interacting. */
const IDLE_MS = 60_000;

export interface AttentionInputs {
  /** `document.visibilityState === 'visible'`. */
  visible?: boolean;
  /** The window has focus. A visible background window is still not attention. */
  focused?: boolean;
  /** Milliseconds since the last pointer or key event. */
  msSinceInput?: number;
}

export interface Attention {
  state: AttentionState;
  /** Empty only when `engaged`. Populated for every other state. */
  reason: string;
  /** Always false here. Stated so a caller can prove no camera was involved. */
  usedCamera: false;
}

export function attentionFrom(inputs: AttentionInputs): Attention {
  const { visible, focused, msSinceInput } = inputs;

  if (visible === undefined && focused === undefined && msSinceInput === undefined) {
    return {
      state: 'unknown',
      reason: 'attention was not measured: no visibility, focus or input recency was supplied',
      usedCamera: false,
    };
  }

  if (visible === false) {
    return { state: 'away', reason: 'the tab is hidden', usedCamera: false };
  }
  if (focused === false) {
    // A visible background window is not attention: the operator is looking at
    // something else on top of it.
    return { state: 'away', reason: 'the window does not have focus', usedCamera: false };
  }

  if (msSinceInput === undefined) {
    return {
      state: 'present',
      reason: 'the tab is visible and focused, but time since last input was not measured',
      usedCamera: false,
    };
  }
  if (msSinceInput > IDLE_MS) {
    return {
      state: 'present',
      reason: `nothing has been touched for ${Math.round(msSinceInput / 1000)}s`,
      usedCamera: false,
    };
  }

  return { state: 'engaged', reason: '', usedCamera: false };
}

export interface IdleMotion {
  /** 0 is still. 1 is the full resting breath. */
  amplitude: number;
  reason: string;
}

/** §7. How much the presence should move while nothing is happening. */
export function idleMotion(attention: Attention, reducedMotion = false): IdleMotion {
  if (reducedMotion) {
    // A floor, not a weight. For some people the setting is medical.
    return { amplitude: 0, reason: 'reduced motion is set' };
  }
  if (attention.state === 'away') {
    return { amplitude: 0, reason: 'the operator is away; animating to an empty room is wasted frames' };
  }
  if (attention.state === 'engaged') {
    return { amplitude: 0.4, reason: 'the operator is engaged; a light breath, not a performance' };
  }
  // `present` and `unknown` both breathe. Going still on unknown would make the
  // presence look broken on every browser that does not report visibility.
  return {
    amplitude: 1,
    reason:
      attention.state === 'present'
        ? 'the operator is present but idle; resting breath'
        : 'attention is unknown, so it keeps breathing rather than appearing dead',
  };
}
