/**
 * hub/workspace.ts — the generative workspace engine.
 *
 * §8, which the specification calls the core differentiator: "The workspace
 * engine receives a task intent and creates, updates, rearranges and removes
 * visual surfaces based on relevance."
 *
 * The distinction it exists to make is between a dashboard and a canvas. A
 * dashboard's panels were decided when the code was written and are there
 * whether or not they matter. Here a surface exists because something asked for
 * it, sits where its importance puts it, and leaves when it stops being
 * relevant.
 *
 * ## It holds no React and draws nothing
 *
 * It owns *what should be on the plane and how much room each thing gets*. That
 * makes every rule below testable without a browser: the priority ordering, the
 * concurrent ceiling, pinning, replacing rather than duplicating, and what
 * happens to focus when the focused surface closes.
 *
 * §23 asks for the layout engine to be independent of the content engine, and
 * this is that boundary: the engine assigns a `span`, the renderer decides what
 * a span looks like.
 */

import { SURFACE_KINDS, type SurfaceKind, type SurfaceRequest } from './contracts.shared';

export type SurfacePriority = 'critical' | 'primary' | 'secondary' | 'background' | 'on_demand';

export interface Surface {
  id: string;
  /**
   * Narrowed to the registry's union rather than left as `string`.
   *
   * A surface only exists if its kind passed `SURFACE_KINDS.includes` in
   * `open()`, so the wider type was never true — and it meant `snapshot()`
   * could not return `SurfaceRequest[]` without a cast, which is the sort of
   * cast that later turns out to be hiding something.
   */
  kind: SurfaceKind;
  /** What it MEANS, in words the AI would use aloud. §9 resolves against this. */
  meaning: string;
  priority: SurfacePriority;
  /** Grid columns out of 12. The engine's placement decision, not the view's. */
  span: number;
  data: Record<string, unknown>;
  pinned: boolean;
  key: string;
  openedAt: number;
  /**
   * Monotonic open counter.
   *
   * Recency was `openedAt`, which is `Date.now()` — three surfaces opened in
   * one millisecond all tie, and the tie-break made the engine evict the
   * SECOND-newest while believing it was evicting the oldest. A counter cannot
   * tie.
   */
  order: number;
}

export interface WorkspaceOptions {
  /**
   * §8: "1-20+ concurrent surfaces subject to device capacity." Twelve is a
   * desktop default; a caller that knows the device passes its own.
   */
  maxSurfaces?: number;
  now?: () => number;
}

/** Rank for ordering and for deciding what gets evicted first. */
const RANK: Record<SurfacePriority, number> = {
  critical: 0,
  primary: 1,
  secondary: 2,
  background: 3,
  on_demand: 4,
};

/**
 * How much room each tier gets, in twelfths.
 *
 * §10: "Critical information receives dominant placement. Supporting context
 * remains visible but quieter." Placement is a consequence of importance rather
 * than of the order things happened to open.
 */
const SPAN: Record<SurfacePriority, number> = {
  critical: 12,
  primary: 6,
  secondary: 4,
  background: 3,
  on_demand: 3,
};

/**
 * Words that match everything and therefore mean nothing here.
 *
 * Without this, "nothing like this" resolved to a chart whose meaning was "gold
 * price THIS session" — one accidental word, and the AI would have gone on to
 * describe a panel the operator never referred to. Returning null is only
 * useful if the score that beats it is real evidence.
 */
const STOPWORDS = new Set([
  'the', 'this', 'that', 'these', 'those', 'and', 'for', 'with', 'about',
  'show', 'give', 'need', 'want', 'please', 'from', 'into', 'onto', 'what',
  'whats', 'have', 'has', 'are', 'was', 'were', 'can', 'you', 'your', 'his',
  'her', 'its', 'our', 'their', 'not', 'but', 'all', 'any', 'now', 'then',
]);

const DEFAULT_MAX = 12;

export class Workspace {
  private items: Surface[] = [];
  private focusedId: string | null = null;
  private seq = 0;
  private capacity: number;
  private readonly now: () => number;

  constructor(options: WorkspaceOptions = {}) {
    this.capacity = options.maxSurfaces ?? DEFAULT_MAX;
    this.now = options.now ?? Date.now;
  }

  /** Ordered by importance, then by recency within a tier. */
  get surfaces(): readonly Surface[] {
    return [...this.items].sort(
      (a, b) => RANK[a.priority] - RANK[b.priority] || b.order - a.order,
    );
  }

  get focused(): string | null {
    return this.focusedId;
  }

  /**
   * Put something on the plane. Returns its id.
   *
   * Asking twice for the same `key` updates the surface rather than opening a
   * second one — "show me gold" twice is one chart. Duplicates are how a
   * generative workspace becomes something nobody can read.
   */
  open(request: SurfaceRequest): string {
    if (!SURFACE_KINDS.includes(request.kind)) {
      throw new Error(
        `unknown surface kind ${request.kind}; nothing would render, so nothing is opened`,
      );
    }
    const priority = (request.priority ?? 'secondary') as SurfacePriority;
    const key = request.key ?? '';

    const existing = key ? this.items.find((s) => s.key === key) : undefined;
    if (existing) {
      existing.meaning = request.intent;
      existing.priority = priority;
      existing.span = SPAN[priority];
      existing.data = request.data ?? {};
      existing.openedAt = this.now();
      existing.order = ++this.seq;
      return existing.id;
    }

    const surface: Surface = {
      id: `s${++this.seq}`,
      kind: request.kind,
      meaning: request.intent,
      priority,
      span: SPAN[priority],
      data: request.data ?? {},
      pinned: false,
      key,
      openedAt: this.now(),
      order: ++this.seq,
    };
    this.items.push(surface);
    this.evict();
    return surface.id;
  }

  close(id: string): void {
    this.items = this.items.filter((s) => s.id !== id);
    // A focus pointing at a surface nobody can see is how the AI ends up
    // explaining something that is not on screen.
    if (this.focusedId === id) this.focusedId = null;
  }

  /** "Simplify this." Keeps whatever the operator pinned. */
  clear(): void {
    this.items = this.items.filter((s) => s.pinned);
    if (this.focusedId && !this.items.some((s) => s.id === this.focusedId)) this.focusedId = null;
  }

  pin(id: string, pinned = true): void {
    const surface = this.items.find((s) => s.id === id);
    if (surface) surface.pinned = pinned;
  }

  focus(id: string | null): void {
    this.focusedId = id && this.items.some((s) => s.id === id) ? id : null;
  }

  /**
   * Turn "the gold chart" into a surface. §9.
   *
   * Word overlap against meaning and kind, and null rather than a guess:
   * pointing at the wrong panel while confidently describing another is worse
   * than asking which one.
   */
  resolve(phrase: string): string | null {
    const wanted = phrase
      .toLowerCase()
      .split(/\s+/)
      .filter((w) => w.length >= 3 && !STOPWORDS.has(w));
    if (wanted.length === 0) return null;
    let best: { score: number; id: string } | null = null;
    for (const surface of this.items) {
      const hay = `${surface.meaning} ${surface.kind}`.toLowerCase().split(/\s+/);
      const score = wanted.filter((w) => hay.some((h) => h.includes(w) || w.includes(h))).length;
      if (score > 0 && (best === null || score > best.score)) best = { score, id: surface.id };
    }
    return best?.id ?? null;
  }

  /**
   * What is on the plane, as the requests that would rebuild it.
   *
   * Requests rather than surfaces, deliberately: a `Surface` carries ids,
   * timestamps and a span that a later version of the layout engine will
   * compute differently. Storing those would make a restored workspace a
   * fossil of the engine that saved it. A request is what was *asked for*, and
   * that is the thing worth keeping.
   */
  snapshot(): SurfaceRequest[] {
    return this.surfaces.map((surface) => ({
      kind: surface.kind,
      intent: surface.meaning,
      priority: surface.priority,
      key: surface.key,
      data: surface.data,
    }));
  }

  /**
   * Rebuild the plane from a snapshot. Returns what could not be restored.
   *
   * A kind that no longer exists is skipped rather than thrown, and named in
   * the return value. Throwing would lose the entire arrangement because one
   * panel type was renamed six months ago — the restore would fail exactly when
   * it is most valuable, on the oldest snapshot.
   */
  restore(requests: readonly SurfaceRequest[]): { restored: number; skipped: string[] } {
    this.items = this.items.filter((s) => s.pinned);
    this.focusedId = null;
    const skipped: string[] = [];
    let restored = 0;
    for (const request of requests) {
      if (!SURFACE_KINDS.includes(request.kind)) {
        skipped.push(request.kind);
        continue;
      }
      this.open(request);
      restored += 1;
    }
    return { restored, skipped };
  }

  /**
   * Change the concurrent ceiling — §8's "subject to device capacity".
   *
   * Evicting immediately rather than at the next open is the point: rotating a
   * phone to portrait with twelve surfaces open must reduce them now, not leave
   * a twelve-screen scroll standing until somebody asks for a thirteenth.
   */
  setCapacity(max: number): void {
    this.capacity = Math.max(1, Math.floor(max));
    this.evict();
  }

  get capacityLimit(): number {
    return this.capacity;
  }

  /**
   * Honour the ceiling by dropping the least important thing.
   *
   * Never the newest — that is what the operator just asked for, and dropping it
   * would make the ceiling look like a bug. Never a pinned one: pinning is the
   * operator saying this matters more than the engine's opinion.
   */
  private evict(): void {
    while (this.items.length > this.capacity) {
      const candidates = this.items.filter((s) => !s.pinned);
      if (candidates.length === 0) return;
      const newest = this.items.reduce((a, b) => (a.order >= b.order ? a : b));
      const victim = candidates
        .filter((s) => s.id !== newest.id)
        .sort((a, b) => RANK[b.priority] - RANK[a.priority] || a.order - b.order)[0];
      if (!victim) return;
      this.close(victim.id);
    }
  }
}
