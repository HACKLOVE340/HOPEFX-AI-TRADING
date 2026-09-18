/**
 * hub/sceneGraph.ts — what is next to what, inside what, and in front of what.
 *
 * §23 asks for "a scene graph for spatial awareness". `hub/spatial.ts` already
 * answers *where one rectangle is* — top-left, centre, which third of the
 * screen. This answers the questions that need more than one panel to be
 * meaningful:
 *
 *   "the chart on the left"      → neighbour(id, 'left')
 *   "inside the war room"        → childrenOf / parentOf / ancestry
 *   "the panel behind that one"  → occludedBy
 *
 * Without it the AI can say where a panel is and cannot say which panel an
 * operator means by "the one under it" — which is most of how people refer to
 * things on a screen.
 *
 * ## Refusals, not silent nothings
 *
 * An unknown id throws rather than returning null. `neighbour('ghost', 'left')`
 * returning null reads identically to "there is nothing to the left of a panel
 * that really exists", and those are different bugs.
 *
 * A parent that does not exist is refused at `place()`, and a containment cycle
 * is refused at the moment the edge is made — the same rule `ai/bus/graph.py`
 * holds for tasks, for the same reason: a cycle found later has already been
 * walked into.
 *
 * ## No React, no DOM
 *
 * Rectangles are handed in. That keeps every rule above testable without a
 * browser, and keeps the layout engine independent of the renderer, which is
 * what §23 asks for in the first place.
 */

import type { Rect } from './spatial';

export type Direction = 'left' | 'right' | 'above' | 'below';

export interface PlaceOptions {
  parent?: string | null;
  /** Higher is nearer the viewer. Equal z never occludes. */
  z?: number;
}

interface Node {
  id: string;
  rect: Rect;
  parent: string | null;
  z: number;
}

function centre(rect: Rect): { x: number; y: number } {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

function overlaps(a: Rect, b: Rect): boolean {
  // Strict: two panels sharing an edge are adjacent, not overlapping. `<=`
  // here would report every tiled layout as fully occluded.
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

export class SceneGraph {
  private nodes = new Map<string, Node>();

  place(id: string, rect: Rect, options: PlaceOptions = {}): void {
    if (!id.trim()) throw new Error('a scene node needs an id');
    const parent = options.parent ?? null;
    if (parent !== null && !this.nodes.has(parent)) {
      throw new Error(`cannot place ${id} inside ${parent}: no such node`);
    }
    this.nodes.set(id, { id, rect, parent, z: options.z ?? 0 });
  }

  reparent(id: string, parent: string | null): void {
    const node = this.require(id);
    if (parent !== null) {
      if (!this.nodes.has(parent)) throw new Error(`no such node: ${parent}`);
      // Walk up from the proposed parent: if we reach `id`, this edge closes a
      // cycle. Checked here because once the edge exists no walk terminates.
      let cursor: string | null = parent;
      while (cursor !== null) {
        if (cursor === id) {
          throw new Error(`cannot put ${id} inside ${parent}: that would close a containment cycle`);
        }
        cursor = this.nodes.get(cursor)?.parent ?? null;
      }
    }
    node.parent = parent;
  }

  remove(id: string): void {
    // Children go with the parent. Leaving them behind puts a panel on the
    // plane whose container is gone, and nothing would ever remove it.
    for (const child of this.childrenOf(id)) this.remove(child);
    this.nodes.delete(id);
  }

  ids(): string[] {
    return [...this.nodes.keys()];
  }

  rectOf(id: string): Rect {
    return this.require(id).rect;
  }

  /** Draw order. Needed by `gestures.pointingAt` to answer the topmost panel. */
  zOf(id: string): number {
    return this.require(id).z;
  }

  parentOf(id: string): string | null {
    return this.require(id).parent;
  }

  childrenOf(id: string): string[] {
    return [...this.nodes.values()].filter((n) => n.parent === id).map((n) => n.id);
  }

  /** Outermost container first, `id` last. */
  ancestry(id: string): string[] {
    const chain: string[] = [];
    let cursor: string | null = id;
    while (cursor !== null) {
      chain.unshift(cursor);
      cursor = this.require(cursor).parent;
    }
    return chain;
  }

  /**
   * The nearest node in `direction`, or null when there is nothing that way.
   *
   * Nearest by centre distance, so "the chart on the left" means the one beside
   * it rather than whichever happens to come first in the map.
   */
  neighbour(id: string, direction: Direction): string | null {
    const from = this.require(id);
    const origin = centre(from.rect);

    let best: { id: string; distance: number } | null = null;
    for (const node of this.nodes.values()) {
      if (node.id === id) continue;
      const point = centre(node.rect);
      const inDirection =
        direction === 'left'
          ? point.x < origin.x
          : direction === 'right'
            ? point.x > origin.x
            : direction === 'above'
              ? point.y < origin.y
              : point.y > origin.y;
      if (!inDirection) continue;
      const distance = Math.hypot(point.x - origin.x, point.y - origin.y);
      if (best === null || distance < best.distance) best = { id: node.id, distance };
    }
    return best === null ? null : best.id;
  }

  /** Nodes drawn in front of `id` and overlapping it, nearest-first by z. */
  occludedBy(id: string): string[] {
    const node = this.require(id);
    return [...this.nodes.values()]
      .filter((other) => other.id !== id && other.z > node.z && overlaps(node.rect, other.rect))
      .sort((a, b) => a.z - b.z)
      .map((other) => other.id);
  }

  private require(id: string): Node {
    const node = this.nodes.get(id);
    if (node === undefined) {
      // Not null: "no such panel" and "nothing in that direction" are different
      // facts, and one value for both hides one of them.
      throw new Error(`no node named ${id} in this scene`);
    }
    return node;
  }
}
