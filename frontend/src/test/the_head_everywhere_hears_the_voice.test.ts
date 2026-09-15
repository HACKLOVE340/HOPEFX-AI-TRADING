/**
 * The presence on every page was mute.
 *
 * `PresenceAnywhere` rendered `<PresenceCore presence={presence} size={…} />`
 * and passed no `utterance`, no `speechProgress` and no `speaking`. So
 * `mouthFor` was called with `speaking=false` on every frame, on every page,
 * and returned `{ openness: 0 }` — the head's mouth was painted shut for the
 * life of the component while the assistant was talking out loud two hundred
 * pixels away.
 *
 * Nothing was broken in `head.ts`: the lip sync worked, and `AICore` drove it
 * correctly. The defect was that speech was per-component state inside
 * `useVoice`, so a head rendered by a different component in a different part
 * of the tree had no way to learn that synthesis had started. That is the
 * dead-control shape: a control that exists, is correct, and is never given
 * the input it needs to run.
 *
 * `speechBus` is that input. This file holds the rules it must keep.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// The cloud probe must answer "unavailable" so `speak` falls back to Web
// Speech, which the fake below provides. No test reaches the network.
vi.mock('../hooks/useApi', () => ({
  voiceApi: {
    status: vi.fn().mockResolvedValue({ data: { tts_available: false, stt_available: false } }),
    tts: vi.fn(),
    stt: vi.fn(),
  },
}));

import { useVoice } from '../hooks/useVoice';

import {
  SILENT,
  currentSpeech,
  publishSpeech,
  resetSpeechBus,
  subscribeSpeech,
} from '../hub/speechBus';

beforeEach(() => resetSpeechBus());

describe('the speech bus', () => {
  it('starts silent', () => {
    expect(currentSpeech()).toEqual(SILENT);
  });

  it('gives a new subscriber the CURRENT frame, not the next one', () => {
    // A head that mounts mid-utterance must open its mouth on its first frame.
    // Waiting for the next publish means the mouth is shut for whatever is left
    // of the sentence, which on a short reply is the whole reply.
    publishSpeech({ utterance: 'gold is bid', progress: 0.5, speaking: true });
    const seen = vi.fn();
    subscribeSpeech(seen);
    expect(seen).toHaveBeenCalledWith({ utterance: 'gold is bid', progress: 0.5, speaking: true });
  });

  it('delivers to every subscriber', () => {
    const a = vi.fn();
    const b = vi.fn();
    subscribeSpeech(a);
    subscribeSpeech(b);
    a.mockClear();
    b.mockClear();
    publishSpeech({ utterance: 'hello', progress: null, speaking: true });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it('stops delivering after unsubscribe', () => {
    const seen = vi.fn();
    const off = subscribeSpeech(seen);
    off();
    seen.mockClear();
    publishSpeech({ utterance: 'hello', progress: null, speaking: true });
    expect(seen).not.toHaveBeenCalled();
  });

  it('one broken subscriber does not mute the others', () => {
    // Every page carries a head. A thrown error in one of them must not stop
    // the rest of the app from learning the assistant is speaking.
    const broken = vi.fn(() => { throw new Error('render failed'); });
    const working = vi.fn();
    subscribeSpeech(broken);
    subscribeSpeech(working);
    working.mockClear();
    expect(() => publishSpeech({ utterance: 'hi', progress: null, speaking: true })).not.toThrow();
    expect(working).toHaveBeenCalledTimes(1);
  });

  it('does not re-notify for an identical frame', () => {
    // Cloud TTS fires `ontimeupdate` several times a second and Web Speech
    // fires `boundary` per word. Re-rendering every head in the app for a frame
    // that did not change is how a decorative canvas becomes a frame-rate bug.
    publishSpeech({ utterance: 'hello', progress: 0.25, speaking: true });
    const seen = vi.fn();
    subscribeSpeech(seen);
    seen.mockClear();
    publishSpeech({ utterance: 'hello', progress: 0.25, speaking: true });
    expect(seen).not.toHaveBeenCalled();
    publishSpeech({ utterance: 'hello', progress: 0.26, speaking: true });
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it('silence clears the utterance and the progress together', () => {
    // The hook already refuses to leave a stale utterance beside a live
    // progress figure. The bus is a second place that could reintroduce it, so
    // it enforces the same rule rather than trusting every publisher.
    publishSpeech({ utterance: 'gold is bid', progress: 0.5, speaking: true });
    publishSpeech({ utterance: 'gold is bid', progress: 0.5, speaking: false });
    expect(currentSpeech()).toEqual(SILENT);
  });

  it('a progress that is not a number is not measured, and is not zero', () => {
    // `mouthFor` reads null as "speaking, nothing measured" and holds a steady
    // shape. Reading NaN as 0 would put the mouth at index 0 of the string for
    // the whole utterance — animated, precise, and wrong.
    publishSpeech({ utterance: 'gold', progress: Number.NaN, speaking: true });
    expect(currentSpeech().progress).toBeNull();
  });

  it('clamps a progress outside 0..1', () => {
    publishSpeech({ utterance: 'gold', progress: 1.4, speaking: true });
    expect(currentSpeech().progress).toBe(1);
    publishSpeech({ utterance: 'gold', progress: -0.3, speaking: true });
    expect(currentSpeech().progress).toBe(0);
  });

  it('speaking with no text is silence', () => {
    // `speak('')` returns early in the hook without starting synthesis. A bus
    // frame claiming speech with nothing to say would animate a mouth against
    // an utterance that was never spoken.
    publishSpeech({ utterance: '   ', progress: null, speaking: true });
    expect(currentSpeech()).toEqual(SILENT);
  });
});

// ── the publisher ────────────────────────────────────────────────────────────

/**
 * jsdom ships no Web Speech API, so `useVoice` reports unsupported and every
 * method is a no-op — which is the right default for the rest of the suite and
 * useless for proving that speech reaches the bus. These tests install a
 * minimal synthesis engine that behaves like Chromium's: `speak` holds the
 * utterance and the test fires `boundary` and `end` on it by hand, so what is
 * asserted is the hook's reaction to real engine events rather than to a timer.
 */
class FakeUtterance {
  text: string;
  lang = '';
  onboundary: ((e: { charIndex: number }) => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

function installFakeSynthesis(): { spoken: FakeUtterance[] } {
  const spoken: FakeUtterance[] = [];
  (globalThis as unknown as Record<string, unknown>).SpeechSynthesisUtterance = FakeUtterance;
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: {
      speak: (u: FakeUtterance) => { spoken.push(u); },
      cancel: () => { /* nothing queued in the fake */ },
    },
  });
  return { spoken };
}

describe('useVoice publishes to the bus', () => {
  let restore: (() => void) | null = null;

  beforeEach(() => {
    resetSpeechBus();
    const original = Object.getOwnPropertyDescriptor(window, 'speechSynthesis');
    const originalCtor = (globalThis as unknown as Record<string, unknown>).SpeechSynthesisUtterance;
    installFakeSynthesis();
    restore = () => {
      if (original) Object.defineProperty(window, 'speechSynthesis', original);
      else delete (window as unknown as Record<string, unknown>).speechSynthesis;
      (globalThis as unknown as Record<string, unknown>).SpeechSynthesisUtterance = originalCtor;
    };
  });

  afterEach(() => { restore?.(); restore = null; });

  async function speakAndSettle(result: { current: ReturnType<typeof useVoice> }, text: string) {
    await act(async () => {
      result.current.speak(text);
      // `speak` probes for cloud TTS through a promise before falling back.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it('announces the utterance the ENGINE was given, not the Markdown', async () => {
    // `speechText` flattens Markdown before synthesis. The mouth is driven by a
    // character index INTO that string, so publishing the raw Markdown would
    // index a different string from the one being spoken and put the mouth on
    // the wrong character for the whole reply.
    const { result } = renderHook(() => useVoice());
    await speakAndSettle(result, '**Gold** is _bid_');
    expect(currentSpeech().speaking).toBe(true);
    expect(currentSpeech().utterance).toBe('Gold is bid');
  });

  it('publishes the engine-reported progress as a fraction', async () => {
    const { spoken } = installFakeSynthesis();
    const { result } = renderHook(() => useVoice());
    await speakAndSettle(result, 'gold is bid');
    const utterance = spoken[spoken.length - 1];
    expect(utterance).toBeDefined();

    await act(async () => { utterance!.onboundary?.({ charIndex: 5 }); });
    expect(currentSpeech().progress).toBeCloseTo(5 / 'gold is bid'.length, 5);
  });

  it('falls silent when the engine reports the end', async () => {
    const { spoken } = installFakeSynthesis();
    const { result } = renderHook(() => useVoice());
    await speakAndSettle(result, 'gold is bid');
    const utterance = spoken[spoken.length - 1];
    expect(currentSpeech().speaking).toBe(true);
    await act(async () => { utterance!.onend?.(); });
    expect(currentSpeech()).toEqual(SILENT);
  });

  it('falls silent when the engine errors', async () => {
    // A failed synthesis that left the bus speaking would animate a mouth
    // against an utterance nobody can hear — §22's decorative "live" value,
    // wearing a face.
    const { spoken } = installFakeSynthesis();
    const { result } = renderHook(() => useVoice());
    await speakAndSettle(result, 'gold is bid');
    const utterance = spoken[spoken.length - 1];
    expect(currentSpeech().speaking).toBe(true);
    await act(async () => { utterance!.onerror?.(); });
    expect(currentSpeech()).toEqual(SILENT);
  });

  it('falls silent when the caller cancels', async () => {
    const { result } = renderHook(() => useVoice());
    await speakAndSettle(result, 'gold is bid');
    expect(currentSpeech().speaking).toBe(true);
    await act(async () => { result.current.cancelSpeak(); });
    expect(currentSpeech()).toEqual(SILENT);
  });

  it('falls silent when the speaking component unmounts', async () => {
    // The hook already cancels synthesis on unmount. Without this the bus would
    // keep the last frame forever and every head in the app would hold an open
    // mouth over a dead utterance.
    const { result, unmount } = renderHook(() => useVoice());
    await speakAndSettle(result, 'gold is bid');
    expect(currentSpeech().speaking).toBe(true);
    await act(async () => { unmount(); });
    expect(currentSpeech()).toEqual(SILENT);
  });
});
