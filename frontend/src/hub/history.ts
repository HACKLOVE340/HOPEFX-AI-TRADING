/**
 * hub/history.ts — workspace history and named snapshots.
 *
 * §8 lists "bring back yesterday's workspace" as one of four example commands.
 * Until now that sentence fell through to the model fallback and got a polite
 * refusal, which is the worst possible answer: the specification's own example,
 * unhandled, in a feature whose whole claim is that it understands what you
 * asked for.
 *
 * ## Yesterday means yesterday
 *
 * "Bring back yesterday's workspace" resolves to a snapshot actually taken
 * yesterday. If none exists it returns null and the caller says so. Restoring
 * the most recent snapshot instead — which is what a naive implementation does,
 * because it is one line shorter — silently answers a different question, and
 * the operator cannot tell: the plane fills with plausible panels from an
 * arrangement they never asked for.
 *
 * ## Storage is best-effort, and its failures are visible
 *
 * `localStorage` throws in Safari's private mode and is absent server-side, so
 * every access is guarded. A failed save returns false rather than throwing,
 * because losing a snapshot is a small problem and crashing the workspace while
 * saving one is a large one — but it does return false, so the caller can tell
 * the operator their arrangement was not kept rather than implying it was.
 */

import type { SurfaceRequest } from './contracts.shared';
import type { LayoutName } from './layout';

export interface WorkspaceSnapshot {
  id: string;
  /** What the operator called it, or an automatic label. */
  name: string;
  /** Epoch milliseconds. */
  at: number;
  layout: LayoutName | null;
  surfaces: SurfaceRequest[];
  /** True when this was captured automatically rather than asked for. */
  auto: boolean;
}

export interface SnapshotStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const KEY = 'hopefx.hub.workspaces.v1';

/**
 * How many to keep.
 *
 * Automatic snapshots are capped separately from named ones: a named snapshot
 * is something the operator deliberately made and must not be pushed out by
 * yesterday's automatic capture of a plane they closed after ten seconds.
 */
const MAX_AUTO = 30;
const MAX_NAMED = 40;

const DAY_MS = 86_400_000;

function browserStorage(): SnapshotStorage | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    return localStorage;
  } catch {
    // Accessing the property itself throws when site data is blocked.
    return null;
  }
}

/** Start of the local day containing `at`, in epoch milliseconds. */
function startOfDay(at: number): number {
  const d = new Date(at);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export class SnapshotStore {
  private readonly storage: SnapshotStorage | null;
  private readonly now: () => number;
  private seq = 0;

  constructor(options: { storage?: SnapshotStorage | null; now?: () => number } = {}) {
    this.storage = options.storage === undefined ? browserStorage() : options.storage;
    this.now = options.now ?? Date.now;
  }

  /** Newest first. Never throws: unreadable storage is an empty history. */
  list(): WorkspaceSnapshot[] {
    if (!this.storage) return [];
    let raw: string | null = null;
    try {
      raw = this.storage.getItem(KEY);
    } catch {
      return [];
    }
    if (!raw) return [];
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      // Written by an older version, or by hand. A snapshot missing its
      // surfaces would restore an empty plane and look like a bug in restore.
      return parsed
        .filter(
          (s): s is WorkspaceSnapshot =>
            typeof s === 'object' &&
            s !== null &&
            typeof (s as WorkspaceSnapshot).id === 'string' &&
            typeof (s as WorkspaceSnapshot).at === 'number' &&
            Array.isArray((s as WorkspaceSnapshot).surfaces),
        )
        .sort((a, b) => b.at - a.at);
    } catch {
      return [];
    }
  }

  /**
   * Keep an arrangement. Returns false when storage refused it.
   *
   * An empty plane is not saved. Restoring one is indistinguishable from a
   * restore that failed, and an automatic capture of every momentarily-empty
   * workspace would fill the history with nothing.
   */
  save(
    surfaces: readonly SurfaceRequest[],
    options: { name?: string; layout?: LayoutName | null; auto?: boolean } = {},
  ): WorkspaceSnapshot | null {
    if (!this.storage || surfaces.length === 0) return null;
    const at = this.now();
    const auto = options.auto ?? false;
    const snapshot: WorkspaceSnapshot = {
      id: `w${at}-${++this.seq}`,
      name: options.name?.trim() || new Date(at).toLocaleString(),
      at,
      layout: options.layout ?? null,
      surfaces: surfaces.map((s) => ({ ...s })),
      auto,
    };

    const existing = this.list();
    // A named save replaces the one with the same name rather than stacking
    // "risk review" seven times.
    const withoutSameName = auto
      ? existing
      : existing.filter((s) => s.auto || s.name.toLowerCase() !== snapshot.name.toLowerCase());

    const next = [snapshot, ...withoutSameName];
    const trimmed = [
      ...next.filter((s) => !s.auto).slice(0, MAX_NAMED),
      ...next.filter((s) => s.auto).slice(0, MAX_AUTO),
    ].sort((a, b) => b.at - a.at);

    try {
      this.storage.setItem(KEY, JSON.stringify(trimmed));
    } catch {
      // Quota, private mode, or a storage that vanished mid-session.
      return null;
    }
    return snapshot;
  }

  /** By name, case-insensitively. Null when there is no such snapshot. */
  byName(name: string): WorkspaceSnapshot | null {
    const wanted = name.trim().toLowerCase();
    if (!wanted) return null;
    return this.list().find((s) => s.name.toLowerCase() === wanted) ?? null;
  }

  /**
   * The last arrangement from the calendar day before today.
   *
   * Null when there is none, so the caller can say "there is no workspace from
   * yesterday" instead of restoring something else and letting the operator
   * work out the difference from the panels.
   */
  yesterday(): WorkspaceSnapshot | null {
    const today = startOfDay(this.now());
    const from = today - DAY_MS;
    return this.list().find((s) => s.at >= from && s.at < today) ?? null;
  }

  /** The most recent arrangement before the current day. "Last time." */
  previous(): WorkspaceSnapshot | null {
    const today = startOfDay(this.now());
    return this.list().find((s) => s.at < today) ?? null;
  }

  latest(): WorkspaceSnapshot | null {
    return this.list()[0] ?? null;
  }
}

/**
 * What a history phrase is asking for.
 *
 * Kept separate from `intent.ts` because restoring an arrangement is not the
 * same kind of act as opening a surface: it replaces the plane, and a phrase
 * that half-matched "show me gold" must not also half-match "bring back
 * yesterday".
 */
export type HistoryIntent =
  | { kind: 'restore_yesterday' }
  | { kind: 'restore_previous' }
  | { kind: 'restore_named'; name: string }
  | { kind: 'save'; name: string }
  | { kind: 'list' };

export function readHistoryIntent(phrase: string): HistoryIntent | null {
  const text = (phrase ?? '').trim();
  if (!text) return null;
  const lower = text.toLowerCase();

  const saveMatch = /\b(?:save|remember|keep)\s+(?:this|it)?\s*(?:as|called|named)\s+(.+)$/i.exec(text);
  if (saveMatch?.[1]) return { kind: 'save', name: saveMatch[1].trim().replace(/[.!?]+$/, '') };

  if (/\byesterday\b/.test(lower) && /\b(workspace|layout|arrangement|screen|back|restore)\b/.test(lower)) {
    return { kind: 'restore_yesterday' };
  }

  if (/\b(last time|previous|earlier) (workspace|arrangement|layout|screen)\b/.test(lower)) {
    return { kind: 'restore_previous' };
  }

  const namedMatch =
    /\b(?:bring back|restore|reopen|load|go back to)\s+(?:the\s+)?(?:workspace\s+)?(?:called\s+)?(.+)$/i.exec(text);
  if (namedMatch?.[1]) {
    const name = namedMatch[1].trim().replace(/[.!?]+$/, '').replace(/\s+workspace$/i, '');
    if (name && !/^(it|that|this)$/i.test(name)) return { kind: 'restore_named', name };
  }

  if (/\b(what|which)\b.*\b(workspaces?|arrangements?|snapshots?)\b|\bmy (workspaces|snapshots)\b/.test(lower)) {
    return { kind: 'list' };
  }

  return null;
}

/**
 * The concurrent ceiling for a viewport — §8's "subject to device capacity",
 * and the "degrade rather than fail" half of it.
 *
 * On a phone every surface is full width, so twelve of them is a twelve-screen
 * scroll: technically working, practically a failure. Fewer surfaces on a small
 * device is the degradation the specification asks for.
 */
export function capacityFor(width: number): number {
  if (width < 640) return 4;
  if (width < 1024) return 8;
  return 12;
}
