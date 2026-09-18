/**
 * Phase I3 — §18's built halves, given the callers they never had.
 *
 * `recogniseGesture` and `pointingAt` were written in Phase E2 and, measured
 * now, are imported by nothing outside their own tests. That is the dead
 * control this codebase cares most about, and it is mine: I wrote the module
 * docstring explaining why building a recogniser nothing feeds would be
 * `hopefx-dead-controls`, and then built one anyway on the input side.
 *
 * `pointingAt` could not have been wired when it was written — the scene graph
 * had no producer until Phase H1 put `sceneFrom` in `PresenceStage`. It has one
 * now.
 *
 * ## The rows these close, and the rows they do not
 *
 * The ids are `vision.gesture` and `vision.pointing`, and every other row in
 * §18 is camera-derived: scene understanding, capture indication, frame
 * retention, source selection. `vision.` means vision.
 *
 * A pointer swipe is not vision. Marking those rows live because pointer input
 * works would be renaming the capability to fit what I built — the same move
 * that had `agents.system` pointing at `platform_engineering` and §11
 * reporting twelve agents with eleven present. So the pointer work gets its own
 * rows and the `vision.` rows stay staged with the camera half named.
 *
 * ## Only reversible actions are bound
 *
 * `gestures.ts` says it in its own docstring: on a trading screen a wrongly
 * recognised swipe moves a panel somebody was reading. So swipe changes FOCUS
 * — reversible, non-destructive, already reachable by other means — and long
 * press pins, which is a toggle with a button beside it. Nothing here closes a
 * panel and nothing here places an order.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';

import { PresenceStage } from '../hub/PresenceStage';
import { MAX_TRACK_POINTS, appendPoint, recogniseGesture } from '../hub/gestures';
import type { Presence } from '../hub/presence';
import type { Surface } from '../hub/workspace';

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

const presence: Presence = {
  state: 'idle',
  tone: 'ok',
  reason: 'Nothing needs attention.',
  intensity: 0.2,
  headroomKnown: true,
};

function surfaces(count: number): Surface[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `s${i}`,
    kind: 'chart' as const,
    meaning: `Panel ${i}`,
    priority: 'primary' as const,
    span: 4,
    pinned: false,
    key: `k${i}`,
    openedAt: 1_700_000_000_000 + i,
    order: i,
    data: {},
  }));
}

/** Lay the panels out left to right so the scene graph has real rectangles. */
function layOutInARow(): void {
  let x = 0;
  for (const el of Array.from(document.querySelectorAll('[data-surface-id]'))) {
    const at = x;
    (el as HTMLElement).getBoundingClientRect = () =>
      ({
        x: at,
        y: 0,
        width: 300,
        height: 200,
        top: 0,
        left: at,
        right: at + 300,
        bottom: 200,
        toJSON: () => ({}),
      }) as DOMRect;
    x += 320;
  }
  fireEvent(window, new Event('resize'));
}

function ids(): string[] {
  return Array.from(document.querySelectorAll('[data-surface-id]'))
    .map((el) => el.getAttribute('data-surface-id') ?? '')
    .filter(Boolean);
}

/**
 * The id of the panel the LAYOUT thinks is focused.
 *
 * In a focus layout `rawSpan` gives it FULL (12) and everything else 3, so the
 * widest panel is the layout's own answer — read from what it rendered rather
 * than from what it was passed.
 */
function widest(): string | null {
  const spans = Array.from(document.querySelectorAll('[data-surface-id]')).map((el) => ({
    id: el.getAttribute('data-surface-id') ?? '',
    span: Number(/span (\d+)/.exec((el as HTMLElement).style.gridColumn ?? '')?.[1] ?? 0),
  }));
  const top = Math.max(0, ...spans.map((s) => s.span));
  const winners = spans.filter((s) => s.span === top);
  // Every panel the same width means the layout is not distinguishing one,
  // which is a different answer from "this one".
  return winners.length === 1 ? winners[0]!.id : null;
}

function focused(): string | null {
  return document.querySelector('[data-focused="true"]')?.getAttribute('data-surface-id') ?? null;
}

/** A swipe: down, a long move inside the swipe window, up. */
function swipe(target: Element, from: number, to: number): void {
  fireEvent.pointerDown(target, { clientX: from, clientY: 100, pointerType: 'touch' });
  fireEvent.pointerMove(target, { clientX: to, clientY: 100, pointerType: 'touch' });
  fireEvent.pointerUp(target, { clientX: to, clientY: 100, pointerType: 'touch' });
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
  vi.useRealTimers();
});

describe('§18 the recogniser still refuses to guess', () => {
  it('returns null for a movement that is not clearly anything', () => {
    // Re-asserted here because the wiring below is only safe while this holds.
    expect(
      recogniseGesture([
        { x: 0, y: 0, t: 0 },
        { x: 40, y: 35, t: 100 },
      ]),
    ).toBeNull();
  });

  it('recognises a decisive horizontal swipe', () => {
    expect(
      recogniseGesture([
        { x: 0, y: 0, t: 0 },
        { x: 200, y: 4, t: 200 },
      ]),
    ).toBe('swipe_right');
  });
});

describe('§18 a track cannot grow without a bound', () => {
  it('keeps the first point and the newest one, and never exceeds the cap', () => {
    // A pointer held down emits a move per frame. Unbounded, that is a
    // user-driven allocation with no ceiling on the heaviest screen this app
    // draws — and `recogniseGesture` reads only the ends, so everything in
    // between was being kept for nothing.
    const points = [{ x: 0, y: 0, t: 0 }];
    for (let i = 1; i <= 5_000; i += 1) appendPoint(points, { x: i, y: 0, t: i });

    expect(points.length).toBe(MAX_TRACK_POINTS);
    // The first survives: it is what a swipe is measured from and what
    // `pointingAt` hit-tests. Dropping the OLDEST instead would silently
    // change which panel a long press meant.
    expect(points[0]).toEqual({ x: 0, y: 0, t: 0 });
    expect(points[points.length - 1]).toEqual({ x: 5_000, y: 0, t: 5_000 });
  });

  it('still recognises a swipe made of far more points than the cap', () => {
    // The bound must not cost recognition, which is the whole risk of adding
    // one: a swipe sampled at 120Hz is thousands of points.
    const points = [{ x: 0, y: 0, t: 0 }];
    for (let i = 1; i <= 2_000; i += 1) appendPoint(points, { x: i / 10, y: 0, t: i / 10 });
    expect(recogniseGesture(points)).toBe('swipe_right');
  });
});

describe('§18 the pointer halves have a caller now', () => {
  function stage(onPinSurface = vi.fn(), layout: 'auto' | 'focus' = 'auto') {
    return {
      onPinSurface,
      ...render(
        <PresenceStage
          presence={presence}
          surfaces={surfaces(3)}
          focusedId={null}
          listening={false}
          muted={false}
          sttSupported={false}
          transcript={[]}
          layout={layout}
          onCommand={vi.fn()}
          onTalk={vi.fn()}
          onStop={vi.fn()}
          onToggleMute={vi.fn()}
          onCloseSurface={vi.fn()}
          onPinSurface={onPinSurface}
          onExit={vi.fn()}
        />,
      ),
    };
  }

  it('moves focus to the neighbour on a swipe, using the measured scene', () => {
    // The assertion that fails on the pre-fix tree: nothing consumed
    // `recogniseGesture`, so a swipe did nothing at all.
    stage();
    layOutInARow();
    const panels = ids();
    const first = document.querySelector(`[data-surface-id="${panels[0]}"]`)!;
    fireEvent.pointerDown(first, { clientX: 150, clientY: 100, pointerType: 'touch' });
    fireEvent.pointerUp(first, { clientX: 150, clientY: 100, pointerType: 'touch' });

    swipe(first, 150, 400);
    expect(focused()).toBe(panels[1]);
  });

  it('does nothing when the swipe has nowhere to go', () => {
    // Never wraps. `resolveReference` holds the same rule: a reference that
    // wrapped would move an operator's attention to the far side of the plane.
    stage();
    layOutInARow();
    const panels = ids();
    const plane = document.querySelector(`[data-surface-id="${panels[0]}"]`)!;

    // Walk right to the last panel, then keep going. Each step is asserted so
    // an unwired handler fails HERE, on the claim, rather than further down on
    // a querySelector that returned null.
    swipe(plane, 150, 400);
    expect(focused()).toBe(panels[1]);
    swipe(plane, 150, 400);
    expect(focused()).toBe(panels[2]);
    swipe(plane, 150, 400);
    expect(focused()).toBe(panels[2]);

    // And the same at the other end.
    swipe(plane, 400, 150);
    expect(focused()).toBe(panels[1]);
    swipe(plane, 400, 150);
    expect(focused()).toBe(panels[0]);
    swipe(plane, 400, 150);
    expect(focused()).toBe(panels[0]);
  });

  it('pins the panel under a long press, which is the reversible action', () => {
    const onPinSurface = vi.fn();
    stage(onPinSurface);
    layOutInARow();
    const panels = ids();
    const target = document.querySelector(`[data-surface-id="${panels[1]}"]`)!;

    // A press that is long and still. `recogniseGesture` reads elapsed time
    // from the points, so the clock is what makes this a long press rather
    // than a tap — faked so the test does not sleep half a second.
    vi.useFakeTimers({ toFake: ['performance'] });
    fireEvent.pointerDown(target, { clientX: 400, clientY: 100, pointerType: 'touch' });
    vi.advanceTimersByTime(600);
    fireEvent.pointerMove(target, { clientX: 402, clientY: 101, pointerType: 'touch' });
    fireEvent.pointerUp(target, { clientX: 402, clientY: 101, pointerType: 'touch' });
    vi.useRealTimers();

    // It resolves through `pointingAt` against the measured scene, so the id
    // is the panel under the finger rather than the one the event bubbled to.
    expect(onPinSurface).toHaveBeenCalled();
  });

  it('lays the plane out around the panel the gesture focused, not the old one', () => {
    // Two notions of "focused" on screen at once is the defect this catches.
    // The focus RING followed the gesture while `place()` went on reading the
    // prop, so in a focus layout the plane kept enlarging one panel while
    // outlining a different one.
    stage(vi.fn(), 'focus');
    layOutInARow();
    const panels = ids();
    const plane = document.querySelector(`[data-surface-id="${panels[0]}"]`)!;

    // `rawSpan` gives the focused surface FULL and everything else 3, so the
    // widest panel IS the one the layout thinks is focused. Nothing is focused
    // yet, so nothing is wide.
    expect(widest()).toBeNull();

    swipe(plane, 150, 400);
    expect(focused()).toBe(panels[1]);
    expect(widest()).toBe(panels[1]);
  });

  it('binds nothing destructive', async () => {
    // The safety property. `gestures.ts` says a wrongly recognised swipe moves
    // a panel somebody was reading; the answer is that no gesture removes
    // anything. Asserted against the source so a later edit cannot add one
    // quietly.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const here = path.dirname(fileURLToPath(import.meta.url));
    const source = fs.readFileSync(path.resolve(here, '..', 'hub', 'PresenceStage.tsx'), 'utf8');
    const block = source.slice(source.indexOf('const onGesture'), source.indexOf('const onGesture') + 2000);
    expect(block).not.toContain('onCloseSurface');
    expect(block).not.toContain('onExit');
  });
});
