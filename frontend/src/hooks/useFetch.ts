/**
 * hooks/useFetch.ts
 *
 * Universal data-fetching hook for pages that use manual api.get() calls
 * (not React Query). Provides:
 *   - AbortController — cancels the in-flight request when the component
 *     unmounts, preventing "Can't perform a React state update on an
 *     unmounted component" crashes.
 *   - Hard deadline — if the fetch hasn't resolved in `timeoutMs` (default
 *     8 s), loading is forced false and a timeout error is shown so the page
 *     never hangs.
 *   - Ref guard — skips setState calls after unmount even if the promise
 *     resolves just after the deadline fires.
 *
 * Usage — replace this pattern:
 *
 *   const [loading, setLoading] = useState(true);
 *   const [error,   setError]   = useState<string | null>(null);
 *   const [data,    setData]    = useState<T | null>(null);
 *
 *   useEffect(() => {
 *     setLoading(true);
 *     api.get('/endpoint')
 *       .then(r => setData(r.data))
 *       .catch(err => setError(extractApiError(err, 'Failed')))
 *       .finally(() => setLoading(false));
 *   }, [deps]);
 *
 * With:
 *
 *   const { loading, error, data, run } = useFetch<T>(() =>
 *     api.get('/endpoint').then(r => r.data)
 *   );
 *   // `run` is stable — safe to call from callbacks to refetch.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ── Shared error extractor ────────────────────────────────────────────────────
// FastAPI can return detail as an object ({msg, loc, type}) on 503/422.
// Probe .msg → .message → JSON.stringify before falling back to err.message.
function extractFetchError(err: unknown): string {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const data = (err as { response?: { data?: { detail?: unknown; message?: unknown } } })
      .response?.data;
    const raw = data?.detail ?? data?.message;
    if (typeof raw === 'string') return raw;
    if (raw && typeof raw === 'object') {
      const d = raw as { msg?: string; message?: string };
      return d.msg ?? d.message ?? JSON.stringify(raw);
    }
  }
  const msg = (err as { message?: unknown })?.message;
  return typeof msg === 'string' && msg.length > 0 ? msg : 'Request failed.';
}

export interface FetchState<T> {
  loading: boolean;
  error:   string | null;
  data:    T | null;
  /** Manually trigger (or re-trigger) the fetch. */
  run:     () => void;
}

/**
 * Fetches data once on mount (and whenever `run()` is called).
 *
 * @param fetcher   A function that performs the API call and returns a Promise
 *                  resolving to the data value.  The AbortSignal is passed as
 *                  the first argument — forward it to axios: `{ signal }`.
 * @param timeoutMs Hard deadline in milliseconds (default: 8000).
 */
export function useFetch<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  timeoutMs = 8_000,
): FetchState<T> {
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const [data,    setData]    = useState<T | null>(null);

  // Track mount state so we never call setState after unmount.
  const mountedRef  = useRef(true);
  // Abort controller reference so run() can cancel the previous request.
  const abortRef    = useRef<AbortController | null>(null);
  // Stable fetcher ref (avoids adding fetcher to the dependency array).
  const fetcherRef  = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(() => {
    // Cancel any in-flight request.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    if (mountedRef.current) {
      setLoading(true);
      setError(null);
    }

    // Hard deadline — force loading false after timeoutMs.
    const deadlineId = setTimeout(() => {
      if (mountedRef.current && !controller.signal.aborted) {
        controller.abort();
        setLoading(false);
        setError('Request timed out. Please check your connection and try again.');
      }
    }, timeoutMs);

    fetcherRef.current(controller.signal)
      .then((value) => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          setData(value);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          const name = (err as { name?: unknown })?.name;
          if (name === 'AbortError' || name === 'CanceledError') return; // intentional cancel
          setError(extractFetchError(err));
        }
      })
      .finally(() => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          setLoading(false);
        }
      });
  }, [timeoutMs]);

  // Run on mount.
  useEffect(() => {
    mountedRef.current = true;
    run();
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { loading, error, data, run };
}

/**
 * Variant that re-runs whenever `deps` change (like useEffect deps).
 * Use this when the fetch depends on URL params, filters, or pagination.
 */
export function useFetchDeps<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  deps: readonly any[],
  timeoutMs = 8_000,
): FetchState<T> {
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const [data,    setData]    = useState<T | null>(null);

  const mountedRef = useRef(true);
  const abortRef   = useRef<AbortController | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    if (mountedRef.current) {
      setLoading(true);
      setError(null);
    }

    const deadlineId = setTimeout(() => {
      if (mountedRef.current && !controller.signal.aborted) {
        controller.abort();
        setLoading(false);
        setError('Request timed out. Please check your connection and try again.');
      }
    }, timeoutMs);

    fetcherRef.current(controller.signal)
      .then((value) => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          setData(value);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          const name = (err as { name?: unknown })?.name;
          if (name === 'AbortError' || name === 'CanceledError') return;
          setError(extractFetchError(err));
        }
      })
      .finally(() => {
        clearTimeout(deadlineId);
        if (mountedRef.current && !controller.signal.aborted) {
          setLoading(false);
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    mountedRef.current = true;
    run();
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  useEffect(() => () => { mountedRef.current = false; }, []);

  return { loading, error, data, run };
}
