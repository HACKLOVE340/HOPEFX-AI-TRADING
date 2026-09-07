/**
 * §17 real-time conversation: listening, endpointing, and what gets said aloud.
 *
 * ## The three failure modes this file is arranged around
 *
 * **A microphone that stays open.** Push-to-talk means the mic is open while a
 * key is held and shut the instant it is not. Every way of losing the key —
 * releasing it, the tab hiding, the window blurring, the component unmounting —
 * has to close it, because the one that does not is the one that leaves a
 * trading desk being recorded.
 *
 * **A transcript that claims words nobody said.** Interim recognition results
 * are guesses that get revised. Appending them builds a transcript full of
 * half-heard phrases attributed to the operator; the only safe handling is that
 * an interim result REPLACES the previous interim and only a final result ever
 * commits.
 *
 * **Speech that cannot be stopped.** Already covered by `voice.interruptible`,
 * and the modules here must not undo it: a wake word that re-opens the mic
 * mid-barge-in, or a preference that makes speech so slow it cannot be waited
 * out, are both new versions of the same problem.
 *
 * ## Pronunciation is not cosmetic here
 *
 * "XAUUSD" read letter by letter, or worse phonetically, is unintelligible in
 * the one situation where the presence speaks unprompted — an alert. A
 * dictionary that turns it into "gold" is the difference between a spoken alert
 * that works and one the operator has to read anyway.
 */

import { describe, it, expect, vi } from 'vitest';

import { pronounce, PRONUNCIATIONS } from '../hub/pronunciation';
import { VOICE_LIMITS, clampPreferences, describePreferences } from '../hub/voicePrefs';
import { Listening } from '../hub/listening';

// ── pronunciation ────────────────────────────────────────────────────────────

describe('pronunciation', () => {
  it('says the instrument rather than spelling it', () => {
    expect(pronounce('XAUUSD is holding 3400')).toMatch(/gold/i);
    expect(pronounce('XAUUSD is holding 3400')).not.toMatch(/XAUUSD/);
  });

  it('leaves ordinary words alone', () => {
    expect(pronounce('the trend is up')).toBe('the trend is up');
  });

  it('only replaces whole tokens, so it cannot corrupt a longer word', () => {
    // A naive replace turns "PIPELINE" into "point-in-percentageELINE".
    expect(pronounce('PIPELINE')).toBe('PIPELINE');
  });

  it('is case-insensitive on the term but keeps the sentence intact', () => {
    expect(pronounce('xauusd fell')).toMatch(/gold fell/i);
  });

  it('expands the financial terms that are unintelligible read aloud', () => {
    for (const term of ['P&L', 'SL', 'TP', 'DD']) {
      expect(PRONUNCIATIONS[term]).toBeTruthy();
      expect(pronounce(`check the ${term} now`)).not.toContain(term);
    }
  });

  it('never returns an empty string for non-empty input', () => {
    expect(pronounce('SL').length).toBeGreaterThan(0);
  });

  it('handles an empty utterance without throwing', () => {
    expect(pronounce('')).toBe('');
  });
});

// ── voice preferences ────────────────────────────────────────────────────────

describe('voice preferences', () => {
  it('accepts a sensible rate and pitch', () => {
    const prefs = clampPreferences({ rate: 1.2, pitch: 1.0, voice: 'en-GB' });
    expect(prefs.rate).toBe(1.2);
    expect(prefs.clamped).toEqual([]);
  });

  it('clamps a rate that would make an alert unintelligible', () => {
    // The presence speaks unprompted exactly once: when something is wrong.
    // A rate of 10 turns that into noise.
    const fast = clampPreferences({ rate: 10 });
    expect(fast.rate).toBe(VOICE_LIMITS.rate.max);
    expect(fast.clamped).toContain('rate');
  });

  it('clamps a rate so slow the operator cannot wait it out', () => {
    const slow = clampPreferences({ rate: 0.05 });
    expect(slow.rate).toBe(VOICE_LIMITS.rate.min);
    expect(slow.clamped).toContain('rate');
  });

  it('falls back to the default for a value that is not a number', () => {
    const prefs = clampPreferences({ rate: Number.NaN, pitch: Infinity });
    expect(prefs.rate).toBe(VOICE_LIMITS.rate.default);
    expect(prefs.pitch).toBe(VOICE_LIMITS.pitch.default);
    expect(prefs.clamped).toEqual(['rate', 'pitch']);
  });

  it('says what it changed, rather than silently correcting the operator', () => {
    const prefs = clampPreferences({ rate: 99 });
    expect(describePreferences(prefs)).toMatch(/rate/i);
  });

  it('reports an untouched preference set as unchanged', () => {
    expect(describePreferences(clampPreferences({}))).toMatch(/default/i);
  });
});

// ── listening: push-to-talk, continuous, endpointing, wake word ──────────────

function harness(options: Record<string, unknown> = {}) {
  const events: string[] = [];
  const mic = {
    start: () => events.push('start'),
    stop: () => events.push('stop'),
  };
  const listening = new Listening(mic, { now: () => 0, ...options });
  return { listening, mic, events };
}

describe('push to talk', () => {
  it('opens the microphone while the key is held', () => {
    const { listening, events } = harness();
    listening.press();
    expect(events).toEqual(['start']);
    expect(listening.open).toBe(true);
  });

  it('closes it the instant the key is released', () => {
    const { listening, events } = harness();
    listening.press();
    listening.release();
    expect(events).toEqual(['start', 'stop']);
    expect(listening.open).toBe(false);
  });

  it('ignores key repeat rather than restarting the microphone', () => {
    const { listening, events } = harness();
    listening.press();
    listening.press();
    listening.press();
    expect(events).toEqual(['start']);
  });

  it('closes on the tab being hidden, which is a key nobody released', () => {
    const { listening, events } = harness();
    listening.press();
    listening.interrupt('the tab was hidden');
    expect(events).toEqual(['start', 'stop']);
    expect(listening.open).toBe(false);
    expect(listening.lastReason).toMatch(/hidden/);
  });

  it('closes on dispose, so a navigation cannot leave it recording', () => {
    const { listening, events } = harness();
    listening.press();
    listening.dispose();
    expect(events).toEqual(['start', 'stop']);
  });

  it('is safe to release when nothing was held', () => {
    const { listening, events } = harness();
    listening.release();
    expect(events).toEqual([]);
  });

  it('stays shut after dispose, whatever is pressed afterwards', () => {
    const { listening, events } = harness();
    listening.dispose();
    listening.press();
    expect(events).toEqual([]);
    expect(listening.open).toBe(false);
  });
});

describe('continuous mode', () => {
  it('is off unless it is asked for, because it holds the microphone open', () => {
    const { listening } = harness();
    expect(listening.mode).toBe('push_to_talk');
  });

  it('refuses continuous mode without microphone consent', () => {
    const { listening, events } = harness();
    const result = listening.setMode('continuous', { micConsent: false });
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/consent/i);
    expect(events).toEqual([]);
  });

  it('opens and holds the microphone in continuous mode once consented', () => {
    const { listening, events } = harness();
    listening.setMode('continuous', { micConsent: true });
    expect(events).toEqual(['start']);
    expect(listening.open).toBe(true);
  });

  it('closes the microphone when leaving continuous mode', () => {
    const { listening, events } = harness();
    listening.setMode('continuous', { micConsent: true });
    listening.setMode('push_to_talk', { micConsent: true });
    expect(events).toEqual(['start', 'stop']);
  });

  it('closes the microphone the moment consent is withdrawn', () => {
    // A revocation that waits for the next mode change is not a revocation.
    const { listening, events } = harness();
    listening.setMode('continuous', { micConsent: true });
    listening.consentWithdrawn();
    expect(events).toEqual(['start', 'stop']);
    expect(listening.mode).toBe('push_to_talk');
  });
});

describe('interim results', () => {
  it('replaces the interim rather than appending it', () => {
    // Appending builds a transcript of half-heard phrases attributed to the
    // operator: "sell gold sell gold now sell gold now please".
    const { listening } = harness();
    listening.press();
    listening.heard({ text: 'sell', final: false });
    listening.heard({ text: 'sell gold', final: false });
    listening.heard({ text: 'sell gold now', final: false });
    expect(listening.interim).toBe('sell gold now');
    expect(listening.committed).toEqual([]);
  });

  it('commits only a final result', () => {
    const { listening } = harness();
    listening.press();
    listening.heard({ text: 'sell gold', final: false });
    listening.heard({ text: 'sell gold now', final: true });
    expect(listening.committed).toEqual(['sell gold now']);
    expect(listening.interim).toBe('');
  });

  it('drops the interim when the microphone closes without a final result', () => {
    // A half-heard phrase left on screen after the key is released reads as
    // something the operator said.
    const { listening } = harness();
    listening.press();
    listening.heard({ text: 'sell gol', final: false });
    listening.release();
    expect(listening.interim).toBe('');
    expect(listening.committed).toEqual([]);
  });

  it('ignores anything heard while the microphone is shut', () => {
    const { listening } = harness();
    listening.heard({ text: 'sell everything', final: true });
    expect(listening.committed).toEqual([]);
  });
});

describe('turn detection', () => {
  it('endpoints after the operator stops speaking', () => {
    let clock = 0;
    const { listening } = harness({ now: () => clock, silenceMs: 800 });
    listening.setMode('continuous', { micConsent: true });
    listening.heard({ text: 'what is gold doing', final: false });

    clock = 500;
    expect(listening.endpointed()).toBe(false);
    clock = 1_200;
    expect(listening.endpointed()).toBe(true);
  });

  it('does not endpoint while speech is still arriving', () => {
    let clock = 0;
    const { listening } = harness({ now: () => clock, silenceMs: 800 });
    listening.setMode('continuous', { micConsent: true });
    listening.heard({ text: 'what is', final: false });
    clock = 700;
    listening.heard({ text: 'what is gold', final: false });
    clock = 1_300;
    expect(listening.endpointed()).toBe(false);
  });

  it('does not endpoint on silence that was never preceded by speech', () => {
    // Otherwise an open microphone in a quiet room fires a turn every second.
    let clock = 0;
    const { listening } = harness({ now: () => clock, silenceMs: 800 });
    listening.setMode('continuous', { micConsent: true });
    clock = 10_000;
    expect(listening.endpointed()).toBe(false);
  });

  it('commits the pending interim when it endpoints', () => {
    let clock = 0;
    const { listening } = harness({ now: () => clock, silenceMs: 800 });
    listening.setMode('continuous', { micConsent: true });
    listening.heard({ text: 'what is gold doing', final: false });
    clock = 2_000;
    listening.endpointed();
    expect(listening.committed).toEqual(['what is gold doing']);
  });
});

describe('wake word', () => {
  it('is off by default, because it needs the microphone held open', () => {
    const { listening } = harness();
    expect(listening.wakeWord).toBeNull();
  });

  it('refuses to arm without continuous microphone consent', () => {
    const { listening } = harness();
    const armed = listening.armWakeWord('hopefx', { micConsent: false });
    expect(armed.allowed).toBe(false);
    expect(armed.reason).toMatch(/consent/i);
  });

  it('fires when the phrase is heard', () => {
    const { listening } = harness();
    listening.armWakeWord('hopefx', { micConsent: true });
    expect(listening.heard({ text: 'hey hopefx what is gold doing', final: false }).woke).toBe(true);
  });

  it('does not fire on a phrase that merely contains the letters', () => {
    const { listening } = harness();
    listening.armWakeWord('hopefx', { micConsent: true });
    expect(listening.heard({ text: 'the hopefxtrading desk', final: false }).woke).toBe(false);
  });

  it('disarms the moment consent is withdrawn', () => {
    const { listening } = harness();
    listening.armWakeWord('hopefx', { micConsent: true });
    listening.consentWithdrawn();
    expect(listening.wakeWord).toBeNull();
  });

  it('refuses a wake phrase too short to be safe', () => {
    // "hi" fires on half of ordinary speech, which is an always-on microphone
    // with extra steps.
    const { listening } = harness();
    const armed = listening.armWakeWord('hi', { micConsent: true });
    expect(armed.allowed).toBe(false);
    expect(armed.reason).toMatch(/short/i);
  });
});

describe('the listening state is reportable', () => {
  it('says what it is doing and why, at any moment', () => {
    const { listening } = harness();
    listening.press();
    const snapshot = listening.snapshot();
    expect(snapshot.open).toBe(true);
    expect(snapshot.mode).toBe('push_to_talk');
    expect(snapshot.reason.length).toBeGreaterThan(0);
  });

  it('an open microphone is always visible in the snapshot', () => {
    // A microphone open with no indication is the defect the whole module is
    // arranged against.
    const { listening } = harness();
    listening.setMode('continuous', { micConsent: true });
    expect(listening.snapshot().open).toBe(true);
  });
});

describe('arming a wake word is visible', () => {
  it('opens the microphone, because a wake word that does not listen cannot fire', () => {
    // Otherwise it is a control that exists, reads correctly and never runs.
    const { listening, events } = harness();
    listening.armWakeWord('hopefx', { micConsent: true });
    expect(events).toEqual(['start']);
    expect(listening.snapshot().open).toBe(true);
    expect(listening.snapshot().reason).toMatch(/wake word/i);
  });

  it('closes it again when consent is withdrawn', () => {
    const { listening, events } = harness();
    listening.armWakeWord('hopefx', { micConsent: true });
    listening.consentWithdrawn();
    expect(events).toEqual(['start', 'stop']);
    expect(listening.snapshot().open).toBe(false);
  });

  it('does not open the microphone when arming is refused', () => {
    const { listening, events } = harness();
    listening.armWakeWord('hi', { micConsent: true });
    listening.armWakeWord('hopefx', { micConsent: false });
    expect(events).toEqual([]);
  });
});
