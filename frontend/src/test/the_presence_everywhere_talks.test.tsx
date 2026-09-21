/**
 * Owner request: "anything that is displaying that have presence everywhere
 * should be head alone talking".
 *
 * It was not talking. `PresenceAnywhere` rendered
 * `<PresenceCore presence={presence} size={…} />` and passed no `utterance`,
 * no `speechProgress` and no `speaking`, so `mouthFor` was called with
 * `speaking=false` on every frame of every page and returned `{ openness: 0 }`.
 * The lip sync in `head.ts` was correct and the head that every operator
 * actually sees never used it — a control that exists, is documented, and is
 * never given its input.
 *
 * `hub/speechBus` is that input, and this file asserts the wiring: what the
 * platform is saying reaches the head on whatever page you are on, and stops
 * reaching it the moment synthesis does.
 *
 * `PresenceCore` is replaced here by a probe. jsdom has no canvas, so asserting
 * on the drawing is impossible and asserting on the props is the real contract
 * anyway — the drawing itself is proved in a browser.
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';

const seen: Record<string, unknown>[] = [];

vi.mock('../hub/PresenceCore', () => ({
  PresenceCore: (props: Record<string, unknown>) => {
    seen.push(props);
    return <div data-testid="presence-core" />;
  },
}));

import { PresenceAnywhere } from '../hub/PresenceAnywhere';
import { publishSpeech, resetSpeechBus } from '../hub/speechBus';

const NAV = [{ path: '/trade', label: 'Trade', group: 'core', plan: 'free', featureKey: 'trade' }];
const PRESENCE = {
  state: 'idle' as const,
  reason: 'Standing by',
  tone: 'info' as const,
  intensity: 0.2,
  headroomKnown: true,
};

function mount() {
  return render(
    <PresenceAnywhere
      pathname="/trade"
      nav={NAV}
      surface={[]}
      presence={PRESENCE}
      viewport={{ x: 0, y: 0, width: 1440, height: 900 }}
    />,
  );
}

const last = () => seen[seen.length - 1]!;

beforeEach(() => {
  cleanup();
  seen.length = 0;
  resetSpeechBus();
  try { localStorage.clear(); } catch { /* storage blocked; the component copes */ }
});

describe('the head on every page', () => {
  it('is silent when the platform is silent', () => {
    mount();
    expect(screen.getByTestId('presence-core')).toBeTruthy();
    expect(last().speaking).toBe(false);
    expect(last().utterance).toBe('');
  });

  it('opens its mouth when the platform speaks', () => {
    mount();
    act(() => { publishSpeech({ utterance: 'gold is bid', progress: null, speaking: true }); });
    expect(last().speaking).toBe(true);
    expect(last().utterance).toBe('gold is bid');
  });

  it('is given the MEASURED progress, and null when there is none', () => {
    // Null is what makes the mouth hold a steady shape instead of animating
    // from a clock. Passing zero here would pin it to the first character of
    // the utterance for the whole reply.
    mount();
    act(() => { publishSpeech({ utterance: 'gold is bid', progress: null, speaking: true }); });
    expect(last().speechProgress).toBeNull();
    act(() => { publishSpeech({ utterance: 'gold is bid', progress: 0.4, speaking: true }); });
    expect(last().speechProgress).toBeCloseTo(0.4, 6);
  });

  it('shuts its mouth when synthesis ends', () => {
    mount();
    act(() => { publishSpeech({ utterance: 'gold is bid', progress: 0.9, speaking: true }); });
    expect(last().speaking).toBe(true);
    act(() => { publishSpeech({ utterance: '', progress: null, speaking: false }); });
    expect(last().speaking).toBe(false);
    expect(last().utterance).toBe('');
  });

  it('catches an utterance already in progress when it mounts', () => {
    // Route changes remount this. A head that waited for the next word boundary
    // would be shut for the rest of a short reply.
    publishSpeech({ utterance: 'already talking', progress: 0.2, speaking: true });
    mount();
    expect(last().speaking).toBe(true);
    expect(last().utterance).toBe('already talking');
  });

  it('shows the head, not a figure — the presence everywhere is a head alone', () => {
    // §7's contextual transformation replaces the head with a chart or a
    // network when the subject IS that shape. That belongs on the AI Core
    // plane, where there is room for it and a panel beside it holding the real
    // numbers. In a 56-pixel dock it would be an unlabelled squiggle where a
    // face should be.
    mount();
    expect(last().representation ?? 'core').toBe('core');
  });

  it('gives the head the room to be a head', () => {
    // The head was drawn at 0.62 of the inner core's radius, which inside a
    // 56-pixel dock is a face about thirteen pixels across. The rings are kept
    // — they carry activity and risk headroom, and dropping them would be a
    // decoration removing data — but the head is scaled up to dominate.
    mount();
    expect(Number(last().headScale)).toBeGreaterThan(1.5);
  });
});
