/**
 * hub/cognitiveStream.ts — what the operator is told, and what is recorded.
 *
 * §3 lists a "cognitive stream" among what the platform already has. It does
 * not exist. §23 asks for the version worth building: a user-facing explanation
 * **distinct from the internal trace**.
 *
 * ## They are two streams, and merging them is a leak
 *
 * The trace carries prompts, tool names, model identifiers and raw tool output.
 * The explanation is a sentence for somebody deciding whether to trust an
 * answer. A single stream showing both to the operator has published the first
 * one — and "it is only on the AI's own panel" is not a boundary, it is a
 * screenshot away from not being one.
 *
 * So `explanation()` and `trace()` are separate lists filled from separate
 * fields, and `forOperator()` returns a shape the trace is not reachable from.
 *
 * ## Nothing to say is "Working", never the trace
 *
 * The tempting shortcut when a step has no human-readable line is to show the
 * trace, because it is right there and it is *something*. That is the leak
 * arriving by convenience rather than by design.
 *
 * ## The trace survives even when nobody is looking
 *
 * It is for the audit, not for the screen. Dropping it because the panel is
 * closed is how an incident becomes unreconstructable.
 */

/** What a step says when it has no human-readable line of its own. */
const WORKING = 'Working.';

const DEFAULT_LIMIT = 200;

export interface Step {
  /** The sentence an operator reads. Optional; absent becomes "Working." */
  say?: string;
  /** The internal record. Never rendered to an operator. */
  trace?: string;
}

export interface OperatorView {
  lines: string[];
  dropped: number;
}

export class CognitiveStream {
  private readonly limit: number;
  private readonly said: string[] = [];
  private readonly traced: string[] = [];
  private droppedCount = 0;

  constructor(options: { limit?: number } = {}) {
    this.limit = Math.max(1, options.limit ?? DEFAULT_LIMIT);
  }

  step(step: Step): void {
    const say = (step.say ?? '').trim();
    const trace = (step.trace ?? '').trim();
    if (!say && !trace) {
      throw new Error('a step that says nothing and records nothing is not a step');
    }

    // "Working." rather than the trace. Showing the trace because it is the
    // only text available is the leak arriving by convenience.
    this.push(this.said, say || WORKING);
    if (trace) this.push(this.traced, trace);
  }

  private push(into: string[], line: string): void {
    into.push(line);
    if (into.length > this.limit) {
      into.shift();
      // Counted once per dropped explanation, so the number means "steps the
      // operator can no longer scroll back to".
      if (into === this.said) this.droppedCount += 1;
    }
  }

  /** What the operator reads. */
  explanation(): string[] {
    return [...this.said];
  }

  /** What the audit reads. Never rendered. */
  trace(): string[] {
    return [...this.traced];
  }

  dropped(): number {
    return this.droppedCount;
  }

  /**
   * The operator's view, with no path to the trace.
   *
   * Returning `this` and letting the caller pick fields would put the trace one
   * property access away from a render.
   */
  forOperator(): OperatorView {
    return { lines: this.explanation(), dropped: this.droppedCount };
  }
}
