/**
 * Regression tests for two runtime-error-handling fixes:
 *
 *  1. extractApiError() used to leak the raw Axios string
 *     "timeout of 30000ms exceeded" (and bare network errors) straight to the
 *     UI across every one of its ~89 call sites. It must now return a
 *     friendly, actionable message for those cases while leaving every other
 *     branch (structured FastAPI `detail`, 404, plain err.message) unchanged.
 *
 *  2. The session-restore flow (_silentRefresh, exercised via
 *     authApi.restoreSession()) used to treat ANY failure — including a bare
 *     network timeout with no response at all — identically to a genuine
 *     "refresh token rejected" (401/403), forcing a real, valid session to be
 *     logged out on a mere network hiccup. It must now retry once on a
 *     transient failure and only give up (return null) on a DEFINITE
 *     rejection or a repeat transient failure.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { extractApiError } from '../lib/utils';

describe('extractApiError — timeout / network handling', () => {
  it('returns a friendly message for an Axios ECONNABORTED timeout (no response)', () => {
    const err = { code: 'ECONNABORTED', message: 'timeout of 30000ms exceeded' };
    expect(extractApiError(err)).toBe('Connection is slow or unavailable — please try again.');
  });

  it('returns a friendly message for a 60s/120s/180s timeout too (any ms value)', () => {
    for (const ms of [30000, 60000, 120000, 180000]) {
      const err = { code: 'ECONNABORTED', message: `timeout of ${ms}ms exceeded` };
      expect(extractApiError(err)).toBe('Connection is slow or unavailable — please try again.');
    }
  });

  it('returns a friendly message for a bare network error with no response', () => {
    const err = { code: 'ERR_NETWORK', message: 'Network Error' };
    expect(extractApiError(err)).toBe('Connection is slow or unavailable — please try again.');
  });

  it('detects a timeout message even without the ECONNABORTED code (defensive)', () => {
    const err = { message: 'timeout of 5000ms exceeded' };
    expect(extractApiError(err)).toBe('Connection is slow or unavailable — please try again.');
  });

  it('does NOT treat a real HTTP error response as a timeout, even if message looks similar', () => {
    const err = { response: { status: 500 }, message: 'timeout of 5000ms exceeded' };
    // Has a real response -> falls through to the normal message branch, not the timeout branch.
    expect(extractApiError(err)).toBe('timeout of 5000ms exceeded');
  });
});

describe('extractApiError — existing behaviour is unchanged (regression)', () => {
  it('prefers a structured FastAPI detail string', () => {
    const err = { response: { status: 422, data: { detail: 'Invalid symbol' } } };
    expect(extractApiError(err)).toBe('Invalid symbol');
  });

  it('unwraps a structured detail object with msg', () => {
    const err = { response: { status: 422, data: { detail: { msg: 'field required', loc: ['body', 'x'] } } } };
    expect(extractApiError(err)).toBe('field required');
  });

  it('returns the fallback (not the raw Axios message) for a bodyless 404', () => {
    const err = { response: { status: 404 }, message: 'Request failed with status code 404' };
    expect(extractApiError(err, 'Not found')).toBe('Not found');
  });

  it('returns the fallback for a bare rejection with nothing useful', () => {
    expect(extractApiError({}, 'Something went wrong')).toBe('Something went wrong');
  });

  it('falls back to err.message when there is no response and it is not a timeout/network shape', () => {
    const err = { message: 'Unexpected token in JSON' };
    expect(extractApiError(err)).toBe('Unexpected token in JSON');
  });

  it('returns the default fallback for null/undefined', () => {
    expect(extractApiError(null)).toBe('An error occurred');
    expect(extractApiError(undefined)).toBe('An error occurred');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Session-restore retry behaviour
// ─────────────────────────────────────────────────────────────────────────────
// Mock the bare `axios` module used internally by hooks/useApi.ts for the
// refresh/me calls (deliberately NOT the configured `api` instance, to avoid
// the interceptor calling back into itself — see the source comments).
const axiosPost = vi.fn();
const axiosGet = vi.fn();
vi.mock('axios', () => {
  const instance = {
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  };
  return {
    default: {
      create: () => instance,
      post: (...args: unknown[]) => axiosPost(...args),
      get: (...args: unknown[]) => axiosGet(...args),
    },
  };
});

describe('authApi.restoreSession — retry vs. definite rejection', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('retries once on a transient (timeout-shaped) failure and succeeds — does NOT treat it as logged out', async () => {
    const { authApi } = await import('../hooks/useApi');
    const { useStore } = await import('../store');
    useStore.setState({ user: { id: '1', email: 'a@b.com', role: 'user' } as never });

    axiosPost
      .mockRejectedValueOnce({ code: 'ECONNABORTED', message: 'timeout of 10000ms exceeded' })
      .mockResolvedValueOnce({ data: { access_token: 'fresh-token' } });

    const promise = authApi.restoreSession();
    // Let the first (failing) attempt settle, then fast-forward past the 1.5s retry pause.
    await vi.advanceTimersByTimeAsync(2000);
    const token = await promise;

    expect(token).toBe('fresh-token');
    expect(axiosPost).toHaveBeenCalledTimes(2); // one failed attempt + one retry, not treated as "logged out" after the first
  });

  it('gives up gracefully (returns null) if the transient failure repeats on retry', async () => {
    const { authApi } = await import('../hooks/useApi');
    axiosPost.mockRejectedValue({ code: 'ECONNABORTED', message: 'timeout of 10000ms exceeded' });

    const promise = authApi.restoreSession();
    await vi.advanceTimersByTimeAsync(2000);
    const token = await promise;

    expect(token).toBeNull();
    expect(axiosPost).toHaveBeenCalledTimes(2); // tried, retried once, then gave up — no more than that
  });

  it('returns null IMMEDIATELY on a definite 401 rejection — no wasted retry', async () => {
    const { authApi } = await import('../hooks/useApi');
    axiosPost.mockRejectedValue({ response: { status: 401 } });

    const token = await authApi.restoreSession();

    expect(token).toBeNull();
    expect(axiosPost).toHaveBeenCalledTimes(1); // a genuinely invalid refresh token must not be retried
  });

  it('returns null immediately on a definite 403 rejection too', async () => {
    const { authApi } = await import('../hooks/useApi');
    axiosPost.mockRejectedValue({ response: { status: 403 } });

    const token = await authApi.restoreSession();

    expect(token).toBeNull();
    expect(axiosPost).toHaveBeenCalledTimes(1);
  });

  it('sets a timeout on the bare refresh/me axios calls (regression: they previously had none)', async () => {
    const { authApi } = await import('../hooks/useApi');
    axiosPost.mockResolvedValue({ data: { access_token: 'tok' } });
    const { useStore } = await import('../store');
    useStore.setState({ user: { id: '1', email: 'a@b.com', role: 'user' } as never });

    await authApi.restoreSession();

    expect(axiosPost).toHaveBeenCalledWith(
      expect.stringContaining('/auth/refresh'),
      {},
      expect.objectContaining({ timeout: expect.any(Number) }),
    );
    const [, , opts] = axiosPost.mock.calls[0] as [string, unknown, { timeout: number }];
    expect(opts.timeout).toBeGreaterThan(0);
  });
});

describe('_isDefiniteAuthRejection — the core retry/no-retry decision', () => {
  it('is true for 401 and 403 only', async () => {
    const { _isDefiniteAuthRejection } = await import('../hooks/useApi');
    expect(_isDefiniteAuthRejection({ response: { status: 401 } })).toBe(true);
    expect(_isDefiniteAuthRejection({ response: { status: 403 } })).toBe(true);
  });

  it('is false for timeouts, network errors, 5xx, and anything with no response', async () => {
    const { _isDefiniteAuthRejection } = await import('../hooks/useApi');
    expect(_isDefiniteAuthRejection({ code: 'ECONNABORTED' })).toBe(false);
    expect(_isDefiniteAuthRejection({ code: 'ERR_NETWORK' })).toBe(false);
    expect(_isDefiniteAuthRejection({ response: { status: 500 } })).toBe(false);
    expect(_isDefiniteAuthRejection({ response: { status: 503 } })).toBe(false);
    expect(_isDefiniteAuthRejection({})).toBe(false);
    expect(_isDefiniteAuthRejection(null)).toBe(false);
    expect(_isDefiniteAuthRejection(undefined)).toBe(false);
  });
});
