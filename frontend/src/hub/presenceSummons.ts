/**
 * hub/presenceSummons.ts — the presence is called, it does not loiter.
 *
 * `App.tsx` rendered `{isAuth && <PresenceAnywhereMount />}`, so the holographic
 * head sat on every page of the product for every signed-in person, all the
 * time. It was also inert: every input to `derivePresence` in that mount was a
 * literal inside a `useMemo` with an empty dependency array.
 *
 * Measured by running the mount's own constants through the real functions
 * before this module existed:
 *
 *     MODE = concerned | severity = 0.35
 *           | "Risk headroom is unmeasured -- not zero, not full, unknown."
 *
 * So the face was permanently, mildly worried, everywhere, about a number the
 * mount had hardcoded to null. A person cannot act on that and cannot turn it
 * off, and after a day of it they stop seeing the presence at all -- which is
 * the real cost, because the same face is what a critical alert has to use.
 *
 * ## The rule
 *
 * Down by default. It comes up when it is CALLED, when it is TALKING, when it
 * is LISTENING, or when what it has to say is urgent enough that waiting to be
 * asked would be wrong.
 *
 * That last clause is the one to be careful with. `chooseHeadMode` already
 * returns a severity beside every mode, and the urgent modes carry the high
 * ones: `panicking` 1.0, `worried` 0.7, `refusing` 0.4, against `concerned`
 * 0.35 and the speaking/listening pair at 0.15. `URGENT_SEVERITY` is set at
 * 0.4 so refusals and worse still raise the head unbidden, and the quiet end
 * stays down. Lowering that floor to 0.35 would restore exactly the permanent
 * worried face this module exists to remove; raising it past 0.4 would make a
 * recorded refusal silent. Neither is a tidy-up.
 *
 * ## Why a module singleton, like speechBus
 *
 * Same reasoning as `hub/speechBus.ts`: the callers are event handlers in
 * unrelated subtrees, the subscriber is a canvas somewhere else, and a context
 * provider above both would re-render half the app to carry one boolean.
 */

import { useSyncExternalStore } from 'react';

/**
 * The severity at or above which the presence raises itself without being
 * asked. See the note above before changing it -- both directions break
 * something real.
 */
export const URGENT_SEVERITY = 0.4;

export interface VisibilitySignals {
  /** The platform is speaking out loud. */
  speaking: boolean;
  /** The microphone is open. */
  micOpen: boolean;
  /** `chooseHeadMode`'s severity for the current mode, 0..1. */
  severity: number;
}

type Listener = () => void;

let summoned = false;
let summonedFor = '';
const listeners = new Set<Listener>();

function announce(): void {
  for (const listener of [...listeners]) {
    try {
      listener();
    } catch {
      // A subscriber's own error boundary owns reporting it; the bus owns
      // reaching the others. Same contract as speechBus.
    }
  }
}

/**
 * Call the presence up, and say what for.
 *
 * The reason is kept rather than discarded because "why is it here" is the
 * first question anyone debugging a presence that will not go away asks.
 */
export function summonPresence(reason: string): void {
  const next = String(reason ?? '').trim();
  if (summoned && next === summonedFor) return;
  summoned = true;
  summonedFor = next;
  announce();
}

/** Let it go. Idempotent -- dismissing a dismissed presence announces nothing. */
export function dismissPresence(): void {
  if (!summoned && summonedFor === '') return;
  summoned = false;
  summonedFor = '';
  announce();
}

/** What it was called for, or an empty string when it was not called. */
export function summonReason(): string {
  return summonedFor;
}

/** Whether something explicitly asked for it, ignoring the automatic cases. */
export function isPresenceSummoned(): boolean {
  return summoned;
}

/**
 * Whether the presence should be on screen at all.
 *
 * A pure function of the summons plus the signals, so it is testable without a
 * renderer and cannot disagree with itself between two call sites.
 */
export function isPresenceVisible(signals: VisibilitySignals): boolean {
  if (summoned) return true;
  if (signals.speaking) return true;
  if (signals.micOpen) return true;
  const severity = Number.isFinite(signals.severity) ? signals.severity : 0;
  return severity >= URGENT_SEVERITY;
}

/** Listen for summon and dismiss. Returns the unsubscribe. */
export function subscribeSummons(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React binding, for a component that re-renders when the summons changes. */
export function useSummoned(): boolean {
  return useSyncExternalStore(subscribeSummons, isPresenceSummoned, isPresenceSummoned);
}
