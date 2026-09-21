/**
 * chunkReload.ts
 * Detect and recover from stale-build dynamic-import (React.lazy) failures.
 *
 * After a redeploy, the currently-loaded index.html references chunk file
 * hashes that no longer exist on the server, so the next lazy import throws a
 * ChunkLoadError / "Failed to fetch dynamically imported module". The fix is a
 * hard reload to fetch the fresh index.html + chunks — guarded so a genuinely
 * broken chunk can't reload forever.
 */

const CHUNK_ERROR_RE =
  /loading chunk|loading css chunk|failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module/i;

/** True when *err* looks like a failed dynamic import / chunk load. */
export function isChunkLoadError(err: unknown): boolean {
  if (!err) return false;
  const name = (err as { name?: string }).name ?? '';
  const message = (err as { message?: string }).message ?? '';
  return name === 'ChunkLoadError' || CHUNK_ERROR_RE.test(message);
}

export const CHUNK_RELOAD_KEY = 'hopefx_chunk_reload_at';

/** Cooldown (ms) within which we won't reload again — the loop guard. */
export const CHUNK_RELOAD_COOLDOWN_MS = 10_000;

/**
 * Reload once to pick up a fresh build. Returns false if we reloaded within the
 * cooldown window (so the caller shows a real error instead of looping).
 *
 * @param now  injectable clock for tests (defaults to Date.now())
 */
export function tryChunkReload(now: number = Date.now()): boolean {
  try {
    const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) ?? '0');
    if (now - last < CHUNK_RELOAD_COOLDOWN_MS) return false; // reloaded recently
    sessionStorage.setItem(CHUNK_RELOAD_KEY, String(now));
    window.location.reload();
    return true;
  } catch {
    // sessionStorage unavailable (private mode) — best-effort single reload.
    window.location.reload();
    return true;
  }
}
