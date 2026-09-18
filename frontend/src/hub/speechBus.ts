/**
 * hub/speechBus.ts — what the platform is saying out loud, available anywhere.
 *
 * §7 asks for "a professional holographic head as the default presence" with
 * "lip synchronisation where the voice pipeline supports it". Both existed and
 * only one of them ran.
 *
 * `hub/head.ts::mouthFor` drives the mouth from the character actually being
 * spoken, and `AICore` fed it correctly. But `PresenceAnywhere` — the head that
 * is on every page in the app — rendered `PresenceCore` with no `utterance`, no
 * `speechProgress` and no `speaking`, because speech lived in `useVoice`'s
 * component state and there was no way for a component elsewhere in the tree to
 * read it. So the presence everybody actually sees had its mouth painted shut
 * while the platform talked.
 *
 * That is the dead-control shape `.claude/skills/hopefx-dead-controls` names:
 * the control is correct, documented and never given its input.
 *
 * ## Why a module singleton and not React context
 *
 * The publisher is a hook callback inside a synthesis event handler, firing
 * several times a second; the subscribers are canvases in unrelated subtrees.
 * A context provider would have to sit above both, re-render its whole subtree
 * per `boundary` event, and exist before any of this could be wired — which is
 * how "the head can talk" turns into an app-shell refactor. A module with an
 * explicit subscribe is smaller, testable without a renderer, and cannot
 * re-render anything that did not ask.
 *
 * ## It publishes measurements, never a clock
 *
 * `progress` is the engine's own character index or the audio element's
 * playback position. It is **null** when nothing measured it, and null is not
 * zero: `mouthFor` reads null as "speaking, unmeasured" and holds a steady
 * shape, whereas zero would pin the mouth to the first character of the string
 * for the entire utterance — animated, precise, and wrong.
 *
 * ## It normalises at the boundary rather than trusting publishers
 *
 * Silence clears the utterance and the progress together, a non-finite progress
 * becomes null, a progress outside 0..1 is clamped, and speech with no text is
 * silence. `useVoice` already keeps every one of those rules; the bus keeps
 * them again because the next publisher has not been written yet.
 */

import { useSyncExternalStore } from 'react';

export interface SpeechFrame {
  /** What is being said. Empty when nothing is. */
  utterance: string;
  /**
   * How far through, 0..1 — or **null** when nothing measured it. Never a
   * timer, never an estimate.
   */
  progress: number | null;
  speaking: boolean;
}

/** Nothing is being said. */
export const SILENT: SpeechFrame = Object.freeze({
  utterance: '',
  progress: null,
  speaking: false,
});

type Listener = (frame: SpeechFrame) => void;

let frame: SpeechFrame = SILENT;
const listeners = new Set<Listener>();

function normalise(next: SpeechFrame): SpeechFrame {
  const utterance = typeof next.utterance === 'string' ? next.utterance : '';
  // Speech with nothing to say is silence: `useVoice.speak` returns early on an
  // empty string without starting synthesis, so a frame claiming otherwise
  // describes an utterance that was never spoken.
  if (!next.speaking || utterance.trim().length === 0) return SILENT;

  const raw = next.progress;
  const progress =
    typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : null;

  return { utterance, progress, speaking: true };
}

function same(a: SpeechFrame, b: SpeechFrame): boolean {
  return a.utterance === b.utterance && a.progress === b.progress && a.speaking === b.speaking;
}

/** What is being said right now. */
export function currentSpeech(): SpeechFrame {
  return frame;
}

/**
 * Announce a change in what the platform is saying.
 *
 * An identical frame notifies nobody. Cloud TTS fires `ontimeupdate` several
 * times a second and Web Speech fires `boundary` per word; re-rendering every
 * head in the app for a frame that did not change is how a decorative canvas
 * becomes a frame-rate problem on the page that also places orders.
 */
export function publishSpeech(next: SpeechFrame): void {
  const clean = normalise(next);
  if (same(clean, frame)) return;
  frame = clean;
  for (const listener of [...listeners]) {
    try {
      listener(clean);
    } catch {
      // One head that throws must not mute every other head in the app. The
      // subscriber's own error boundary owns reporting it; the bus owns
      // delivery, and delivery continues.
    }
  }
}

/**
 * Listen. Returns the unsubscribe.
 *
 * The listener is called immediately with the current frame, so a head that
 * mounts mid-utterance opens its mouth on its first painted frame instead of
 * staying shut until the next word boundary — which, on a short reply, is the
 * whole reply.
 */
export function subscribeSpeech(listener: Listener): () => void {
  listeners.add(listener);
  try {
    listener(frame);
  } catch {
    /* see publishSpeech */
  }
  return () => {
    listeners.delete(listener);
  };
}

/** Tests only. Drops every listener and returns to silence. */
export function resetSpeechBus(): void {
  frame = SILENT;
  listeners.clear();
}

/**
 * React binding. Re-renders the caller when what is being said changes.
 *
 * `useSyncExternalStore` rather than `useEffect` + `useState`: the frame is
 * external mutable state, and the store hook is the API React provides for
 * exactly that. It also closes the gap the effect version leaves — a component
 * mounting mid-utterance gets the current frame in its first render rather than
 * after a commit, which on a short reply is the difference between a head that
 * speaks and one that stays shut for the whole sentence.
 */
export function useSpeech(): SpeechFrame {
  return useSyncExternalStore(subscribeFrames, currentSpeech, currentSpeech);
}

/** `useSyncExternalStore` wants subscribe-without-immediate-call. */
function subscribeFrames(onChange: () => void): () => void {
  listeners.add(onChange as Listener);
  return () => {
    listeners.delete(onChange as Listener);
  };
}
