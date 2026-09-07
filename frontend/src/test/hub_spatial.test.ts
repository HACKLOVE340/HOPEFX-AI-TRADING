/**
 * §9's remaining four: coordinate and viewport awareness, focus transitions,
 * zoom into data regions, layer navigation and breadcrumbs.
 *
 * Fails on the pre-fix tree — `hub/spatial.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import {
  LayerStack,
  applyZoom,
  focusTransition,
  positionOf,
  readNavigation,
  readZoom,
} from '../hub/spatial';

const VIEW = { x: 0, y: 0, width: 1200, height: 900 };

describe('position is measured or it is not claimed', () => {
  it('names the ninth a panel sits in', () => {
    expect(positionOf({ x: 50, y: 40, width: 200, height: 100 }, VIEW)?.phrase).toBe('top left');
    expect(positionOf({ x: 950, y: 750, width: 200, height: 100 }, VIEW)?.phrase).toBe('bottom right');
    expect(positionOf({ x: 500, y: 400, width: 200, height: 100 }, VIEW)?.phrase).toBe('the centre');
  });

  it('says "the right" rather than "middle right"', () => {
    // What a person standing at the screen would say.
    expect(positionOf({ x: 950, y: 400, width: 200, height: 100 }, VIEW)?.phrase).toBe('the right');
  });

  it('returns null for a rect that was never measured', () => {
    // `getBoundingClientRect` gives a zero rect for an element that is not laid
    // out yet. Reading that as "top left" points the operator at a corner where
    // nothing is — the AI directing their eyes to the wrong part of their own
    // screen, confidently.
    expect(positionOf(null, VIEW)).toBeNull();
    expect(positionOf(undefined, VIEW)).toBeNull();
    expect(positionOf({ x: 0, y: 0, width: 0, height: 0 }, VIEW)).toBeNull();
  });

  it('returns null when the viewport itself has not been measured', () => {
    expect(positionOf({ x: 10, y: 10, width: 50, height: 50 }, { x: 0, y: 0, width: 0, height: 0 })).toBeNull();
  });

  it('accounts for a viewport that does not start at the origin', () => {
    const offset = { x: 400, y: 200, width: 600, height: 600 };
    // Absolute 450,250 is near the offset viewport's top-left corner.
    expect(positionOf({ x: 450, y: 250, width: 40, height: 40 }, offset)?.phrase).toBe('top left');
  });
});

describe('zooming into a region', () => {
  const points = Array.from({ length: 100 }, (_, i) => i);

  it('keeps the most recent stretch for "zoom into the last hour"', () => {
    const range = readZoom('zoom into the last hour', points.length);
    expect(range).not.toBeNull();
    const zoomed = applyZoom(points, range);
    expect(zoomed[zoomed.length - 1]).toBe(99);
    expect(zoomed.length).toBeLessThan(points.length);
  });

  it('honours an explicit count', () => {
    expect(applyZoom(points, readZoom('zoom in on the last 10', points.length))).toHaveLength(10);
    expect(applyZoom(points, readZoom('zoom in on the first 5', points.length))[0]).toBe(0);
  });

  it('restores the whole series on "zoom out"', () => {
    expect(applyZoom(points, readZoom('zoom out', points.length))).toHaveLength(100);
  });

  it('returns null when no region was named, so the chart is left alone', () => {
    // Zooming somewhere arbitrary because a sentence mentioned a chart is worse
    // than not zooming.
    expect(readZoom('show me gold', points.length)).toBeNull();
    expect(readZoom('what is happening', points.length)).toBeNull();
    expect(readZoom('', points.length)).toBeNull();
  });

  it('refuses to zoom a series too short to zoom', () => {
    expect(readZoom('zoom in', 1)).toBeNull();
    expect(readZoom('zoom in', 0)).toBeNull();
  });

  it('clamps a range that runs off either end', () => {
    expect(applyZoom(points, { from: -50, to: 500 })).toHaveLength(100);
    expect(applyZoom(points, { from: 98, to: 99 })).toEqual([98]);
  });

  it('never returns an empty chart', () => {
    // An empty series renders as "not enough data to draw a line", which reads
    // as a dead feed rather than as a zoom.
    expect(applyZoom(points, { from: 50, to: 50 }).length).toBeGreaterThan(0);
    expect(applyZoom([], null)).toEqual([]);
  });
});

describe('breadcrumbs', () => {
  it('starts at the root and stays there when you go back', () => {
    // An operator who taps back twice at the top has not done anything wrong.
    const stack = new LayerStack();
    expect(stack.depth).toBe(0);
    stack.back();
    stack.back();
    expect(stack.depth).toBe(0);
    expect(stack.trail).toHaveLength(1);
  });

  it('records where you drilled to and gets you back', () => {
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'Gold price' });
    stack.enter({ surfaceId: 's2', label: 'Risk limits' });
    expect(stack.trail.map((l) => l.label)).toEqual(['Plane', 'Gold price', 'Risk limits']);
    expect(stack.back().label).toBe('Gold price');
    expect(stack.back().label).toBe('Plane');
  });

  it('replaces rather than stacks when you go deeper into the same surface', () => {
    // Zooming three times would otherwise leave three identical breadcrumbs,
    // and "back" would appear to do nothing twice.
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'Gold price', zoom: { from: 0, to: 50 } });
    stack.enter({ surfaceId: 's1', label: 'Gold price', zoom: { from: 25, to: 50 } });
    stack.enter({ surfaceId: 's1', label: 'Gold price', zoom: { from: 40, to: 50 } });
    expect(stack.depth).toBe(1);
    expect(stack.current.zoom).toEqual({ from: 40, to: 50 });
  });

  it('jumps to a breadcrumb and truncates everything past it', () => {
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'A' });
    stack.enter({ surfaceId: 's2', label: 'B' });
    stack.enter({ surfaceId: 's3', label: 'C' });
    expect(stack.to(1).label).toBe('A');
    expect(stack.trail).toHaveLength(2);
  });

  it('clamps a stale breadcrumb index rather than throwing', () => {
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'A' });
    expect(stack.to(99).label).toBe('A');
    expect(stack.to(-4).label).toBe('Plane');
  });

  it('drops breadcrumbs for surfaces that were closed', () => {
    // A breadcrumb that navigates nowhere is worse than no breadcrumb.
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'A' });
    stack.enter({ surfaceId: 's2', label: 'B' });
    stack.prune(new Set(['s1']));
    expect(stack.trail.map((l) => l.label)).toEqual(['Plane', 'A']);
  });

  it('keeps the root when every surface is gone', () => {
    const stack = new LayerStack();
    stack.enter({ surfaceId: 's1', label: 'A' });
    stack.prune(new Set());
    expect(stack.trail).toHaveLength(1);
    expect(stack.depth).toBe(0);
  });
});

describe('reading a navigation phrase', () => {
  it('recognises going back and going to the top', () => {
    expect(readNavigation('go back')).toBe('back');
    expect(readNavigation('zoom back out')).toBe('back');
    expect(readNavigation('back to the top')).toBe('root');
    expect(readNavigation('all the way back')).toBe('root');
  });

  it('returns null for anything else', () => {
    expect(readNavigation('show me gold')).toBeNull();
    expect(readNavigation('')).toBeNull();
  });
});

describe('focus transitions', () => {
  it('animates transform and opacity, never width or height', () => {
    // Animating geometry on a grid of a dozen panels drops frames on exactly
    // the device that can least afford it.
    const t = focusTransition({ focused: true, spokenAbout: false, reducedMotion: false });
    expect(t.transition).not.toMatch(/\b(width|height|top|left|margin|padding)\b/);
    expect(t.transition).toMatch(/transform/);
  });

  it('stays inside the 150-300ms band', () => {
    const t = focusTransition({ focused: true, spokenAbout: false, reducedMotion: false });
    const durations = [...t.transition.matchAll(/(\d+)ms/g)].map((m) => Number(m[1]));
    expect(durations.length).toBeGreaterThan(0);
    for (const d of durations) {
      expect(d).toBeGreaterThanOrEqual(150);
      expect(d).toBeLessThanOrEqual(300);
    }
  });

  it('removes motion entirely under prefers-reduced-motion', () => {
    // Not shortens. A 1ms transform is still a transform, and for some people
    // the setting is medical rather than aesthetic.
    const t = focusTransition({ focused: true, spokenAbout: true, reducedMotion: true });
    expect(t.transition).toBe('none');
    expect(t.transform).toBe('none');
  });

  it('lifts a focused panel more than one merely being talked about', () => {
    const focused = focusTransition({ focused: true, spokenAbout: false, reducedMotion: false });
    const spoken = focusTransition({ focused: false, spokenAbout: true, reducedMotion: false });
    const neither = focusTransition({ focused: false, spokenAbout: false, reducedMotion: false });
    expect(focused.transform).not.toBe(spoken.transform);
    expect(neither.transform).toBe('none');
  });
});
