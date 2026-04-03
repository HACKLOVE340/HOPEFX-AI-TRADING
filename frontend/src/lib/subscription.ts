/**
 * subscription.ts
 * Defines subscription plans, feature gates, and role-based access control.
 * Admin/superadmin always bypass all gates.
 */

import type { UserRole } from '../store';

export type Plan = 'free' | 'starter' | 'pro' | 'elite';

export const PLAN_RANK: Record<Plan, number> = {
  free: 0,
  starter: 1,
  pro: 2,
  elite: 3,
};

/** Features gated by subscription plan */
export const PLAN_FEATURES: Record<string, Plan> = {
  // Free
  dashboard: 'free',
  watchlist: 'free',
  calendar: 'free',
  leaderboard: 'free',
  marketplace: 'free',
  affiliate: 'free',
  profile: 'free',
  settings: 'free',
  status: 'free',

  // Starter
  journal: 'starter',
  performance: 'starter',
  alerts: 'starter',
  'risk-calc': 'starter',
  wallet: 'starter',

  // Pro
  trading: 'pro',
  'ai-strategy': 'pro',
  'copy-trading': 'pro',
  'prop-firm': 'pro',
  correlation: 'pro',
  indicators: 'pro',
  'walk-forward': 'pro',
  'ab-testing': 'pro',
  tca: 'pro',
  nuclear: 'pro',
  feed: 'pro',

  // Elite
  'sub-accounts': 'elite',
  whitelabel: 'elite',
};

/** Routes that are admin-only regardless of subscription */
export const ADMIN_ONLY_ROUTES = new Set([
  '/admin',
  '/audit',
  '/security',
  '/auto-heal',
  '/whitelabel',
]);

/** Check if a user role is admin or above */
export function isAdmin(role: UserRole): boolean {
  return role === 'admin' || role === 'superadmin';
}

/** Check if a user has access to a feature given their plan */
export function hasFeatureAccess(
  role: UserRole,
  userPlan: Plan,
  featureKey: string,
): boolean {
  if (isAdmin(role)) return true;
  const required = PLAN_FEATURES[featureKey] ?? 'free';
  return PLAN_RANK[userPlan] >= PLAN_RANK[required];
}

/** Return the minimum plan required for a feature */
export function requiredPlan(featureKey: string): Plan {
  return PLAN_FEATURES[featureKey] ?? 'free';
}

export const PLAN_LABELS: Record<Plan, string> = {
  free: 'Free',
  starter: 'Starter',
  pro: 'Pro',
  elite: 'Elite',
};

export const PLAN_COLORS: Record<Plan, string> = {
  free: '#475569',
  starter: '#3b82f6',
  pro: '#8b5cf6',
  elite: '#f59e0b',
};
