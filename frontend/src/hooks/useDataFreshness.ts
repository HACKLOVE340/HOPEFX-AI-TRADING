/**
 * hooks/useDataFreshness.ts
 *
 * One place for a page to record "my last load failed" (audit F1-01).
 *
 * The F1 runtime failure matrix found three pages that issued real requests,
 * had every request fail, and rendered byte-identically to the healthy case in
 * all five failure states. Each had the same shape — a `catch` that swallowed
 * the failure and silently substituted a fallback:
 *
 *     catch { /* API unavailable — show empty list * / }
 *     catch { /* keep existing prices * / }
 *     catch { /* fall back to store prices * / }
 *
 * Degrading is fine. Degrading *invisibly* is not, because the page then states
 * things it cannot know — that prices are live, that a computed position size
 * reflects the current market.
 */

import { useCallback, useMemo, useState } from 'react';

export interface DataFreshness {
  /** True when the most recent load attempt failed. */
  failed: boolean;
  /** What failed, in words a user recognises ("prices", "watchlist"). */
  what: string;
  /** Convenience inverse — never claim "live" while a load is failing. */
  isLive: boolean;
  markFailed: (what?: string) => void;
  markOk: () => void;
}

export function useDataFreshness(initialWhat = 'data'): DataFreshness {
  const [failed, setFailed] = useState(false);
  const [what, setWhat] = useState(initialWhat);

  const markFailed = useCallback((w?: string) => {
    if (w) setWhat(w);
    setFailed(true);
  }, []);

  const markOk = useCallback(() => setFailed(false), []);

  // Memoised: callers put this object in dependency arrays. Returning a fresh
  // object each render made `fetchAll` a new function every render, which
  // re-ran its effect, which fetched again — an unbounded request loop (138
  // requests in one render pass, caught by the F1 harness's request counter).
  return useMemo(
    () => ({ failed, what, isLive: !failed, markFailed, markOk }),
    [failed, what, markFailed, markOk],
  );
}
