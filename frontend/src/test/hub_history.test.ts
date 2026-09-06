/**
 * §8's own example: "bring back yesterday's workspace".
 *
 * It fell through to the model fallback and got a refusal — the specification's
 * named example, unhandled, in a feature whose claim is that it understands what
 * you asked for. `workspace.history_snapshots` was `planned` in the registry.
 *
 * These fail on the pre-fix tree — `hub/history.ts` does not exist there.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  SnapshotStore,
  capacityFor,
  readHistoryIntent,
  type SnapshotStorage,
} from '../hub/history';
import { Workspace } from '../hub/workspace';
import type { SurfaceRequest } from '../hub/contracts.shared';

class Memory implements SnapshotStorage {
  private data = new Map<string, string>();
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
}

/** Storage that refuses every write, like Safari's private mode. */
class Refusing implements SnapshotStorage {
  getItem() {
    return null;
  }
  setItem(): never {
    throw new DOMException('QuotaExceededError');
  }
}

const DAY = 86_400_000;
const SURFACES: SurfaceRequest[] = [
  { kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' },
  { kind: 'table', intent: 'Risk limits', priority: 'critical', key: 'risk' },
];

let storage: Memory;
beforeEach(() => {
  storage = new Memory();
});

describe('yesterday means yesterday', () => {
  it('restores a snapshot actually taken yesterday', () => {
    const now = new Date('2026-03-10T14:00:00').getTime();
    const store = new SnapshotStore({ storage, now: () => now - DAY });
    store.save(SURFACES, { name: 'monday' });

    const today = new SnapshotStore({ storage, now: () => now });
    expect(today.yesterday()?.name).toBe('monday');
  });

  it('returns null when there is nothing from yesterday, rather than the newest thing', () => {
    // The defect this exists to prevent: restoring the most recent snapshot is
    // one line shorter and silently answers a different question. The plane
    // fills with plausible panels from an arrangement nobody asked for.
    const now = new Date('2026-03-10T14:00:00').getTime();
    const old = new SnapshotStore({ storage, now: () => now - 9 * DAY });
    old.save(SURFACES, { name: 'last week' });

    const today = new SnapshotStore({ storage, now: () => now });
    expect(today.yesterday()).toBeNull();
    // ...and the older one is still findable when asked for differently.
    expect(today.previous()?.name).toBe('last week');
  });

  it('does not count something saved earlier today as yesterday', () => {
    const morning = new Date('2026-03-10T08:00:00').getTime();
    const evening = new Date('2026-03-10T20:00:00').getTime();
    new SnapshotStore({ storage, now: () => morning }).save(SURFACES, { name: 'this morning' });
    expect(new SnapshotStore({ storage, now: () => evening }).yesterday()).toBeNull();
  });
});

describe('storage that refuses is reported, not swallowed', () => {
  it('returns null from save so the caller can say it was not kept', () => {
    const store = new SnapshotStore({ storage: new Refusing() });
    expect(store.save(SURFACES, { name: 'x' })).toBeNull();
  });

  it('treats unreadable storage as an empty history rather than throwing', () => {
    const store = new SnapshotStore({ storage: null });
    expect(store.list()).toEqual([]);
    expect(store.yesterday()).toBeNull();
    expect(store.latest()).toBeNull();
  });

  it('survives storage holding something that is not a snapshot list', () => {
    storage.setItem('hopefx.hub.workspaces.v1', '{"not":"an array"}');
    expect(new SnapshotStore({ storage }).list()).toEqual([]);
  });

  it('drops a stored entry with no surfaces rather than restoring an empty plane', () => {
    // Which would be indistinguishable from a restore that failed.
    storage.setItem('hopefx.hub.workspaces.v1', JSON.stringify([{ id: 'a', at: 1, name: 'x' }]));
    expect(new SnapshotStore({ storage }).list()).toEqual([]);
  });
});

describe('saving', () => {
  it('refuses to save an empty plane', () => {
    expect(new SnapshotStore({ storage }).save([], { name: 'nothing' })).toBeNull();
  });

  it('replaces a named snapshot rather than stacking seven of the same name', () => {
    let clock = 1_000;
    const store = new SnapshotStore({ storage, now: () => (clock += 1000) });
    store.save(SURFACES, { name: 'risk review' });
    store.save(SURFACES.slice(0, 1), { name: 'Risk Review' });
    const named = store.list().filter((s) => !s.auto);
    expect(named).toHaveLength(1);
    expect(named[0]!.surfaces).toHaveLength(1);
  });

  it('does not let automatic captures push out a named snapshot', () => {
    // A named snapshot is something the operator deliberately made. Yesterday's
    // automatic capture of a plane they closed after ten seconds is not.
    let clock = 1_000;
    const store = new SnapshotStore({ storage, now: () => (clock += 1000) });
    store.save(SURFACES, { name: 'keep me' });
    for (let i = 0; i < 60; i += 1) store.save(SURFACES, { auto: true });
    expect(store.byName('keep me')).not.toBeNull();
  });

  it('finds a snapshot by name, case-insensitively', () => {
    const store = new SnapshotStore({ storage });
    store.save(SURFACES, { name: 'War Room' });
    expect(store.byName('war room')?.name).toBe('War Room');
    expect(store.byName('nothing like it')).toBeNull();
  });
});

describe('the workspace can be snapshotted and rebuilt', () => {
  it('round-trips what was asked for', () => {
    const ws = new Workspace();
    ws.open(SURFACES[0]!);
    ws.open(SURFACES[1]!);
    const saved = ws.snapshot();

    const rebuilt = new Workspace();
    const { restored, skipped } = rebuilt.restore(saved);
    expect(restored).toBe(2);
    expect(skipped).toEqual([]);
    expect(rebuilt.surfaces.map((s) => s.key).sort()).toEqual(['gold-chart', 'risk']);
  });

  it('stores requests, not surfaces, so a restore is not a fossil of the old engine', () => {
    const ws = new Workspace();
    ws.open(SURFACES[0]!);
    const saved = ws.snapshot();
    expect(saved[0]).not.toHaveProperty('span');
    expect(saved[0]).not.toHaveProperty('id');
    expect(saved[0]).not.toHaveProperty('openedAt');
  });

  it('skips a surface kind that no longer exists instead of losing the whole arrangement', () => {
    // Throwing would make the restore fail exactly when it is most valuable:
    // on the oldest snapshot, because one panel type was renamed.
    const ws = new Workspace();
    const { restored, skipped } = ws.restore([
      { kind: 'chart', intent: 'Gold', priority: 'primary', key: 'g' },
      // Deliberately not a kind this version knows — that is the whole test.
      // Cast because the compiler is right and the stored snapshot is not.
      { kind: 'holodeck', intent: 'Gone', priority: 'primary', key: 'x' } as unknown as SurfaceRequest,
    ]);
    expect(restored).toBe(1);
    expect(skipped).toEqual(['holodeck']);
    expect(ws.surfaces).toHaveLength(1);
  });

  it('keeps pinned surfaces across a restore', () => {
    const ws = new Workspace();
    const pinned = ws.open({ kind: 'table', intent: 'Kill switch', priority: 'critical', key: 'kill' });
    ws.pin(pinned);
    ws.restore(SURFACES);
    expect(ws.surfaces.some((s) => s.key === 'kill')).toBe(true);
  });
});

describe('degrading on a small device rather than failing', () => {
  it('allows fewer concurrent surfaces on a phone', () => {
    // Every surface is full width below 640px, so twelve of them is a
    // twelve-screen scroll: technically working, practically a failure.
    expect(capacityFor(375)).toBeLessThan(capacityFor(1600));
    expect(capacityFor(900)).toBeLessThan(capacityFor(1600));
  });

  it('evicts immediately when the ceiling drops, not at the next open', () => {
    // Rotating a phone to portrait with twelve open must reduce them now.
    const ws = new Workspace({ maxSurfaces: 12 });
    for (let i = 0; i < 10; i += 1) {
      ws.open({ kind: 'chart', intent: `s${i}`, priority: 'secondary', key: `s${i}` });
    }
    expect(ws.surfaces).toHaveLength(10);
    ws.setCapacity(capacityFor(375));
    expect(ws.surfaces).toHaveLength(4);
  });

  it('never drops below one surface however small the ceiling asked for', () => {
    const ws = new Workspace();
    ws.open(SURFACES[0]!);
    ws.setCapacity(0);
    expect(ws.capacityLimit).toBe(1);
    expect(ws.surfaces).toHaveLength(1);
  });
});

describe('reading a history phrase', () => {
  const cases: [string, string][] = [
    ["bring back yesterday's workspace", 'restore_yesterday'],
    ['restore yesterday layout', 'restore_yesterday'],
    ['go back to my previous workspace', 'restore_previous'],
    ['save this as risk review', 'save'],
    ['remember it as monday morning', 'save'],
    ['bring back risk review', 'restore_named'],
    ['what workspaces do I have', 'list'],
  ];

  for (const [phrase, kind] of cases) {
    it(`reads ${JSON.stringify(phrase)} as ${kind}`, () => {
      expect(readHistoryIntent(phrase)?.kind).toBe(kind);
    });
  }

  it('extracts the name from a save', () => {
    const intent = readHistoryIntent('save this as Risk Review.');
    expect(intent).toEqual({ kind: 'save', name: 'Risk Review' });
  });

  it('extracts the name from a restore', () => {
    expect(readHistoryIntent('restore the workspace called war room')).toEqual({
      kind: 'restore_named',
      name: 'war room',
    });
  });

  it('returns null for an ordinary question rather than guessing', () => {
    // Otherwise "show me gold" half-matches a restore and replaces the plane.
    expect(readHistoryIntent('show me everything affecting gold')).toBeNull();
    expect(readHistoryIntent('focus on risk')).toBeNull();
    expect(readHistoryIntent('')).toBeNull();
  });
});
