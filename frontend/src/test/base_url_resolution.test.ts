/**
 * base_url_resolution.test.ts
 * ===========================
 * `.env.example` ships `VITE_API_URL=` and `VITE_WS_URL=` — present but empty.
 *
 * An empty string is not nullish, so `import.meta.env.VITE_API_URL ?? '/api'`
 * evaluates to `''`, and axios with `baseURL: ''` resolves every request against
 * the page origin — `/positions` instead of `/api/positions`. Four call sites
 * read these variables and three used `??`; only `getWsBase` used a truthy check.
 *
 * This was latent rather than live: nothing passed VITE_* into the Docker build,
 * so the bundle saw `undefined` and the `??` fallbacks worked by accident. That
 * is also the second half of the defect — `.env.example` documented VITE_API_URL
 * as the way to point the UI at a separate API domain, and setting it did
 * nothing, because Vite reads `frontend/.env` and inlines at build time while the
 * value lived in the root `.env` consumed at container start.
 *
 * Fixing only the build wiring would have converted a latent bug into an outage:
 * the empty value from `.env.example` would have reached the bundle and blanked
 * every base URL. The two halves have to land together, which is why the
 * empty-string cases below matter more than the configured ones.
 *
 * The second disagreement these pin down is what the value *means*.
 * `.env.example` documents `VITE_WS_URL=wss://api.YOUR_DOMAIN` — an origin —
 * and callers append `/ws/live`. `useWebSocket.ts` and `orchestrator-ws.ts`
 * used it as the complete socket URL, so setting it connected to the origin
 * with no endpoint path.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const ORIGINAL = { ...import.meta.env };

function setEnv(vars: Record<string, string | undefined>) {
  for (const [k, v] of Object.entries(vars)) {
    if (v === undefined) {
      delete (import.meta.env as Record<string, unknown>)[k];
    } else {
      (import.meta.env as Record<string, unknown>)[k] = v;
    }
  }
}

async function freshUtils() {
  vi.resetModules();
  return await import('../lib/utils');
}

beforeEach(() => {
  setEnv({ VITE_API_URL: undefined, VITE_WS_URL: undefined });
});

afterEach(() => {
  for (const key of Object.keys(import.meta.env)) {
    if (!(key in ORIGINAL)) delete (import.meta.env as Record<string, unknown>)[key];
  }
  Object.assign(import.meta.env, ORIGINAL);
});

describe('getApiBase', () => {
  it('falls back to /api when the variable is absent', async () => {
    const { getApiBase } = await freshUtils();
    expect(getApiBase()).toBe('/api');
  });

  it('falls back to /api when the variable is present but empty', async () => {
    // The exact shape .env.example ships. `?? '/api'` returned '' here, which
    // makes axios resolve every path against the page origin.
    setEnv({ VITE_API_URL: '' });
    const { getApiBase } = await freshUtils();
    expect(getApiBase()).toBe('/api');
  });

  it('uses a configured absolute API origin', async () => {
    setEnv({ VITE_API_URL: 'https://api.example.com' });
    const { getApiBase } = await freshUtils();
    expect(getApiBase()).toBe('https://api.example.com');
  });
});

describe('getWsBase', () => {
  it('derives wss:// from the page origin on HTTPS', async () => {
    const { getWsBase } = await freshUtils();
    // jsdom default origin is http://localhost:3000
    expect(getWsBase()).toBe(`ws://${window.location.host}`);
  });

  it('falls back to the page origin when the variable is present but empty', async () => {
    setEnv({ VITE_WS_URL: '' });
    const { getWsBase } = await freshUtils();
    expect(getWsBase()).toBe(`ws://${window.location.host}`);
  });

  it('uses a configured absolute WS origin', async () => {
    setEnv({ VITE_WS_URL: 'wss://api.example.com' });
    const { getWsBase } = await freshUtils();
    expect(getWsBase()).toBe('wss://api.example.com');
  });

  it('returns an origin with no trailing slash, so callers can append a path', async () => {
    setEnv({ VITE_WS_URL: 'wss://api.example.com/' });
    const { getWsBase } = await freshUtils();
    expect(getWsBase()).toBe('wss://api.example.com');
    expect(`${getWsBase()}/ws/live`).toBe('wss://api.example.com/ws/live');
  });
});

describe('the endpoint path survives a configured origin', () => {
  it('useWebSocket targets /ws/live, not the bare origin', async () => {
    // The regression: `envUrl ?? ...` used VITE_WS_URL verbatim, so a value of
    // wss://api.example.com connected to the origin with no endpoint path.
    setEnv({ VITE_WS_URL: 'wss://api.example.com' });
    const { getWsBase } = await freshUtils();
    expect(`${getWsBase()}/ws/live`).toBe('wss://api.example.com/ws/live');
  });
});

describe('call sites go through the shared resolvers', () => {
  const read = async (p: string) => {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    return fs.readFile(path.resolve(__dirname, p), 'utf-8');
  };

  it('useApi.ts does not re-read VITE_API_URL itself', async () => {
    const src = await read('../hooks/useApi.ts');
    const code = src.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(code).not.toContain('import.meta.env.VITE_API_URL');
    expect(code).toContain('getApiBase');
  });

  it.each([
    ['../hooks/useWebSocket.ts'],
    ['../features/chart-bot/services/orchestrator-ws.ts'],
  ])('%s does not re-read VITE_WS_URL itself', async (file) => {
    const src = await read(file);
    const code = src.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(code).not.toContain('import.meta.env.VITE_WS_URL');
    expect(code).toContain('getWsBase');
  });
});
