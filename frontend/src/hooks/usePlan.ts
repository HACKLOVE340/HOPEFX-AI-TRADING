/**
 * usePlan.ts
 * Fetches the authenticated user's active subscription plan from the API
 * and syncs it into the Zustand store. Call once at app bootstrap.
 */

import { useEffect } from 'react';
import { api } from './useApi';
import { useStore, selectIsAuth } from '../store';
import type { Plan } from '../lib/subscription';

interface BillingResponse {
  plan: string;
  status: string;
}

export function usePlan(): void {
  const isAuth  = useStore(selectIsAuth);
  const setPlan = useStore((s) => s.setPlan);

  useEffect(() => {
    if (!isAuth) return;

    api.get<BillingResponse>('/billing/subscription')
      .then((r) => {
        const raw = (r.data.plan ?? 'free').toLowerCase() as Plan;
        const valid: Plan[] = ['free', 'starter', 'pro', 'elite'];
        setPlan(valid.includes(raw) ? raw : 'free');
      })
      .catch(() => {
        // Non-fatal — default to free if billing endpoint unreachable
        setPlan('free');
      });
  }, [isAuth, setPlan]);
}
