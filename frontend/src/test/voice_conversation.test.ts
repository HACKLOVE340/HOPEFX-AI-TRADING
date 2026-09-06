/**
 * Interruptible conversation — §17.
 *
 * `useVoice` already does speech-to-text and text-to-speech. What it does not do
 * is let you cut in. That is the whole difference between a conversation and a
 * command line: an assistant you cannot interrupt is one you have to wait out,
 * and an assistant reading a forty-second briefing you no longer want is worse
 * than one that stayed silent.
 *
 * This is the turn manager. Deliberately not a React hook: it is a small state
 * machine with an injectable clock and injectable speech engines, so every
 * transition is testable without a microphone, a browser, or a timer.
 */

import { describe, it, expect, vi } from 'vitest';
import { ConversationTurn } from '../hub/conversation';

function engines() {
  const spoken: string[] = [];
  const calls = { cancels: 0, starts: 0, stops: 0 };
  let onEnd: (() => void) | null = null;
  return {
    spoken,
    calls,
    finishSpeaking: () => onEnd?.(),
    tts: {
      speak: (text: string, done: () => void) => {
        spoken.push(text);
        calls.starts += 1;
        onEnd = done;
      },
      cancel: () => {
        calls.cancels += 1;
        onEnd = null;
      },
    },
    stt: {
      start: () => { calls.starts += 1; },
      stop: () => { calls.stops += 1; },
    },
  };
}

describe('barge-in', () => {
  it('stops speaking the moment the user starts talking', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);

    turn.say('A long briefing about the gold market that nobody wants to hear');
    expect(turn.state).toBe('speaking');

    turn.userStartedSpeaking();
    expect(e.calls.cancels).toBe(1);
    expect(turn.state).toBe('listening');
  });

  it('keeps what it had already said rather than pretending it never spoke', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('Gold is range-bound and volume is thin');
    turn.userStartedSpeaking();
    expect(turn.lastUtterance).toBe('Gold is range-bound and volume is thin');
  });

  it('records that it was interrupted, so the AI can acknowledge it', () => {
    // "You cut me off" is context. Losing it makes the next turn read as a
    // non-sequitur.
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('something long');
    turn.userStartedSpeaking();
    expect(turn.wasInterrupted).toBe(true);
  });

  it('does not report an interruption when it finished naturally', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('short answer');
    e.finishSpeaking();
    expect(turn.wasInterrupted).toBe(false);
    expect(turn.state).toBe('idle');
  });

  it('is safe to interrupt when it is not speaking', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.userStartedSpeaking();
    expect(turn.state).toBe('listening');
    expect(e.calls.cancels).toBe(0);
  });
});

describe('turn taking', () => {
  it('goes back to idle when the user stops and says nothing', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.userStartedSpeaking();
    turn.userStoppedSpeaking('');
    expect(turn.state).toBe('idle');
  });

  it('hands a final transcript to the caller exactly once', () => {
    const heard = vi.fn();
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt, { onUtterance: heard });
    turn.userStartedSpeaking();
    turn.userStoppedSpeaking('what changed overnight');
    expect(heard).toHaveBeenCalledTimes(1);
    expect(heard).toHaveBeenCalledWith('what changed overnight');
  });

  it('will not speak over itself', () => {
    // Two answers arriving at once is a real case — two jobs finishing. The
    // second must cancel the first rather than overlap it.
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('first answer');
    turn.say('second answer');
    expect(e.calls.cancels).toBe(1);
    expect(e.spoken).toEqual(['first answer', 'second answer']);
  });

  it('refuses to speak an empty string', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('   ');
    expect(e.spoken).toEqual([]);
    expect(turn.state).toBe('idle');
  });
});

describe('muted', () => {
  it('still reports what it would have said, so the caption is unaffected', () => {
    // Muting is an audio preference, not a decision to withhold information.
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt, { muted: true });
    turn.say('Gold is range-bound');
    expect(e.spoken).toEqual([]);
    expect(turn.lastUtterance).toBe('Gold is range-bound');
    expect(turn.state).toBe('idle');
  });
});

describe('transcript', () => {
  it('keeps both sides in order', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('Morning. Nothing needs you.');
    e.finishSpeaking();
    turn.userStartedSpeaking();
    turn.userStoppedSpeaking('what about overnight');
    turn.say('It held a narrow range.');

    expect(turn.transcript.map((t) => [t.who, t.text])).toEqual([
      ['ai', 'Morning. Nothing needs you.'],
      ['user', 'what about overnight'],
      ['ai', 'It held a narrow range.'],
    ]);
  });

  it('is bounded, so a long session does not grow without limit', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt, { maxTranscript: 4 });
    for (let i = 0; i < 20; i++) {
      turn.say(`line ${i}`);
      e.finishSpeaking();
    }
    expect(turn.transcript.length).toBe(4);
    expect(turn.transcript[3]?.text).toBe('line 19');
  });

  it('marks an interrupted line so the record is honest about it', () => {
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('a long thing');
    turn.userStartedSpeaking();
    expect(turn.transcript[0]?.interrupted).toBe(true);
  });
});

describe('cleanup', () => {
  it('stops everything on dispose', () => {
    // A page navigated away from while the microphone is open is a privacy
    // problem, not a tidiness one.
    const e = engines();
    const turn = new ConversationTurn(e.tts, e.stt);
    turn.say('talking');
    turn.userStartedSpeaking();
    turn.dispose();
    expect(e.calls.stops).toBeGreaterThan(0);
    expect(turn.state).toBe('idle');
  });
});
