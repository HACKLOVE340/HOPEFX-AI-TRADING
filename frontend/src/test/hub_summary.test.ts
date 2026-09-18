/**
 * §10: "summarise across surfaces and name relationships."
 *
 * Six panels open is six things to read. The value the AI adds is saying how
 * they bear on each other — the part a dashboard has never been able to do.
 *
 * The rule this is built on: **relationships are declared, not inferred.** A
 * model asked to find connections between whatever is on screen would find
 * some, and some of those would be wrong, and a confident false statement about
 * how risk limits relate to open exposure is expensive on this platform.
 *
 * Fails on the pre-fix tree — `hub/summary.ts` does not exist there.
 */

import { describe, expect, it } from 'vitest';

import { RELATIONS, asksForSummary, summarise } from '../hub/summary';
import { place } from '../hub/layout';
import { Workspace, type Surface } from '../hub/workspace';
import type { SurfaceRequest } from '../hub/contracts.shared';

const REQUESTS: Record<string, SurfaceRequest> = {
  'gold-chart': { kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' },
  'gold-news': { kind: 'news', intent: 'Gold headlines', priority: 'secondary', key: 'gold-news' },
  'gold-exposure': { kind: 'table', intent: 'Gold exposure', priority: 'secondary', key: 'gold-exposure' },
  risk: { kind: 'table', intent: 'Risk limits and headroom', priority: 'critical', key: 'risk' },
  camera: { kind: 'camera', intent: 'Camera', priority: 'background', key: 'camera' },
  calls: { kind: 'terminal', intent: 'Recent model calls', priority: 'background', key: 'calls' },
};

function plane(...keys: string[]): readonly Surface[] {
  const ws = new Workspace();
  for (const k of keys) ws.open(REQUESTS[k]!);
  return ws.surfaces;
}

describe('naming relationships', () => {
  it('says how two connected surfaces bear on each other', () => {
    const text = summarise(plane('gold-chart', 'gold-exposure')).text;
    expect(text).toMatch(/Gold price and Gold exposure are connected/i);
    expect(text).toMatch(/exposure is to the instrument on this chart/i);
  });

  it('finds the relationship whichever order the surfaces are in', () => {
    const forward = summarise(plane('gold-exposure', 'risk')).relations;
    const backward = summarise(plane('risk', 'gold-exposure')).relations;
    expect(forward).toHaveLength(1);
    expect(backward).toHaveLength(1);
    expect(forward[0]!.because).toBe(backward[0]!.because);
  });

  it('makes no claim about a pair nobody wrote down', () => {
    // The whole point. An unlisted pair produces silence, not a plausible
    // sentence — this is a money-moving system and a confident wrong
    // relationship costs more than an absent one.
    const summary = summarise(plane('camera', 'risk'));
    expect(summary.relations).toHaveLength(0);
  });

  it('says which surfaces it had nothing to say about', () => {
    // Quietly omitting them implies they were covered.
    const summary = summarise(plane('gold-chart', 'gold-exposure', 'camera'));
    expect(summary.unrelated.map((s) => s.key)).toEqual(['camera']);
    expect(summary.text).toMatch(/nothing declared linking camera/i);
  });

  it('says so plainly when it can relate none of them', () => {
    const summary = summarise(plane('camera', 'calls'));
    expect(summary.text).toMatch(/no declared relationship between any of these/i);
  });
});

describe('it describes the screen, not the account', () => {
  it('never asserts anything about the numbers inside a panel', () => {
    // "Risk limits govern that exposure" is a fact about the screen. "You are
    // close to your limit" is a fact about the account, and is not knowable
    // from here. Mixing them is how a layout engine makes a risk assertion.
    const text = summarise(plane('gold-chart', 'gold-exposure', 'risk')).text.toLowerCase();
    for (const forbidden of ['close to', 'breach', 'safe', 'you should', 'i recommend', 'buy', 'sell']) {
      expect(text).not.toContain(forbidden);
    }
  });
});

describe('it stays readable', () => {
  it('speaks at most three relationships and counts the rest', () => {
    // A summary that recites nine connections is a second thing to read rather
    // than a way of not reading the first.
    const summary = summarise(plane('gold-chart', 'gold-news', 'gold-exposure', 'risk'));
    const spoken = summary.text.match(/are connected/g) ?? [];
    expect(spoken.length).toBeLessThanOrEqual(3);
    if (summary.relations.length > 3) expect(summary.text).toMatch(/more connections/i);
  });

  it('has nothing to say about an empty plane', () => {
    expect(summarise([]).text).toBe('');
  });

  it('does not claim a relationship on a plane of one', () => {
    const summary = summarise(plane('risk'));
    expect(summary.relations).toHaveLength(0);
    expect(summary.text).toMatch(/one surface/i);
  });
});

describe('the relation table itself', () => {
  it('names no surface key twice in one pair', () => {
    for (const r of RELATIONS) expect(r.a).not.toBe(r.b);
  });

  it('holds no duplicate pair in either direction', () => {
    // Two entries for the same pair would print the relationship twice.
    const seen = new Set<string>();
    for (const r of RELATIONS) {
      const key = [r.a, r.b].sort().join('|');
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  });

  it('explains every relationship in words', () => {
    for (const r of RELATIONS) expect(r.because.length).toBeGreaterThan(10);
  });
});

describe('asking for one', () => {
  const yes = [
    'summarise this',
    'summarize what I am looking at',
    'what am I looking at',
    'how do these relate',
    'tie this together',
    'explain all of this',
  ];
  for (const phrase of yes) {
    it(`recognises ${JSON.stringify(phrase)}`, () => expect(asksForSummary(phrase)).toBe(true));
  }

  it('does not fire on an ordinary question', () => {
    for (const phrase of ['show me gold', 'focus on risk', 'what is the gold price', '']) {
      expect(asksForSummary(phrase)).toBe(false);
    }
  });
});

// ── §10 background collapse ──────────────────────────────────────────────────

describe('background information collapses into a stack', () => {
  function crowded(): readonly Surface[] {
    const ws = new Workspace();
    ws.open(REQUESTS.risk!);
    ws.open(REQUESTS['gold-chart']!);
    for (let i = 0; i < 5; i += 1) {
      ws.open({ kind: 'terminal', intent: `Log ${i}`, priority: 'background', key: `log${i}` });
    }
    return ws.surfaces;
  }

  it('folds background surfaces away once the plane is crowded', () => {
    const placed = place(crowded(), { collapseBackground: true, viewport: { width: 1600 } });
    expect(placed.filter((p) => p.collapsed).length).toBeGreaterThan(0);
  });

  it('never folds anything above the background tier', () => {
    const placed = place(crowded(), { collapseBackground: true, viewport: { width: 1600 } });
    for (const p of placed) {
      if (p.collapsed) expect(['background', 'on_demand']).toContain(p.surface.priority);
    }
  });

  it('does not collapse a small plane however unimportant its panels are', () => {
    // §10 is about cognitive load, not a hard limit. Four panels do not need
    // collapsing however quiet two of them are.
    const ws = new Workspace();
    for (let i = 0; i < 4; i += 1) {
      ws.open({ kind: 'terminal', intent: `Log ${i}`, priority: 'background', key: `log${i}` });
    }
    const placed = place(ws.surfaces, { collapseBackground: true, viewport: { width: 1600 } });
    expect(placed.every((p) => !p.collapsed)).toBe(true);
  });

  it('leaves a pinned surface alone', () => {
    // Pinning is the operator overruling the engine's opinion about importance.
    // Folding it away is the engine overruling them back.
    const ws = new Workspace();
    ws.open(REQUESTS.risk!);
    const pinned = ws.open({ kind: 'terminal', intent: 'Kept', priority: 'background', key: 'kept' });
    ws.pin(pinned);
    for (let i = 0; i < 5; i += 1) {
      ws.open({ kind: 'terminal', intent: `Log ${i}`, priority: 'background', key: `log${i}` });
    }
    const placed = place(ws.surfaces, { collapseBackground: true, viewport: { width: 1600 } });
    expect(placed.find((p) => p.surface.key === 'kept')!.collapsed).toBe(false);
  });

  it('leaves the focused surface alone', () => {
    const ws = new Workspace();
    ws.open(REQUESTS.risk!);
    const id = ws.open({ kind: 'terminal', intent: 'Watching', priority: 'background', key: 'watch' });
    for (let i = 0; i < 5; i += 1) {
      ws.open({ kind: 'terminal', intent: `Log ${i}`, priority: 'background', key: `log${i}` });
    }
    const placed = place(ws.surfaces, {
      collapseBackground: true,
      focusedId: id,
      viewport: { width: 1600 },
    });
    expect(placed.find((p) => p.surface.id === id)!.collapsed).toBe(false);
  });

  it('is off unless asked for, so nothing collapses behind an existing caller', () => {
    const placed = place(crowded(), { viewport: { width: 1600 } });
    expect(placed.every((p) => !p.collapsed)).toBe(true);
  });

  it('is not the same thing as hidden', () => {
    // A collapsed surface is still on the plane and still listed; a hidden one
    // is not drawn at all. Conflating them means the operator cannot get a
    // collapsed panel back without knowing it was there.
    const placed = place(crowded(), { collapseBackground: true, viewport: { width: 1600 } });
    expect(placed.filter((p) => p.collapsed).every((p) => p.visible)).toBe(true);
  });
});
