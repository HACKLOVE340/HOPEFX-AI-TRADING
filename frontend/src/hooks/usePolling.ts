/**
 * usePolling — runs a callback on a fixed interval while the tab is visible.
 *
 * Pauses automatically when the document is hidden (tab switch, minimise) to
 * avoid unnecessary API calls, and resumes immediately when the tab becomes
 * visible again.
 *
 * Usage:
 *   usePolling(load, 15_000);   // call load() every 15 s while tab is active
 *
 * The callback ref is stable — changing `cb` between renders does NOT reset
 * the timer, so callers can pass an inline function without wrapping in
 * useCallback (though useCallback is still recommended for clarity).
 */

import { useEffect, useRef } from 'react';

export function usePolling(cb: () => void, intervalMs: number): void {
  const cbRef = useRef(cb);

  // Keep the ref current without resetting the interval
  useEffect(() => {
    cbRef.current = cb;
  }, [cb]);

  useEffect(() => {
    if (intervalMs <= 0) return;

    let timerId: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timerId !== null) return;
      timerId = setInterval(() => {
        if (!document.hidden) cbRef.current();
      }, intervalMs);
    };

    const stop = () => {
      if (timerId !== null) {
        clearInterval(timerId);
        timerId = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
      } else {
        // Immediately refresh when tab becomes visible again, then restart timer
        cbRef.current();
        start();
      }
    };

    start();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [intervalMs]);
}
