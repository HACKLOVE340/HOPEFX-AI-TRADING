/**
 * The layout engine is wired to the plane, not merely written.
 *
 * `hub/layout.ts` has thirty-two unit tests and would pass every one of them
 * while never being called by anything on screen. That is the shape of defect
 * F176 in this repository: a control that exists, reads correctly, and never
 * runs. `SurfaceView` read `surface.span` — the TIER's span — before this, so
 * a layout could decide anything it liked and the grid would ignore it.
 *
 * These tests drive the real panel through the real command box and read the
 * grid, so nothing passes unless the decision reaches a rendered style.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(), cancelSpeak: vi.fn(), startListening: vi.fn(), stopListening: vi.fn(),
    speaking: false, listening: false, sttSupported: false, transcript: '', status: null,
  }),
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

/** The rendered grid column of a surface, e.g. "span 4". */
function spanOf(name: RegExp): string {
  const section = screen.getByRole('region', { name }) as HTMLElement;
  return section.style.gridColumn;
}

beforeEach(() => {
  // jsdom reports 1024 by default, which is exactly the medium breakpoint and
  // would floor every span at 6 — hiding the differences these tests are about.
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('a named layout changes what is rendered', () => {
  it('gives every surface the same width in compare', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    // Under the tiers these differ: the chart is primary (6) and the headlines
    // are secondary (4). Comparing them means they must match.
    expect(spanOf(/gold price/i)).not.toBe(spanOf(/gold headlines/i));

    say('compare them side by side');
    await waitFor(() => expect(spanOf(/gold price/i)).toBe(spanOf(/gold headlines/i)));
  });

  it('makes everything narrow in the war room', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    say('open the war room');
    await waitFor(() => expect(spanOf(/gold price/i)).toBe('span 4'));
    expect(spanOf(/gold headlines/i)).toBe('span 4');
  });

  it('shows one surface and says how many are hidden in presentation', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    say('presentation mode');
    // A surface that vanishes with no trace is indistinguishable from one that
    // was closed, so the count has to be on screen.
    await waitFor(() => expect(screen.getByText(/2 hidden/)).toBeTruthy());
    expect(screen.queryByRole('region', { name: /gold headlines/i })).toBeNull();
  });

  it('keeps the named layout when the next surface opens', async () => {
    // The bug this guards: resolving the layout from the object count on every
    // command overrules what the operator asked for, and the plane rearranges
    // itself under someone who told it not to.
    await renderPresence();
    say('show me everything affecting gold');
    say('open the war room');
    await waitFor(() => expect(spanOf(/gold price/i)).toBe('span 4'));

    say('show me risk');
    await screen.findByRole('region', { name: /risk limits/i });
    expect(spanOf(/risk limits/i)).toBe('span 4');
  });

  it('returns to the default arrangement on "simplify this"', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    say('open the war room');
    await waitFor(() => expect(spanOf(/gold price/i)).toBe('span 4'));

    say('simplify this');
    say('show me everything affecting gold');
    // Primary again, not the war room's 4.
    await waitFor(() => expect(spanOf(/gold price/i)).toBe('span 6'));
  });
});

describe('the viewport overrules the layout', () => {
  it('collapses the war room to one column on a phone', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 375, configurable: true, writable: true });
    await renderPresence();
    say('show me everything affecting gold');
    say('open the war room');
    await waitFor(() => expect(spanOf(/gold price/i)).toBe('span 12'));
  });
});

describe('the operator can see which arrangement they are in', () => {
  it('names the layout in the rail', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    say('open the war room');
    await waitFor(() => expect(screen.getByText(/war room · 3 on the plane/i)).toBeTruthy());
  });
});
