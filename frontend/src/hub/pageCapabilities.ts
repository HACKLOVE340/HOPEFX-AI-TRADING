/**
 * hub/pageCapabilities.ts — what the AI may do on the page it is standing on.
 *
 * ## Two lists, never merged
 *
 * `readable` is what it can look at. `requestable` is what it can ask for. They
 * are separate fields and there is deliberately no combined one, because a
 * caller handed a single list would reasonably conclude that everything on it
 * can be done.
 *
 * `ai/agent/loop.py` holds the same split between `permitted` and
 * `platform_context` for the same reason, and `ai/hub/app_surface.py` reports
 * `visible` and `invokable` as two numbers rather than one. This is that
 * discipline arriving at the page level.
 *
 * The gate itself is unchanged and is not here: anything that acts still goes
 * through `ai/tools/bus.py`, the permission registry and the sixteen
 * constitutional invariants, with an authenticated operator. A presence overlay
 * must not become a second way to place a trade.
 *
 * ## A write with no tool is unavailable, not absent
 *
 * "The AI cannot do this" and "this does not exist" are different answers to an
 * operator asking why nothing happened. Writes with no registered tool are
 * listed in `unavailable` with the reason rather than filtered out.
 */

export interface SurfaceEntry {
  method: string;
  path: string;
  mode: string;
  area: string;
  summary?: string;
  tool?: string;
  invokable?: boolean;
}

export interface Unavailable {
  path: string;
  reason: string;
}

export interface PageCapabilities {
  /** What the AI can look at here. */
  readable: SurfaceEntry[];
  /** What it can ask to have done here, still behind the tool bus's gates. */
  requestable: SurfaceEntry[];
  /** Writes that exist and cannot be invoked, and why. */
  unavailable: Unavailable[];
  counts: { readable: number; requestable: number; unavailable: number };
  /** Populated when this area offers nothing, so an empty list has an explanation. */
  reason: string;
}

export function pageCapabilities(request: {
  area: string;
  surface: readonly SurfaceEntry[];
}): PageCapabilities {
  const here = request.surface.filter((entry) => entry.area === request.area);

  const readable = here.filter((entry) => entry.mode === 'read');
  const requestable = here.filter((entry) => entry.mode !== 'read' && entry.invokable === true);
  const unavailable = here
    .filter((entry) => entry.mode !== 'read' && entry.invokable !== true)
    .map((entry) => ({
      path: entry.path,
      reason: 'no tool is registered for it, so the AI cannot invoke it',
    }));

  const empty = readable.length === 0 && requestable.length === 0;
  return {
    readable,
    requestable,
    unavailable,
    counts: { readable: readable.length, requestable: requestable.length, unavailable: unavailable.length },
    reason: empty
      ? `nothing in the ${request.area} area is exposed to the AI; this page is one it can be present on and not act in`
      : '',
  };
}
