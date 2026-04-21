/**
 * usePlan.ts
 * Fetches the authenticated user's active subscription plan from the API
 * and syncs it into the Zustand store. Call once at app bootstrap (App.tsx).
 *
 * Handles three cases gracefully:
 *   1. Billing feature flag disabled (404) → default to 'free', no error log
 *   2. Network / server error             → default to 'free', warn once
 *   3. Success                            → set plan from response
 *
 * Admins and superadmins bypass plan gates in SubscriptionGate regardless
 * of what this hook returns.
 *
 * Re-fetches whenever the token changes (covers login, token refresh, and
 * account switches) so the plan is always in sync with the active session.
 */

import { useEffect, useRef } from 'react';
import { api } from './useApi';
import { useStore, selectIsAuth, useHasHydrated } from '../store';
import { normalisePlan } from '../lib/subscription';

interface BillingResponse {
  plan:   string;
  tier?:  string;
  status: string;
}

export function usePlan(): void {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  // Subscribe to the token itself so the effect re-runs on every login/refresh,
  // not just on the initial hydration. isAuth alone doesn't change when the
  // user logs out and back in within the same session (it stays true).
  const token    = useStore((s) => s.token);
  const setPlan  = useStore((s) => s.setPlan);
  const warned   = useRef(false);

  useEffect(() => {
    // Wait for localStorage rehydration before reading isAuth — otherwise
    // this fires with isAuth=false and skips the fetch entirely.
    if (!hydrated || !isAuth || !token) return;

    let cancelled = false;

    api.get<BillingResponse>('/billing/subscription')
      .then((r) => {
        if (cancelled) return;
        // Accept either 'plan' or 'tier' key from the API response
        setPlan(normalisePlan(r.data.plan ?? r.data.tier));
      })
      .catch((err: unknown) => {
        if (cancelled) return;

        const httpStatus = (err as { response?: { status?: number } })?.response?.status;

        if (httpStatus === 404) {
          // Billing feature flag is disabled on the backend — silently default to free
          setPlan('free');
          return;
        }

        if (httpStatus === 401 || httpStatus === 403) {
          // Auth error is handled by the axios interceptor — nothing to do here
          return;
        }

        // Any other error: default to free and warn once per session
        if (!warned.current) {
          warned.current = true;
          console.warn('[usePlan] Could not fetch subscription plan — defaulting to free.', err);
        }
        setPlan('free');
      });

    return () => { cancelled = true; };
  // token in deps: re-fetch on every login/refresh so plan stays in sync
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, isAuth, token, setPlan]);
}
