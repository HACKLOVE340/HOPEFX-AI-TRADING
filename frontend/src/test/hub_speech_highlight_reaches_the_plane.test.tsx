/**
 * The AI points at what it is talking about — driven through the real panel.
 *
 * `hub/reference.ts` has seventeen unit tests and would pass every one while
 * nothing on screen ever changed colour. The difference between an assistant
 * that reads a paragraph at you and one standing in front of the screen
 * pointing at things is entirely in this wiring.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

/**
 * A voice mock whose `spokenText` and `speechProgress` we drive by hand — the
 * two values the real hook fills in from an `<audio>` element's playback
 * position or a `boundary` event's character index.
 */
const voiceState = {
  spokenText: '',
  speechProgress: null as number | null,
};
let rerenderVoice: (() => void) | null = null;

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => {
    const { useState, useEffect } = require('react') as typeof import('react');
    const [, bump] = useState(0);
    useEffect(() => {
      rerenderVoice = () => bump((n) => n + 1);
      return () => {
        rerenderVoice = null;
      };
    });
    return {
      speak: vi.fn(), cancelSpeak: vi.fn(), startListening: vi.fn(), stopListening: vi.fn(),
      speaking: voiceState.spokenText !== '', listening: false, sttSupported: false,
      transcript: '', status: null,
      spokenText: voiceState.spokenText,
      speechProgress: voiceState.speechProgress,
    };
  },
}));

async function renderPresence() {
  const { useStore } = await import('../store');
  useStore.setState({ wsStatus: 'connected' });
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

/** Make the AI "speak" `text`, at `progress` through it (null = unmeasured). */
function speaks(text: string, progress: number | null) {
  voiceState.spokenText = text;
  voiceState.speechProgress = progress;
  rerenderVoice?.();
}

function highlighted(): string[] {
  return Array.from(document.querySelectorAll('[data-spoken-about="true"]')).map(
    (el) => el.getAttribute('aria-label') ?? '',
  );
}

beforeEach(() => {
  voiceState.spokenText = '';
  voiceState.speechProgress = null;
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('the panel being talked about lights up', () => {
  it('highlights the surface the current sentence names', async () => {
    await renderPresence();
    // Just the chart, so the assertion is about one panel. The three-gold-panel
    // case is asserted separately below.
    say('show me gold');
    say('show me risk');
    await screen.findByRole('region', { name: /gold price/i });

    speaks('Gold is up two dollars. Risk headroom is thin.', 0.05);
    await waitFor(() => expect(highlighted()).toEqual(['Gold price']));

    speaks('Gold is up two dollars. Risk headroom is thin.', 0.9);
    await waitFor(() => expect(highlighted()).toEqual(['Risk limits and headroom']));
  });

  it('covers every panel the utterance mentions when progress is unmeasured', async () => {
    // Not the first sentence — null is "nobody measured this", not zero.
    await renderPresence();
    say('show me gold');
    say('show me risk');
    await screen.findByRole('region', { name: /gold price/i });

    speaks('Gold is up. Risk headroom is thin.', null);
    await waitFor(() => expect(highlighted().sort()).toEqual(['Gold price', 'Risk limits and headroom']));
  });

  it('lights every gold panel when three of them are open and gold is the subject', async () => {
    // Not over-matching: "show me everything affecting gold" opens the chart,
    // the headlines and the exposure, and a sentence about gold is about all
    // three. Highlighting only the chart would answer a smaller question.
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    speaks('Gold is up two dollars.', 0.5);
    await waitFor(() =>
      expect(highlighted().sort()).toEqual(['Gold exposure', 'Gold headlines', 'Gold price']),
    );
  });

  it('clears the highlight when the AI stops talking', async () => {
    await renderPresence();
    say('show me risk');
    await screen.findByRole('region', { name: /risk limits/i });

    speaks('Risk headroom is thin.', 0.5);
    await waitFor(() => expect(highlighted()).toHaveLength(1));

    speaks('', null);
    await waitFor(() => expect(highlighted()).toHaveLength(0));
  });

  it('highlights nothing when the sentence names nothing on the plane', async () => {
    await renderPresence();
    say('show me risk');
    await screen.findByRole('region', { name: /risk limits/i });

    speaks('I am not sure I follow.', 0.5);
    await waitFor(() => expect(highlighted()).toHaveLength(0));
  });
});

describe('the highlight is not colour alone', () => {
  it('marks the panel for a screen reader too', async () => {
    // §27: colour is never the only indicator. A border change tells a
    // screen-reader user nothing about which panel is being described.
    await renderPresence();
    say('show me risk');
    await screen.findByRole('region', { name: /risk limits/i });

    speaks('Risk headroom is thin.', 0.5);
    await waitFor(() => {
      const panel = screen.getByRole('region', { name: /risk limits/i });
      expect(panel.getAttribute('aria-current')).toBe('true');
    });
  });

  it('says so in words on the panel itself', async () => {
    await renderPresence();
    say('show me risk');
    await screen.findByRole('region', { name: /risk limits/i });

    speaks('Risk headroom is thin.', 0.5);
    await waitFor(() => expect(screen.getByText(/speaking about/i)).toBeTruthy());
  });
});

describe('AI attention and operator focus are different things', () => {
  it('does not make a spoken-about panel look selected', async () => {
    // Merging them would mean the AI mentioning a panel reads as the operator
    // having chosen it, and closing "the focused panel" would then depend on
    // who was talking.
    await renderPresence();
    say('show me everything affecting gold');
    say('show me risk');
    await screen.findByRole('region', { name: /gold price/i });

    speaks('Risk headroom is thin.', 0.5);
    await waitFor(() => expect(highlighted()).toEqual(['Risk limits and headroom']));

    // Nothing was focused by the operator, so the layout must not have switched
    // to focus mode.
    expect(screen.queryByText(/^focus ·/i)).toBeNull();
  });
});
