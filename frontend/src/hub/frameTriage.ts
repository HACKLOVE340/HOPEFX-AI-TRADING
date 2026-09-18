/**
 * hub/frameTriage.ts — deciding here whether a frame has to leave at all.
 *
 * §18 asks for "local processing where feasible". That row is a PRIVACY row,
 * not a performance one. The feasible local processing on a video stream is not
 * running a model in the browser; it is noticing that most frames are not worth
 * sending anywhere.
 *
 * A frame identical to the last one carries no new information. A blank frame
 * is a lens cap. A frame arriving forty times a second is thirty-nine frames
 * more than anyone can act on. Each of those is dropped **on the machine that
 * captured it**, and never travels.
 *
 * ## Every drop is counted, with a reason
 *
 * "The AI saw nothing" and "we sent nothing" are different facts. A triage that
 * silently discarded would make the first indistinguishable from the second,
 * and an operator wondering why the camera panel is quiet would have no way to
 * find out.
 *
 * `keptLocal` is the number worth reading: how many frames never left.
 *
 * ## Consent is checked here too
 *
 * Not because the endpoint does not check it — it does, before decoding — but
 * because the cheapest refusal is the one that happens before the network. A
 * frame that is never sent cannot be intercepted, logged, or retained by
 * anything downstream.
 */

export interface FrameSummary {
  /** A cheap local digest. Two identical frames share one. */
  fingerprint: string;
  /** 0..1 spread of pixel values. Near zero is blank. */
  variance: number;
  /** Milliseconds, monotonic. */
  at: number;
}

export interface TriageDecision {
  send: boolean;
  /** Empty only when sending. */
  reason: string;
}

export interface TriageReport {
  considered: number;
  sent: number;
  /** Frames that never left the machine. The point of the whole module. */
  keptLocal: number;
  dropped: { unchanged: number; blank: number; rate: number; consent: number };
}

/** Below this a frame is a flat field: a lens cap, a dark room, a blank screen. */
const BLANK_VARIANCE = 0.01;

const DEFAULT_MIN_INTERVAL_MS = 750;

export class FrameTriage {
  private readonly minIntervalMs: number;
  private lastSentFingerprint: string | null = null;
  private lastSentAt: number | null = null;
  private consideredCount = 0;
  private sentCount = 0;
  private readonly droppedCounts = { unchanged: 0, blank: 0, rate: 0, consent: 0 };

  constructor(options: { minIntervalMs?: number } = {}) {
    this.minIntervalMs = Math.max(0, options.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS);
  }

  consider(frame: FrameSummary, context: { consented?: boolean } = {}): TriageDecision {
    this.consideredCount += 1;

    if (context.consented === false) {
      this.droppedCounts.consent += 1;
      return { send: false, reason: 'consent for this source has not been given, so the frame stays here' };
    }

    if (frame.variance < BLANK_VARIANCE) {
      this.droppedCounts.blank += 1;
      return { send: false, reason: 'the frame is blank or near-uniform; a lens cap is not a scene' };
    }

    if (this.lastSentFingerprint !== null && frame.fingerprint === this.lastSentFingerprint) {
      this.droppedCounts.unchanged += 1;
      return { send: false, reason: 'the frame is unchanged from the last one sent and carries nothing new' };
    }

    if (this.lastSentAt !== null && frame.at - this.lastSentAt < this.minIntervalMs) {
      this.droppedCounts.rate += 1;
      return {
        send: false,
        reason: `too soon: ${frame.at - this.lastSentAt}ms since the last send, and the rate allows one every ${this.minIntervalMs}ms`,
      };
    }

    this.lastSentFingerprint = frame.fingerprint;
    this.lastSentAt = frame.at;
    this.sentCount += 1;
    return { send: true, reason: '' };
  }

  report(): TriageReport {
    return {
      considered: this.consideredCount,
      sent: this.sentCount,
      keptLocal: this.consideredCount - this.sentCount,
      dropped: { ...this.droppedCounts },
    };
  }
}
