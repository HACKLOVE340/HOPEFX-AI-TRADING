/**
 * hub/displays.ts — §10: a console that knows how many screens it is on.
 *
 * This row was staged with a note saying it needed "a second physical screen
 * this deployment does not have". The Window Management API is a browser API,
 * and the code plus its honest degradation are buildable without owning a
 * monitor. Being unable to *verify* placement on real hardware is a reason to
 * say so — see the note in the registry — not a reason to call the work
 * blocked.
 *
 * ## Three states, not one boolean
 *
 * The API is Chromium-only and permission-gated, so most of the time it is
 * simply absent. These look alike and are not:
 *
 *   `unsupported`  this browser has no Window Management API at all
 *   `unpermitted`  it has one and the operator has not granted it
 *   `measured`     it answered, and the count is real — including one
 *
 * Collapsing them into "no extra screens" is §22's rule broken in a new place:
 * an unmeasured display count is ABSENT, never zero. An operator on a
 * three-monitor desk told they have one screen goes looking for a fault in
 * their hardware, which is a worse outcome than being told the browser cannot
 * see them.
 *
 * ## Rendering never asks for permission
 *
 * `getScreenDetails()` prompts. Calling it because a component mounted makes
 * *opening the app* the request — the same mistake the camera panel made
 * before §25, and a prompt nobody asked for is one people learn to dismiss.
 * `readDisplays({ probe: true })` reports what can be known without asking;
 * only an explicit operator action calls it for real.
 *
 * ## Risk does not move to a monitor nobody is watching
 *
 * When the plane spreads, the critical surface stays on the primary screen.
 * Same reasoning that made risk `critical` in the war room so a crowded plane
 * could not fold it into a chip: the panel that matters most is the one that
 * must not end up somewhere peripheral.
 */

export const DISPLAY_STATES = ['unsupported', 'unpermitted', 'measured'] as const;
export type DisplayState = (typeof DISPLAY_STATES)[number];

export interface ScreenInfo {
  label: string;
  left: number;
  top: number;
  width: number;
  height: number;
  isPrimary: boolean;
}

export interface DisplaySnapshot {
  state: DisplayState;
  screens: ScreenInfo[];
  /** Null unless `state` is `measured`. Null is a fact, not a zero. */
  count: number | null;
  /** Empty when measured. Says which of the two absences this is otherwise. */
  reason: string;
}

export interface ReadOptions {
  /**
   * Report without prompting.
   *
   * True on every automatic read — a mount, a resize, a poll. Only an explicit
   * operator action passes false, because that is the only moment a permission
   * prompt is something they asked for.
   */
  probe?: boolean;
}

function unmeasured(state: DisplayState, reason: string): DisplaySnapshot {
  return { state, screens: [], count: null, reason };
}

/** A screen with no area is not somewhere a panel can go. */
function usable(screen: ScreenInfo): boolean {
  return (
    Number.isFinite(screen.width) && Number.isFinite(screen.height) && screen.width > 0 && screen.height > 0
  );
}

export async function readDisplays(options: ReadOptions = {}): Promise<DisplaySnapshot> {
  const host = typeof window === 'undefined' ? undefined : (window as unknown as Record<string, unknown>);
  if (!host || typeof host.getScreenDetails !== 'function') {
    return unmeasured(
      'unsupported',
      'this browser has no Window Management API, so it cannot say how many screens there are',
    );
  }

  if (options.probe) {
    return unmeasured(
      'unpermitted',
      'the screen layout has not been requested; granting it is an action you take, and opening the app is not one',
    );
  }

  let details: unknown;
  try {
    details = await (host.getScreenDetails as () => Promise<unknown>)();
  } catch (error) {
    const name = error instanceof Error ? error.name : 'unknown error';
    return unmeasured(
      'unpermitted',
      `permission to see the screen layout has not been granted (${name})`,
    );
  }

  const raw = (details as { screens?: unknown })?.screens;
  if (!Array.isArray(raw)) {
    // It answered with something this does not understand. Trusting it would
    // put panels on screens that may not exist.
    return unmeasured(
      'unsupported',
      'the browser returned a screen layout in a shape this app does not understand',
    );
  }

  const screens: ScreenInfo[] = raw
    .map((entry, index) => {
      const s = (entry ?? {}) as Record<string, unknown>;
      return {
        label: typeof s.label === 'string' && s.label ? s.label : `screen ${index + 1}`,
        left: Number(s.left) || 0,
        top: Number(s.top) || 0,
        width: Number(s.width) || 0,
        height: Number(s.height) || 0,
        isPrimary: Boolean(s.isPrimary),
      };
    })
    .filter(usable);

  if (screens.length === 0) {
    return unmeasured('unsupported', 'the browser reported no usable screens, which cannot be right');
  }
  return { state: 'measured', screens, count: screens.length, reason: '' };
}

/** The snapshot in a sentence, for an operator. Never claims what it does not know. */
export function describeDisplays(snapshot: DisplaySnapshot): string {
  if (snapshot.state === 'measured') {
    const n = snapshot.count ?? snapshot.screens.length;
    return n === 1
      ? 'One screen. The plane uses all of it.'
      : `${n} screens. The plane can spread across them, and risk stays on the primary one.`;
  }
  const why = snapshot.reason ? ` — ${snapshot.reason}` : '';
  return `This app cannot see how many screens you have${why}. Everything stays on this one.`;
}

export interface PlaceableSurface {
  id: string;
  priority: 'critical' | 'primary' | 'secondary' | 'background' | 'on_demand';
}

export interface DisplayPlan {
  /** Screen label to the surface ids on it. One key when not spread. */
  byScreen: Record<string, string[]>;
  /** Whether more than one screen is actually in use. */
  spread: boolean;
  reason: string;
}

/** Tiers that stay where the operator is looking. */
const STAYS_PRIMARY = new Set(['critical', 'primary']);

/**
 * Decide which surface goes on which screen.
 *
 * Pure — the snapshot is handed in — for the same reason `layout.ts` is: the
 * placement rules should be testable without a browser, let alone without two
 * monitors.
 */
export function assignSurfacesToScreens(
  surfaces: readonly PlaceableSurface[],
  snapshot: DisplaySnapshot,
): DisplayPlan {
  const ids = surfaces.map((s) => s.id);

  if (snapshot.state !== 'measured' || snapshot.screens.length <= 1) {
    // Exactly today's behaviour. An unmeasured count must not become a guess
    // at a second monitor — see the module docstring.
    const label = snapshot.state === 'measured' ? (snapshot.screens[0]?.label ?? '') : '';
    return {
      byScreen: { [label]: ids },
      spread: false,
      reason:
        snapshot.state === 'measured'
          ? 'One screen, so the whole plane is on it.'
          : `Could not tell how many screens there are, so the whole plane stays on this one — ${snapshot.reason}`,
    };
  }

  const primary = snapshot.screens.find((s) => s.isPrimary) ?? snapshot.screens[0]!;
  const others = snapshot.screens.filter((s) => s.label !== primary.label);

  const byScreen: Record<string, string[]> = { [primary.label]: [] };
  for (const other of others) byScreen[other.label] = [];

  const overflow: PlaceableSurface[] = [];
  for (const surface of surfaces) {
    if (STAYS_PRIMARY.has(surface.priority)) byScreen[primary.label]!.push(surface.id);
    else overflow.push(surface);
  }

  // Round-robin the rest across the secondary screens. Not by area or by
  // guessing where somebody is looking: both would be inventions, and an even
  // split is at least a rule an operator can predict.
  overflow.forEach((surface, index) => {
    const target = others[index % others.length]!;
    byScreen[target.label]!.push(surface.id);
  });

  return {
    byScreen,
    spread: true,
    reason: `${snapshot.screens.length} screens. Critical and primary surfaces stay on ${primary.label}.`,
  };
}
