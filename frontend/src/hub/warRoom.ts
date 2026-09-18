/**
 * hub/warRoom.ts — §20: a market war room, generated on demand.
 *
 * `war_room` already existed as a LAYOUT. `readLayout('war room')` returns it
 * and `suggestLayout` reaches for it once eight surfaces are open, so saying
 * "war room" rearranged whatever happened to be on the plane — and on an empty
 * plane it rearranged nothing and looked broken. §20 asks for one to be
 * GENERATED, which means assembling the panels rather than tidying the ones
 * already there.
 *
 * ## It must not fabricate one
 *
 * The obvious implementation opens all eight candidates. On a deployment with
 * no news feed and a flat book that is six panels reading "nothing is
 * connected to this yet" — a war room that looks like a dead platform, which
 * is worse than not opening one. So the set is filtered by what actually has
 * data.
 *
 * ## And what it leaves out is named
 *
 * Silently dropping the empty ones has its own failure: an operator who
 * expected a news panel and does not see one cannot tell whether the feed is
 * silent or the war room forgot. `omitted` is the answer to that question, and
 * `reason` is the sentence to say.
 *
 * ## Risk is critical, and that is load-bearing
 *
 * `layout.ts` folds `background` and `on_demand` surfaces into the collapsed
 * stack once the plane is crowded, and a war room is crowded by definition.
 * Risk turning into a chip at exactly the moment somebody opened a war room is
 * the one collapse that must not happen, so the tier is declared here rather
 * than left to whatever the panel's default is.
 */

import type { Priority, SurfaceKind, SurfaceRequest } from './contracts.shared';

export interface WarRoomCandidate {
  kind: SurfaceKind;
  /** The `surfaceData` key this panel reads. Also how "has it any data" is asked. */
  key: string;
  intent: string;
  priority: Priority;
}

/**
 * What a war room is made of, in the order it should appear.
 *
 * Every key here is one `surfaceData` already answers from a real feed. A
 * candidate whose key had no case would open a panel that could never fill,
 * which is the fabrication this module exists to avoid.
 */
export const WAR_ROOM_CANDIDATES: readonly WarRoomCandidate[] = Object.freeze([
  // Risk first and critical: see the module docstring.
  { kind: 'table', key: 'risk', intent: 'Risk limits and headroom', priority: 'critical' },
  { kind: 'chart', key: 'gold-chart', intent: 'Gold price', priority: 'primary' },
  { kind: 'table', key: 'positions', intent: 'Open positions', priority: 'primary' },
  { kind: 'news', key: 'news', intent: 'Market headlines', priority: 'secondary' },
  { kind: 'heatmap', key: 'session-heatmap', intent: 'Session movement', priority: 'secondary' },
  { kind: 'network', key: 'relationships', intent: 'How these relate', priority: 'secondary' },
  { kind: 'timeline', key: 'chronology', intent: 'What happened, in order', priority: 'secondary' },
  { kind: 'table', key: 'spend', intent: 'AI spend against the ceiling', priority: 'background' },
  { kind: 'agent_activity', key: 'agents', intent: 'What the agents are doing', priority: 'background' },
]);

export interface WarRoom {
  surfaces: SurfaceRequest[];
  /** Keys left out because their feed had nothing. Named, never dropped. */
  omitted: string[];
  /** One sentence, for the operator. Always populated. */
  reason: string;
}

/**
 * Assemble the war room from the feeds that currently have something.
 *
 * `hasData` is injected rather than read here so this stays a pure function —
 * the same split `layout.ts` and `useViewportWidth` already hold, and the
 * reason the whole set is testable without a store.
 */
export function warRoomSurfaces(hasData: (key: string) => boolean): WarRoom {
  const surfaces: SurfaceRequest[] = [];
  const omitted: string[] = [];

  for (const candidate of WAR_ROOM_CANDIDATES) {
    let filled = false;
    try {
      filled = hasData(candidate.key);
    } catch {
      // A probe that threw is not a feed with data. Opening the panel anyway
      // would put "nothing connected" on screen for a source that may be
      // perfectly healthy and merely unreadable from here.
      filled = false;
    }
    if (filled) {
      surfaces.push({
        kind: candidate.kind,
        intent: candidate.intent,
        priority: candidate.priority,
        key: candidate.key,
      });
    } else {
      omitted.push(candidate.key);
    }
  }

  return { surfaces, omitted, reason: explain(surfaces.length, omitted) };
}

function explain(opened: number, omitted: readonly string[]): string {
  if (opened === 0) {
    return (
      'Nothing has any data right now, so there is no war room to open. Every feed is either silent ' +
      'or not connected on this deployment.'
    );
  }
  if (omitted.length === 0) {
    return `War room: ${opened} panels, every feed reporting.`;
  }
  return (
    `War room: ${opened} panels. Left out because they have no data — ${omitted.join(', ')}. ` +
    'Empty panels would make a silent feed look like a working one.'
  );
}
