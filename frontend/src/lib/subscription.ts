/**
 * subscription.ts
 * Defines subscription plans, feature gates, and role-based access control.
 *
 * Role hierarchy (lowest → highest):
 *   user < trader < admin < superadmin
 *
 * Superadmin bypasses EVERY gate — plan, role, feature flag, everything.
 * Admin bypasses plan gates but not superadmin-only gates.
 */

import type { UserRole } from '../store';

export type Plan = 'free' | 'starter' | 'pro' | 'elite';

export const PLAN_RANK: Record<Plan, number> = {
  free: 0,
  starter: 1,
  pro: 2,
  elite: 3,
};

export const ROLE_RANK: Record<UserRole, number> = {
  user:       0,
  trader:     1,
  admin:      2,
  superadmin: 3,
};

/** Features gated by subscription plan */
export const PLAN_FEATURES: Record<string, Plan> = {
  // Free
  dashboard:    'free',
  watchlist:    'free',
  calendar:     'free',
  leaderboard:  'free',
  marketplace:  'free',
  affiliate:    'free',
  profile:      'free',
  settings:     'free',
  status:       'free',

  // Starter
  journal:      'starter',
  performance:  'starter',
  alerts:       'starter',
  'risk-calc':  'starter',
  wallet:       'starter',

  // Pro
  trading:        'pro',
  'ai-strategy':  'pro',
  'copy-trading': 'pro',
  'prop-firm':    'pro',
  correlation:    'pro',
  indicators:     'pro',
  'walk-forward': 'pro',
  'ab-testing':   'pro',
  tca:            'pro',
  nuclear:        'pro',
  feed:           'pro',

  // Elite
  'sub-accounts': 'elite',
  whitelabel:     'elite',
};

/** Routes that require admin or above */
export const ADMIN_ONLY_ROUTES = new Set([
  '/admin',
  '/audit',
  '/security',
  '/auto-heal',
  '/whitelabel',
]);

/** Routes that require superadmin only */
export const SUPERADMIN_ONLY_ROUTES = new Set([
  '/superadmin',
]);

/** True for superadmin role */
export function isSuperAdmin(role: UserRole): boolean {
  return role === 'superadmin';
}

/** True for admin or superadmin */
export function isAdmin(role: UserRole): boolean {
  return role === 'admin' || role === 'superadmin';
}

/** True if role meets minimum required role */
export function hasRole(role: UserRole, required: UserRole): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

/**
 * Check feature access.
 * Superadmin always passes. Admin bypasses plan gates.
 * Traders/users need the correct plan tier.
 */
export function hasFeatureAccess(
  role: UserRole,
  userPlan: Plan,
  featureKey: string,
): boolean {
  if (isSuperAdmin(role)) return true;
  if (isAdmin(role)) return true;
  const required = PLAN_FEATURES[featureKey] ?? 'free';
  return PLAN_RANK[userPlan] >= PLAN_RANK[required];
}

/** Return the minimum plan required for a feature */
export function requiredPlan(featureKey: string): Plan {
  return PLAN_FEATURES[featureKey] ?? 'free';
}

export const PLAN_LABELS: Record<Plan, string> = {
  free:    'Free',
  starter: 'Starter',
  pro:     'Pro',
  elite:   'Elite',
};

export const PLAN_COLORS: Record<Plan, string> = {
  free:    '#475569',
  starter: '#3b82f6',
  pro:     '#8b5cf6',
  elite:   '#f59e0b',
};

export const ROLE_LABELS: Record<UserRole, string> = {
  user:       'User',
  trader:     'Trader',
  admin:      'Admin',
  superadmin: 'Super Admin',
};

export const ROLE_COLORS: Record<UserRole, string> = {
  user:       '#475569',
  trader:     '#3b82f6',
  admin:      '#8b5cf6',
  superadmin: '#f59e0b',
};
