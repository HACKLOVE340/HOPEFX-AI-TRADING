/**
 * §9 relative reference, driven through the real panel.
 *
 * `hub_scene_reference.test.ts` proves `sceneFrom` and `resolveReference`
 * decide correctly in isolation. That is not the claim the registry makes.
 * The §9 rows were staged with "the model exists and nothing populates it",
 * and the only assertion that changes is one where a real `PresenceStage`
 * measures real panels and a real command resolves against them.
 *
 * ## The defect this starts from
 *
 * `workspace.resolve` matches a phrase against what a panel MEANS. It returns
 * null for "the one on the right", and the focus path passed that null
 * straight to `workspace.focus(null)` — so asking to focus a panel by its
 * position silently UNFOCUSED everything and said nothing about it. The
 * operator gets no panel, no error, and no reason.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(),
    cancelSpeak: vi.fn(),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    speaking: false,
    listening: false,
    sttSupported: false,
    transcript: '',
    status: null,
    spokenText: '',
    speechProgress: null,
  }),
}));

async function renderPresence() {
  const { useStore } = await import('../store');
  useStore.setState({
    wsStatus: 'connected',
    priceHistory: { 'XAU/USD': Array.from({ length: 100 }, (_, i) => 2000 + i) },
  } as never);
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

/** Panel ids in document order, which is the order the scene assigns z from. */
function panelIds(): string[] {
  return Array.from(document.querySelectorAll('[data-surface-id]'))
    .map((el) => el.getAttribute('data-surface-id') ?? '')
    .filter(Boolean);
}

/** Each panel's meaning, in the same order as `panelIds`. */
function panelMeanings(): string[] {
  return Array.from(document.querySelectorAll('[data-surface-id] h3')).map((el) => el.textContent ?? '');
}

function focusedId(): string | null {
  const el = document.querySelector('[data-surface-id][data-focused="true"]');
  return el?.getAttribute('data-surface-id') ?? null;
}

/**
 * jsdom lays nothing out, so every rect is zero and `sceneFrom` — correctly —
 * places nothing. Give each panel a rectangle in document order, left to right,
 * so the relative questions have something real to answer against.
 */
function layOutPanelsInARow(): void {
  let x = 0;
  for (const el of Array.from(document.querySelectorAll('[data-surface-id]'))) {
    const at = x;
    (el as HTMLElement).getBoundingClientRect = () =>
      ({ x: at, y: 0, width: 300, height: 200, top: 0, left: at, right: at + 300, bottom: 200, toJSON: () => ({}) }) as DOMRect;
    x += 320;
  }
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('§9 the scene is populated by what is actually on screen', () => {
  it('resolves "focus on the one to the right" against measured position', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    // Exactly three, not "more than one": a partial render satisfies the looser
    // condition and the plane is still re-ordering, so the ids captured next
    // belong to a layout that no longer exists a frame later.
    await waitFor(() => expect(panelIds()).toHaveLength(3));

    const ids = panelIds();
    layOutPanelsInARow();
    // Re-measure with the laid-out rectangles.
    fireEvent(window, new Event('resize'));

    say(`focus on ${panelMeanings()[0]}`);
    await waitFor(() => expect(focusedId()).toBe(ids[0]));

    say('focus on the one to the right');
    // The assertion that fails on the pre-fix tree: without the scene the
    // phrase resolves to nothing and focus is cleared.
    await waitFor(() => expect(focusedId()).toBe(ids[1]));
  });

  it('says why rather than clearing focus when the phrase cannot be resolved', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    // Exactly three, not "more than one": a partial render satisfies the looser
    // condition and the plane is still re-ordering, so the ids captured next
    // belong to a layout that no longer exists a frame later.
    await waitFor(() => expect(panelIds()).toHaveLength(3));

    const ids = panelIds();
    layOutPanelsInARow();
    fireEvent(window, new Event('resize'));

    say(`focus on ${panelMeanings()[0]}`);
    await waitFor(() => expect(focusedId()).toBe(ids[0]));

    // Nothing is to the left of the leftmost panel, and the reference must not
    // wrap round to the far right — that would move the operator's attention
    // to a panel they were not looking at.
    say('focus on the one to the left');
    await waitFor(() => expect(screen.getByLabelText(/recent conversation/i).textContent).toMatch(/nothing to the left/i));
    // Focus is unchanged: a refusal does not also take away what they had.
    expect(focusedId()).toBe(ids[0]);
  });
});
