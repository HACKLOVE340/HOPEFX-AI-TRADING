/**
 * hub/workspaceStore.ts — saving a workspace and getting the same one back.
 *
 * §23 asks for "a state store for workspace sessions". An operator arranges six
 * surfaces around a question, closes the tab, and comes back to it. The value
 * is entirely in the *same* arrangement returning; a workspace that restores
 * approximately is one nobody trusts enough to rely on.
 *
 * ## What it refuses to do quietly
 *
 * **It never comes back one panel short without saying so.** A saved session
 * referring to a surface kind this build no longer has — renamed, removed,
 * written by a newer deployment — cannot be restored, and the honest response
 * is to restore the rest and NAME what was dropped. Silently returning three of
 * four panels is the workspace losing the operator's work and telling them it
 * succeeded.
 *
 * **An unknown schema version is refused, not coerced.** Reading a future
 * session with today's rules produces something that looks restored and is not.
 * Refusing gives the operator a message; coercing gives them a wrong workspace.
 *
 * ## It stores plain data
 *
 * No class instances, no functions, no `undefined`. Whatever comes out of
 * `save()` has to survive `JSON.stringify` and a round trip through
 * localStorage or a server, or it is not a saved session at all — it is a live
 * object that happens to be reachable.
 */

import { PRIORITIES, SURFACE_KINDS, type Priority, type SurfaceKind } from './contracts.shared';

/** Bumped whenever the shape below changes in a way older readers cannot handle. */
export const SCHEMA_VERSION = 1;

export interface StoredSurface {
  id: string;
  kind: SurfaceKind;
  intent: string;
  priority: Priority;
  span: number;
}

export interface WorkspaceSession {
  surfaces: StoredSurface[];
  /** Null when nothing is focused, or when the focused surface did not survive. */
  focus: string | null;
  layout: string;
}

export interface StoredBlob {
  version: number;
  surfaces: unknown[];
  focus: string | null;
  layout: string;
  savedAt: number;
}

export interface Dropped {
  id: string;
  reason: string;
}

export interface RestoreResult {
  ok: boolean;
  session: WorkspaceSession | null;
  /** Everything that could not be restored, and why. Never silently empty. */
  dropped: Dropped[];
  /** Empty when `ok`. Populated whenever the blob could not be read at all. */
  reason: string;
}

export function save(session: {
  surfaces: readonly StoredSurface[];
  focus: string | null;
  layout: string;
}): StoredBlob {
  return {
    version: SCHEMA_VERSION,
    surfaces: session.surfaces.map((s) => ({
      id: s.id,
      kind: s.kind,
      intent: s.intent,
      priority: s.priority,
      span: s.span,
    })),
    focus: session.focus,
    layout: session.layout,
    savedAt: Date.now(),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function restore(blob: unknown): RestoreResult {
  if (!isRecord(blob)) {
    return refuse(`a saved workspace must be an object, got ${blob === null ? 'null' : typeof blob}`);
  }
  if (typeof blob.version !== 'number') {
    return refuse('the saved workspace has no schema version, so it cannot be read safely');
  }
  if (blob.version !== SCHEMA_VERSION) {
    // Coercing would produce something that looks restored and is not.
    return refuse(
      `saved workspace schema version ${blob.version} cannot be read by this build, which writes version ${SCHEMA_VERSION}`,
    );
  }
  if (!Array.isArray(blob.surfaces)) {
    return refuse('the saved workspace has no surfaces list');
  }

  const dropped: Dropped[] = [];
  const surfaces: StoredSurface[] = [];

  for (const [index, raw] of blob.surfaces.entries()) {
    const outcome = readSurface(raw, index);
    if ('reason' in outcome) dropped.push({ id: outcome.id, reason: outcome.reason });
    else surfaces.push(outcome.surface);
  }

  const requestedFocus = typeof blob.focus === 'string' ? blob.focus : null;
  let focus: string | null = null;
  if (requestedFocus !== null) {
    if (surfaces.some((s) => s.id === requestedFocus)) focus = requestedFocus;
    else {
      // A focus pointing at a panel that did not survive would leave the
      // workspace highlighting nothing, with no way to tell why.
      dropped.push({ id: requestedFocus, reason: 'focused surface did not survive the restore' });
    }
  }

  return {
    ok: true,
    session: { surfaces, focus, layout: typeof blob.layout === 'string' ? blob.layout : 'auto' },
    dropped,
    reason: '',
  };
}

type SurfaceOutcome = { surface: StoredSurface } | { id: string; reason: string };

function readSurface(raw: unknown, index: number): SurfaceOutcome {
  if (!isRecord(raw)) return { id: `#${index}`, reason: 'entry is not an object' };
  const id = typeof raw.id === 'string' && raw.id.trim() ? raw.id : `#${index}`;

  if (typeof raw.kind !== 'string') return { id, reason: 'entry has no surface kind' };
  if (!(SURFACE_KINDS as readonly string[]).includes(raw.kind)) {
    return { id, reason: `unknown surface kind: ${raw.kind}` };
  }
  if (typeof raw.intent !== 'string') return { id, reason: 'entry has no intent' };

  const priority =
    typeof raw.priority === 'string' && (PRIORITIES as readonly string[]).includes(raw.priority)
      ? (raw.priority as Priority)
      : null;
  if (priority === null) return { id, reason: `unknown priority: ${String(raw.priority)}` };

  const span = typeof raw.span === 'number' && Number.isFinite(raw.span) ? raw.span : null;
  if (span === null) return { id, reason: 'entry has no numeric span' };

  return { surface: { id, kind: raw.kind as SurfaceKind, intent: raw.intent, priority, span } };
}

function refuse(reason: string): RestoreResult {
  return { ok: false, session: null, dropped: [], reason };
}
