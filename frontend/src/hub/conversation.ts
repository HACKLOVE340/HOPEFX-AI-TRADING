/**
 * hub/conversation.ts — whose turn it is to talk.
 *
 * Phase 1 of the AI Hub specification (§17 interruptible real-time conversation,
 * §5 "permit interruption while speaking").
 *
 * `useVoice` already handles speech-to-text and text-to-speech. What it does not
 * handle is the thing that makes those a conversation rather than a command
 * line: cutting in. An assistant you cannot interrupt is one you have to wait
 * out, and an assistant reading a forty-second briefing you no longer want is
 * worse than one that stayed quiet.
 *
 * ## Why this is a class and not a hook
 *
 * It is a state machine with two injected engines and no React in it, so every
 * transition — barge-in mid-sentence, two answers arriving at once, disposal
 * with the microphone open — is reachable in a test without a browser, a
 * microphone, or a timer. The hook that wires it to `useVoice` is a thin shell
 * over this.
 *
 * ## The rules that matter
 *
 * **Barge-in cancels immediately.** The moment the user speaks, synthesis stops.
 * Not at the end of the sentence, not after a fade — the point of interrupting
 * is not to be talked over.
 *
 * **An interruption is remembered.** `wasInterrupted` and the transcript's
 * `interrupted` flag exist because "you cut me off" is context; a next turn that
 * does not know it was cut off reads as a non-sequitur.
 *
 * **Muting changes the audio, never the information.** A muted turn still
 * records what it would have said, so the caption and the transcript are
 * identical whether or not sound is on. §27: captions are not a lesser channel.
 *
 * **Disposal stops the microphone.** A page navigated away from with capture
 * still running is a privacy problem, not an untidiness one.
 */

export interface SpeechOut {
  /** Speak `text`; call `done` when it finishes on its own. */
  speak(text: string, done: () => void): void;
  /** Stop immediately. Must be safe to call when nothing is speaking. */
  cancel(): void;
}

export interface SpeechIn {
  start(): void;
  stop(): void;
}

export type TurnState = 'idle' | 'listening' | 'speaking';

export interface TranscriptLine {
  who: 'ai' | 'user';
  text: string;
  at: number;
  /** True when the AI was cut off part-way through this line. */
  interrupted?: boolean;
}

export interface ConversationOptions {
  /** Called once with each final user utterance. */
  onUtterance?: (text: string) => void;
  /** Audio off. The transcript is unaffected. */
  muted?: boolean;
  /** Lines kept. A long session must not grow without limit. */
  maxTranscript?: number;
  now?: () => number;
}

const DEFAULT_MAX_TRANSCRIPT = 200;

export class ConversationTurn {
  state: TurnState = 'idle';
  /** The last thing the AI said, whether or not it finished saying it. */
  lastUtterance = '';
  /** Whether the last AI line was cut off. Reset when it next speaks. */
  wasInterrupted = false;

  private readonly lines: TranscriptLine[] = [];
  private readonly max: number;
  private readonly now: () => number;

  constructor(
    private readonly out: SpeechOut,
    private readonly input: SpeechIn,
    private readonly options: ConversationOptions = {},
  ) {
    this.max = options.maxTranscript ?? DEFAULT_MAX_TRANSCRIPT;
    this.now = options.now ?? Date.now;
  }

  get transcript(): readonly TranscriptLine[] {
    return this.lines;
  }

  /** Say something. Cancels anything already being said rather than overlapping. */
  say(text: string): void {
    const clean = text.trim();
    if (!clean) return;

    // Two answers can genuinely arrive at once — two jobs finishing together.
    // The newer one wins; overlapping speech is unintelligible.
    if (this.state === 'speaking') this.out.cancel();

    this.lastUtterance = clean;
    this.wasInterrupted = false;
    this.push({ who: 'ai', text: clean, at: this.now() });

    if (this.options.muted) {
      // Recorded, not spoken. The caption is the same either way.
      this.state = 'idle';
      return;
    }

    this.state = 'speaking';
    this.out.speak(clean, () => {
      // Only settle if nothing has moved on — a barge-in may already have
      // taken the turn, and a late `done` must not steal it back.
      if (this.state === 'speaking') this.state = 'idle';
    });
  }

  /** The user has begun talking. Barge-in. */
  userStartedSpeaking(): void {
    if (this.state === 'speaking') {
      this.out.cancel();
      this.wasInterrupted = true;
      const last = this.lines[this.lines.length - 1];
      if (last && last.who === 'ai') last.interrupted = true;
    }
    this.state = 'listening';
    this.input.start();
  }

  /** The user has stopped. `text` is the final transcript, possibly empty. */
  userStoppedSpeaking(text: string): void {
    this.input.stop();
    this.state = 'idle';
    const clean = text.trim();
    if (!clean) return;
    this.push({ who: 'user', text: clean, at: this.now() });
    this.options.onUtterance?.(clean);
  }

  /** Stop everything. Safe to call twice. */
  dispose(): void {
    this.out.cancel();
    this.input.stop();
    this.state = 'idle';
  }

  private push(line: TranscriptLine): void {
    this.lines.push(line);
    if (this.lines.length > this.max) this.lines.splice(0, this.lines.length - this.max);
  }
}
