/**
 * hub/presence.ts — what the AI presence is doing, derived from what the system
 * is doing.
 *
 * Phase 1 of the AI Hub specification (§7 animation states, §5 honest state).
 *
 * ## Why this is a pure function
 *
 * The existing `HologramPanel` sets its own state — `setState('analyzing')` with
 * no request made — and the comment in that file says so plainly: it "narrated
 * an analysis that never happened". A presence that can assert its own mood can
 * assert a mood the system is not in, and nothing catches it, because there is
 * nothing to catch it against.
 *
 * So state here is a pure function of real inputs. Every input traces to
 * something already flowing: the WebSocket status and stale-feed flag from
 * `useWebSocket`, job counts from the runner's `ai_jobs` channel, risk headroom
 * and provider reachability from the AI Core summary. Nothing is invented, and
 * the same inputs always produce the same answer.
 *
 * ## Why every state carries a reason
 *
 * A presence that cannot say why it looks alarmed is a decorative badge. The
 * reason is the caption, the screen-reader announcement, and what the AI says
 * out loud — one sentence, three consumers, so they cannot drift apart.
 *
 * ## Why precedence is explicit
 *
 * Several inputs are true at once far more often than not: a job runs while the
 * microphone is open while the feed is stale. "Whichever branch was written
 * first" is not a design, so the order is stated, tested, and justified where it
 * is not obvious — notably that listening beats speaking, because if both are
 * true the user has interrupted and the presence follows the user.
 */

/** Severity vocabulary from §19. Only the top two warrant interrupting. */
export type AlertSeverity = 'informational' | 'important' | 'high' | 'critical';

export interface PresenceAlert {
  severity: AlertSeverity;
  text: string;
}

export interface PresenceInputs {
  /** From `useWebSocket`. `error` is a real fourth state in the store, and it
   *  means the same thing to an operator as `disconnected`: nothing arriving. */
  wsStatus: 'connected' | 'connecting' | 'disconnected' | 'error';
  /** From `useWebSocket`'s stale watchdog — the socket can be open and silent. */
  feedStale: boolean;
  /** The microphone is capturing right now. */
  micOpen: boolean;
  /** Speech synthesis is producing sound right now. */
  speaking: boolean;
  jobsRunning: number;
  jobsQueued: number;
  /** 0..1, or null when nobody has measured it. Null is not zero and not full. */
  riskHeadroom: number | null;
  alert: PresenceAlert | null;
  /** How many model vendors this deployment can actually reach. */
  providersReachable: number;
}

/**
 * Every state the machine can produce.
 *
 * Exported so the renderer can be checked against it: a state with no animation
 * is a presence that freezes at the moment it most needs to communicate.
 */
export const PRESENCE_STATES = [
  'idle',
  'listening',
  'thinking',
  'speaking',
  'explaining',
  'alerting',
  'degraded',
  'offline',
] as const;

export type PresenceState = (typeof PRESENCE_STATES)[number];

/** Semantic tone. The renderer picks colour from this, never from the state name. */
export type PresenceTone = 'ok' | 'info' | 'warn' | 'bad' | 'dead';

export interface Presence {
  state: PresenceState;
  /** One sentence saying why. Caption, announcement and speech all read this. */
  reason: string;
  tone: PresenceTone;
  /** 0..1 for the animation layer, so it never interprets business state itself. */
  intensity: number;
  /** False when risk headroom is unknown — so the ring is not drawn full for a
   *  number nobody has measured. */
  headroomKnown: boolean;
}

/** Below this fraction of the daily risk limit, the presence interrupts. */
const HEADROOM_ALARM = 0.1;

/** Severities that outrank a conversation in progress. §19. */
const INTERRUPTING = new Set<AlertSeverity>(['high', 'critical']);

/** Jobs at which the animation reads as fully busy. Beyond this it does not grow. */
const BUSY_SATURATION = 4;

export function derivePresence(input: PresenceInputs): Presence {
  const headroomKnown = input.riskHeadroom !== null && Number.isFinite(input.riskHeadroom);
  const inFlight = Math.max(0, input.jobsRunning) + Math.max(0, input.jobsQueued);
  const load = Math.min(1, inFlight / BUSY_SATURATION);

  const base = { headroomKnown };

  // 1 — Offline outranks everything. Nothing on screen can be trusted, so no
  //     other state would be honest to show.
  if (input.wsStatus === 'disconnected' || input.wsStatus === 'error') {
    return {
      ...base,
      state: 'offline',
      tone: 'dead',
      intensity: 0,
      reason: 'The connection is lost. Everything on screen is frozen and I am not going to guess at what has changed.',
    };
  }

  // 2 — A serious alert. This is the definition of something worth interrupting
  //     a person for, so it outranks the conversation.
  if (input.alert && INTERRUPTING.has(input.alert.severity)) {
    return {
      ...base,
      state: 'alerting',
      tone: 'bad',
      intensity: 1,
      reason: input.alert.text,
    };
  }

  if (headroomKnown && (input.riskHeadroom as number) <= HEADROOM_ALARM) {
    const pct = Math.round((input.riskHeadroom as number) * 100);
    return {
      ...base,
      state: 'alerting',
      tone: 'bad',
      intensity: 1,
      reason: `Only ${pct}% of today's risk limit is left. One more loss at this size ends the session.`,
    };
  }

  // 3 — Conversation. Listening beats speaking: if both are true the user has
  //     interrupted, and the presence follows the user rather than talking over
  //     them. That is what barge-in means (§17).
  if (input.micOpen) {
    return { ...base, state: 'listening', tone: 'info', intensity: 0.6, reason: 'Listening.' };
  }
  if (input.speaking) {
    return { ...base, state: 'speaking', tone: 'info', intensity: 0.8, reason: 'Speaking. Interrupt me any time.' };
  }

  // 4 — Degradation, below conversation. A stale price does not stop it hearing
  //     you, and degrading the microphone because a chart is old would be the
  //     tail wagging the dog.
  if (input.providersReachable <= 0) {
    return {
      ...base,
      state: 'degraded',
      tone: 'warn',
      intensity: 0.2,
      reason: 'No model vendor is reachable, so I cannot answer. Prices and risk limits are unaffected.',
    };
  }
  if (input.feedStale) {
    return {
      ...base,
      state: 'degraded',
      tone: 'warn',
      intensity: 0.2,
      reason: 'The market feed has gone stale. What you see is old — I am showing it rather than blanking it, but do not act on it yet.',
    };
  }

  // 5 — Working on something the operator asked for.
  if (inFlight > 0) {
    const noun = inFlight === 1 ? 'task' : 'tasks';
    return {
      ...base,
      state: 'thinking',
      tone: 'info',
      intensity: 0.35 + load * 0.5,
      reason: `Working on ${inFlight} ${noun}.`,
    };
  }

  // 6 — At rest, and saying what it checked. "All clear" without naming what was
  //     examined has told the operator nothing.
  return {
    ...base,
    state: 'idle',
    tone: 'ok',
    intensity: 0.12,
    reason: headroomKnown
      ? `Nothing needs you. ${Math.round((input.riskHeadroom as number) * 100)}% of today's risk limit is unused and the feed is live.`
      : 'Nothing needs you. The feed is live; risk headroom has not been measured yet.',
  };
}
