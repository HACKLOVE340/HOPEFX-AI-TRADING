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
 */

import { useEffect, useRef } from 'react';
import { api } from './useApi';
import { useStore, selectIsAuth, useHasHydrated } from '../store';
import type { Plan } from '../lib/subscription';

interface BillingResponse {
  plan:   string;
  status: string;
}

const VALID_PLANS: Plan[] = ['free', 'starter', 'pro', 'elite'];

function normalisePlan(raw: string | undefined): Plan {
  const lower = (raw ?? 'free').toLowerCase() as Plan;
  return VALID_PLANS.includes(lower) ? lower : 'free';
}

export function usePlan(): void {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const setPlan  = useStore((s) => s.setPlan);
  const warned   = useRef(false);

  useEffect(() => {
    // Wait for localStorage rehydration before reading isAuth — otherwise
    // this fires with isAuth=false and skips the fetch entirely.
    if (!hydrated || !isAuth) return;

    let cancelled = false;

    api.get<BillingResponse>('/billing/subscription')
      .then((r) => {
        if (cancelled) return;
        setPlan(normalisePlan(r.data.plan));
      })
      .catch((err: unknown) => {
        if (cancelled) return;

        const status = (err as { response?: { status?: number } })?.response?.status;

        if (status === 404) {
          // Billing feature flag is disabled on the backend — silently default to free
          setPlan('free');
          return;
        }

        if (status === 401 || status === 403) {
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
  }, [hydrated, isAuth, setPlan]);
}
