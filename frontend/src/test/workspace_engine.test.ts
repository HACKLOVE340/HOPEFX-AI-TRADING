/**
 * The generative workspace — §8, which the specification calls the core
 * differentiator.
 *
 * "The workspace engine receives a task intent and creates, updates, rearranges
 * and removes visual surfaces based on relevance." Not a dashboard whose panels
 * were decided at build time: surfaces appear because something asked for them,
 * and leave when they stop being relevant.
 *
 * The engine holds no React and draws nothing. It owns *what should be on the
 * plane and where*, so every rule below — priority ordering, the concurrent
 * ceiling, pinning, replacing rather than duplicating — is testable without a
 * browser.
 */

import { describe, it, expect } from 'vitest';
import { Workspace } from '../hub/workspace';

describe('surfaces appear because something asked for them', () => {
  it('starts empty — the default interface is a clean canvas', () => {
    // §2 and §4. An engine that starts with panels is a dashboard.
    expect(new Workspace().surfaces).toEqual([]);
  });

  it('opens a surface from a request', () => {
    const w = new Workspace();
    w.open({ kind: 'chart', intent: 'gold price this session' });
    expect(w.surfaces).toHaveLength(1);
    expect(w.surfaces[0]?.kind).toBe('chart');
    expect(w.surfaces[0]?.meaning).toBe('gold price this session');
  });

  it('gives every surface an id so it can be referred to and closed', () => {
    const w = new Workspace();
    w.open({ kind: 'chart', intent: 'a' });
    w.open({ kind: 'table', intent: 'b' });
    const ids = w.surfaces.map((s) => s.id);
    expect(new Set(ids).size).toBe(2);
  });

  it('updates rather than duplicates when the same key is asked for twice', () => {
    // "Show me gold" twice is one chart, not two. Duplicates are how a
    // generative workspace becomes a mess nobody can read.
    const w = new Workspace();
    w.open({ kind: 'chart', intent: 'gold', key: 'gold-chart' });
    w.open({ kind: 'chart', intent: 'gold, hourly', key: 'gold-chart' });
    expect(w.surfaces).toHaveLength(1);
    expect(w.surfaces[0]?.meaning).toBe('gold, hourly');
  });

  it('closes a surface by id', () => {
    const w = new Workspace();
    const id = w.open({ kind: 'chart', intent: 'gold' });
    w.close(id);
    expect(w.surfaces).toEqual([]);
  });

  it('clears everything on "simplify this"', () => {
    const w = new Workspace();
    w.open({ kind: 'chart', intent: 'a' });
    w.open({ kind: 'news', intent: 'b' });
    w.clear();
    expect(w.surfaces).toEqual([]);
  });
});

describe('pinning — §8', () => {
  it('keeps a pinned surface when everything else is cleared', () => {
    const w = new Workspace();
    const keep = w.open({ kind: 'chart', intent: 'gold' });
    w.open({ kind: 'news', intent: 'headlines' });
    w.pin(keep);
    w.clear();
    expect(w.surfaces.map((s) => s.id)).toEqual([keep]);
  });

  it('never evicts a pinned surface to make room', () => {
    const w = new Workspace({ maxSurfaces: 2 });
    const keep = w.open({ kind: 'chart', intent: 'gold' });
    w.pin(keep);
    w.open({ kind: 'news', intent: 'one' });
    w.open({ kind: 'table', intent: 'two' });
    expect(w.surfaces.map((s) => s.id)).toContain(keep);
    expect(w.surfaces).toHaveLength(2);
  });
});

describe('the ceiling — §8 says 1 to 20+, subject to device capacity', () => {
  it('holds many at once', () => {
    const w = new Workspace({ maxSurfaces: 20 });
    for (let i = 0; i < 20; i++) w.open({ kind: 'text', intent: `note ${i}` });
    expect(w.surfaces).toHaveLength(20);
  });

  it('evicts the least important, not the newest', () => {
    // The newest is what the operator just asked for. Dropping it to honour a
    // ceiling would make the ceiling look like a bug.
    const w = new Workspace({ maxSurfaces: 2 });
    w.open({ kind: 'text', intent: 'background thing', priority: 'background' });
    w.open({ kind: 'text', intent: 'primary thing', priority: 'primary' });
    w.open({ kind: 'text', intent: 'the new thing', priority: 'primary' });
    const meanings = w.surfaces.map((s) => s.meaning);
    expect(meanings).toContain('the new thing');
    expect(meanings).not.toContain('background thing');
  });
});

describe('relevance ordering — §10 cognitive load', () => {
  it('puts critical work first and background last', () => {
    const w = new Workspace();
    w.open({ kind: 'text', intent: 'background', priority: 'background' });
    w.open({ kind: 'text', intent: 'critical', priority: 'critical' });
    w.open({ kind: 'text', intent: 'secondary', priority: 'secondary' });
    expect(w.surfaces.map((s) => s.meaning)).toEqual(['critical', 'secondary', 'background']);
  });

  it('gives a critical surface more room than a background one', () => {
    // §10: "Critical information receives dominant placement." Placement is the
    // engine's job, not the renderer's.
    const w = new Workspace();
    w.open({ kind: 'chart', intent: 'critical', priority: 'critical' });
    w.open({ kind: 'chart', intent: 'background', priority: 'background' });
    const [first, second] = w.surfaces;
    expect((first?.span ?? 0)).toBeGreaterThan(second?.span ?? 0);
  });
});

describe('focus — §9, §10', () => {
  it('can focus one surface, and says which', () => {
    const w = new Workspace();
    const a = w.open({ kind: 'chart', intent: 'gold' });
    w.open({ kind: 'news', intent: 'headlines' });
    w.focus(a);
    expect(w.focused).toBe(a);
  });

  it('resolves a phrase to a surface so "this chart" means something', () => {
    const w = new Workspace();
    const gold = w.open({ kind: 'chart', intent: 'gold price this session' });
    w.open({ kind: 'table', intent: 'open positions' });
    expect(w.resolve('the gold chart')).toBe(gold);
    expect(w.resolve('nothing like this')).toBeNull();
  });

  it('drops focus when the focused surface closes', () => {
    // A focus pointing at a surface nobody can see is how the AI ends up
    // explaining something that is not on screen.
    const w = new Workspace();
    const a = w.open({ kind: 'chart', intent: 'gold' });
    w.focus(a);
    w.close(a);
    expect(w.focused).toBeNull();
  });
});

describe('it refuses what it cannot render', () => {
  it('rejects an unknown kind rather than opening a blank panel', () => {
    const w = new Workspace();
    expect(() => w.open({ kind: 'teleporter' as never, intent: 'x' })).toThrow(/unknown surface kind/);
    expect(w.surfaces).toEqual([]);
  });
});
