/**
 * lib/utils.ts — shared utility functions for the dashboard UI.
 *
 * Mirrors the extractApiError helper in frontend/src/lib/utils.ts so all
 * dashboard catch blocks use the same safe, instanceof-free error extraction.
 */

/**
 * Extract a human-readable error message from an Axios/fetch error.
 *
 * FastAPI can return `detail` as either a string or an object
 * ({msg, loc, type} on 422/503). This function handles both shapes
 * so callers never render [object Object].
 *
 * Priority: response.data.detail → response.data.message → err.message → fallback
 */
export function extractApiError(err: unknown, fallback = 'An error occurred'): string {
  if (err == null) return fallback;
  const data = (err as { response?: { data?: { detail?: unknown; message?: unknown } } })
    ?.response?.data;
  const raw = data?.detail ?? data?.message;
  if (typeof raw === 'string' && raw.length > 0) return raw;
  if (raw && typeof raw === 'object') {
    const d = raw as { msg?: string; message?: string };
    const s = d.msg ?? d.message;
    if (typeof s === 'string' && s.length > 0) return s;
    return JSON.stringify(raw);
  }
  const msg = (err as { message?: unknown })?.message;
  if (typeof msg === 'string' && msg.length > 0) return msg;
  return fallback;
}
