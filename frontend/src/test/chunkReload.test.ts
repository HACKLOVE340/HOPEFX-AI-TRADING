import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CHUNK_RELOAD_COOLDOWN_MS,
  CHUNK_RELOAD_KEY,
  isChunkLoadError,
  tryChunkReload,
} from '../lib/chunkReload';

describe('isChunkLoadError', () => {
  it('detects ChunkLoadError by name', () => {
    const e = new Error('boom');
    e.name = 'ChunkLoadError';
    expect(isChunkLoadError(e)).toBe(true);
  });

  it('detects failed dynamic imports by message', () => {
    expect(isChunkLoadError(new Error('Failed to fetch dynamically imported module: /x.js'))).toBe(true);
    expect(isChunkLoadError(new Error('Loading chunk 42 failed'))).toBe(true);
    expect(isChunkLoadError(new Error('error loading dynamically imported module'))).toBe(true);
    expect(isChunkLoadError(new Error('Importing a module script failed'))).toBe(true);
  });

  it('ignores unrelated errors and falsy input', () => {
    expect(isChunkLoadError(new Error("Cannot read properties of undefined (reading 'x')"))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
    expect(isChunkLoadError(undefined)).toBe(false);
  });
});

describe('tryChunkReload', () => {
  let reload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    reload = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload },
    });
  });

  it('reloads once then loop-guards within the cooldown', () => {
    const t0 = 1_000_000;
    expect(tryChunkReload(t0)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(CHUNK_RELOAD_KEY)).toBe(String(t0));

    // Second attempt inside the cooldown must NOT reload (prevents a loop).
    expect(tryChunkReload(t0 + CHUNK_RELOAD_COOLDOWN_MS - 1)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('reloads again once the cooldown has elapsed', () => {
    const t0 = 2_000_000;
    expect(tryChunkReload(t0)).toBe(true);
    expect(tryChunkReload(t0 + CHUNK_RELOAD_COOLDOWN_MS + 1)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});
