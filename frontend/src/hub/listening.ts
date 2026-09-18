/**
 * hub/listening.ts — when the microphone is open, and what was actually said.
 *
 * §17's listening half: push-to-talk, optional continuous conversation, turn
 * detection, interim results, and a wake word where privacy allows one.
 *
 * ## A microphone that stays open is the defect this is arranged against
 *
 * Push-to-talk means open while held and shut the instant it is not. Every way
 * of losing the key closes it — release, the tab hiding, the window blurring,
 * the component unmounting — because the one path that does not is the one that
 * leaves a trading desk being recorded. `dispose()` is final: after it, nothing
 * reopens the microphone, so a navigation cannot race a keypress.
 *
 * ## An interim result is a guess, and guesses do not go in the transcript
 *
 * Recognition revises as it hears more: "sell", "sell gold", "sell gold now".
 * Appending those builds a transcript of half-heard phrases attributed to the
 * operator. An interim REPLACES the previous interim; only a final result
 * commits; and an interim left pending when the microphone closes is dropped,
 * because a half-heard phrase left on screen reads as something that was said.
 *
 * ## Endpointing needs speech first
 *
 * Silence alone is not the end of a turn — an open microphone in a quiet room
 * would fire a turn every second. It endpoints only after something was heard
 * and then stopped.
 *
 * ## Continuous mode and the wake word both hold the microphone open
 *
 * So both require consent, both are off by default, and both stop the instant
 * consent is withdrawn. A revocation that waits for the next mode change is not
 * a revocation.
 */

export type ListeningMode = 'push_to_talk' | 'continuous';

export interface Mic {
  start(): void;
  stop(): void;
}

export interface Heard {
  text: string;
  final: boolean;
}

export interface HeardResult {
  /** True when this utterance contained the armed wake word. */
  woke: boolean;
}

export interface ModeResult {
  allowed: boolean;
  reason: string;
}

export interface ListeningSnapshot {
  open: boolean;
  mode: ListeningMode;
  wakeWord: string | null;
  interim: string;
  reason: string;
}

export interface ListeningOptions {
  now?: () => number;
  /** Silence after speech before the turn is considered over. */
  silenceMs?: number;
}

const DEFAULT_SILENCE_MS = 900;

/** A wake phrase shorter than this fires on ordinary speech. */
const MIN_WAKE_LENGTH = 4;

export class Listening {
  mode: ListeningMode = 'push_to_talk';
  wakeWord: string | null = null;
  interim = '';
  readonly committed: string[] = [];
  lastReason = '';

  private opened = false;
  private held = false;
  private disposed = false;
  private lastSpeechAt: number | null = null;
  private readonly now: () => number;
  private readonly silenceMs: number;

  constructor(
    private readonly mic: Mic,
    options: ListeningOptions = {},
  ) {
    this.now = options.now ?? Date.now;
    this.silenceMs = Math.max(0, options.silenceMs ?? DEFAULT_SILENCE_MS);
  }

  get open(): boolean {
    return this.opened;
  }

  // -- push to talk ----------------------------------------------------------

  press(): void {
    if (this.disposed || this.held) return;
    this.held = true;
    this.openMic('push-to-talk key held');
  }

  release(): void {
    if (!this.held) return;
    this.held = false;
    if (this.mode === 'push_to_talk') this.closeMic('push-to-talk key released');
  }

  /** Close for a reason that is not a key release: a hidden tab, a blur. */
  interrupt(reason: string): void {
    this.held = false;
    this.closeMic(reason);
  }

  /** Final. Nothing reopens the microphone afterwards. */
  dispose(): void {
    this.interrupt('the conversation was disposed');
    this.disposed = true;
    this.wakeWord = null;
  }

  // -- modes -----------------------------------------------------------------

  setMode(mode: ListeningMode, context: { micConsent: boolean }): ModeResult {
    if (this.disposed) return { allowed: false, reason: 'the conversation has been disposed' };

    if (mode === 'continuous') {
      if (!context.micConsent) {
        return {
          allowed: false,
          reason: 'continuous conversation holds the microphone open, so it needs microphone consent',
        };
      }
      this.mode = 'continuous';
      this.openMic('continuous conversation is on');
      return { allowed: true, reason: '' };
    }

    this.mode = 'push_to_talk';
    if (!this.held) this.closeMic('continuous conversation is off');
    return { allowed: true, reason: '' };
  }

  /** Consent withdrawn. Everything that holds the microphone open stops now. */
  consentWithdrawn(): void {
    this.wakeWord = null;
    this.mode = 'push_to_talk';
    this.held = false;
    this.closeMic('microphone consent was withdrawn');
  }

  // -- the wake word ---------------------------------------------------------

  armWakeWord(phrase: string, context: { micConsent: boolean }): ModeResult {
    const clean = phrase.trim().toLowerCase();
    if (clean.length < MIN_WAKE_LENGTH) {
      // "hi" fires on half of ordinary speech, which is an always-on
      // microphone with extra steps.
      return { allowed: false, reason: `"${phrase}" is too short to be a safe wake word` };
    }
    if (!context.micConsent) {
      return {
        allowed: false,
        reason: 'a wake word needs the microphone held open, so it needs microphone consent',
      };
    }
    this.wakeWord = clean;
    // Arming opens the microphone. A wake word that does not hold the mic open
    // can never fire -- it would be a control that exists, reads correctly and
    // never runs. Opening it here also means the snapshot reports an open
    // microphone from the moment it is armed, rather than from the moment
    // somebody speaks.
    this.openMic('a wake word is armed; the microphone is held open to hear it');
    return { allowed: true, reason: '' };
  }

  // -- what was heard --------------------------------------------------------

  heard(result: Heard): HeardResult {
    if (!this.opened) return { woke: false };

    const text = result.text.trim();
    this.lastSpeechAt = this.now();

    if (result.final) {
      this.interim = '';
      if (text) this.committed.push(text);
    } else {
      // Replaces, never appends: recognition revises as it hears more.
      this.interim = text;
    }

    return { woke: this.matchesWakeWord(text) };
  }

  private matchesWakeWord(text: string): boolean {
    if (this.wakeWord === null) return false;
    // Word boundaries, so "hopefxtrading" does not wake it.
    const pattern = new RegExp(`(^|[^a-z0-9])${escapeRegExp(this.wakeWord)}([^a-z0-9]|$)`, 'i');
    return pattern.test(text);
  }

  // -- turn detection --------------------------------------------------------

  /**
   * Whether the operator has finished speaking. Commits the pending interim
   * when it has.
   *
   * Silence alone is not an endpoint: an open microphone in a quiet room would
   * fire a turn every second. Something has to have been heard first.
   */
  endpointed(): boolean {
    if (!this.opened || this.lastSpeechAt === null) return false;
    if (this.now() - this.lastSpeechAt < this.silenceMs) return false;

    if (this.interim) {
      this.committed.push(this.interim);
      this.interim = '';
    }
    this.lastSpeechAt = null;
    return true;
  }

  // -- reporting -------------------------------------------------------------

  snapshot(): ListeningSnapshot {
    return {
      open: this.opened,
      mode: this.mode,
      wakeWord: this.wakeWord,
      interim: this.interim,
      reason: this.lastReason || (this.opened ? 'the microphone is open' : 'the microphone is closed'),
    };
  }

  private openMic(reason: string): void {
    this.lastReason = reason;
    if (this.opened) return;
    this.opened = true;
    this.mic.start();
  }

  private closeMic(reason: string): void {
    this.lastReason = reason;
    // A half-heard phrase left on screen after the microphone shuts reads as
    // something the operator said.
    this.interim = '';
    this.lastSpeechAt = null;
    if (!this.opened) return;
    this.opened = false;
    this.mic.stop();
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
