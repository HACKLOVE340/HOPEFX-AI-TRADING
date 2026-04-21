/**
 * subscription.ts
 * Defines subscription plans, feature gates, and role-based access control.
 *
 * Role hierarchy (lowest → highest):
 *   user < trader < admin < superadmin
 *
 * Access rules:
 *   - superadmin  → bypasses EVERY gate: plan, role, feature flag, everything.
 *                   Has exclusive access to /superadmin and all superadmin-only
 *                   settings sections. Cannot be impersonated or demoted by admins.
 *   - admin       → bypasses plan gates but NOT superadmin-only gates.
 *                   Can access /admin, /audit, /security, /auto-heal, /whitelabel.
 *   - trader      → plan-gated features at starter/pro/enterprise/elite tiers.
 *   - user        → free tier only.
 *
 * Canonical 5-tier system (matches backend monetization/pricing.py):
 *   free | starter | professional | enterprise | elite
 *
 * The frontend uses 'pro' as a short alias for 'professional' in UI labels
 * and nav config. normalisePlan() maps API responses to the canonical set.
 */

import type { UserRole } from '../store';

/** Canonical plan IDs — must match backend SubscriptionTier values. */
export type Plan = 'free' | 'starter' | 'professional' | 'enterprise' | 'elite';

/** Short UI alias accepted in nav config and feature gates. */
export type PlanAlias = Plan | 'pro';

export const PLAN_RANK: Record<Plan, number> = {
  free:         0,
  starter:      1,
  professional: 2,
  enterprise:   3,
  elite:        4,
};

/**
 * Normalise any plan string (including legacy 'pro', 'basic') to a canonical Plan.
 * Called on every API response so the rest of the app always sees canonical values.
 */
export function normalisePlan(raw: string | undefined | null): Plan {
  const lower = (raw ?? 'free').toLowerCase();
  // Map legacy / alias values
  if (lower === 'pro') return 'professional';
  if (lower === 'basic') return 'starter';
  const valid: Plan[] = ['free', 'starter', 'professional', 'enterprise', 'elite'];
  return valid.includes(lower as Plan) ? (lower as Plan) : 'free';
}

/** Resolve a PlanAlias (including 'pro') to a canonical Plan rank. */
function aliasRank(alias: PlanAlias): number {
  return PLAN_RANK[normalisePlan(alias)];
}

export const ROLE_RANK: Record<UserRole, number> = {
  user:       0,
  trader:     1,
  admin:      2,
  superadmin: 3,
};

/** Features gated by subscription plan.
 *
 * Every featureKey used in App.tsx gated() must appear here.
 * Missing keys fall through to 'free' (safe default) but are listed
 * explicitly so the gate is intentional and auditable.
 *
 * Uses canonical Plan values (no 'pro' alias here).
 */
export const PLAN_FEATURES: Record<string, Plan> = {
  // ── Free — available to all authenticated users ───────────────────────────
  dashboard:    'free',
  trade:        'free',   // paper trading terminal (paper mode always available)
  portfolio:    'free',
  watchlist:    'free',
  calendar:     'free',
  profile:      'free',
  settings:     'free',
  leaderboard:  'free',
  marketplace:  'free',
  affiliate:    'free',
  status:       'free',

  // ── Starter ───────────────────────────────────────────────────────────────
  journal:      'starter',
  performance:  'starter',
  alerts:       'starter',
  'risk-calc':  'starter',
  wallet:       'starter',

  // ── Professional ──────────────────────────────────────────────────────────
  trading:        'professional',   // advanced AI charting terminal
  geopolitical:   'professional',   // geopolitical risk intelligence
  'ai-strategy':  'professional',
  'copy-trading': 'professional',
  'prop-firm':    'professional',
  correlation:    'professional',
  indicators:     'professional',
  'walk-forward': 'professional',
  'ab-testing':   'professional',
  tca:            'professional',
  nuclear:        'professional',
  feed:           'professional',

  // ── Enterprise ────────────────────────────────────────────────────────────
  research:       'enterprise',
  teams:          'enterprise',
  replay:         'enterprise',

  // ── Elite ─────────────────────────────────────────────────────────────────
  'sub-accounts': 'elite',
  'elite':        'elite',   // Elite Hub: dedicated support, custom dev, account manager
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

// ── Role predicates ───────────────────────────────────────────────────────────

/** True only for superadmin — the highest privilege level. */
export function isSuperAdmin(role: UserRole): boolean {
  return role === 'superadmin';
}

/** True for admin or superadmin. */
export function isAdmin(role: UserRole): boolean {
  return role === 'admin' || role === 'superadmin';
}

/** True if role meets or exceeds the required role in the hierarchy. */
export function hasRole(role: UserRole, required: UserRole): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

// ── Feature access ────────────────────────────────────────────────────────────

/**
 * Check feature access.
 *
 * - superadmin: always passes (bypasses plan AND role gates).
 * - admin:      bypasses plan gates (can access all plan-gated features).
 * - trader/user: must meet the required plan tier.
 */
export function hasFeatureAccess(
  role: UserRole,
  userPlan: Plan,
  featureKey: string,
): boolean {
  if (isSuperAdmin(role)) return true;
  if (isAdmin(role)) return true;
  const requiredAlias = (PLAN_FEATURES[featureKey] ?? 'free') as PlanAlias;
  return PLAN_RANK[userPlan] >= aliasRank(requiredAlias);
}

/**
 * Check superadmin-only feature access.
 * Only superadmin passes — admins do NOT bypass this gate.
 */
export function hasSuperAdminAccess(role: UserRole): boolean {
  return isSuperAdmin(role);
}

/** Return the minimum plan required for a feature. */
export function requiredPlan(featureKey: string): Plan {
  return PLAN_FEATURES[featureKey] ?? 'free';
}

// ── Display metadata ──────────────────────────────────────────────────────────

export const PLAN_LABELS: Record<Plan, string> = {
  free:         'Free',
  starter:      'Starter',
  professional: 'Professional',
  enterprise:   'Enterprise',
  elite:        'Elite',
};

export const PLAN_COLORS: Record<Plan, string> = {
  free:         '#475569',
  starter:      '#3b82f6',
  professional: '#8b5cf6',
  enterprise:   '#06b6d4',
  elite:        '#f59e0b',
};

/** Monthly prices in USD — matches backend monetization/pricing.py */
export const PLAN_PRICES: Record<Plan, number> = {
  free:         0,
  starter:      1800,
  professional: 4500,
  enterprise:   7500,
  elite:        10000,
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
  superadmin: '#ef4444',
};

export const ROLE_BADGE_STYLES: Record<UserRole, { bg: string; color: string; border: string }> = {
  user:       { bg: '#1e293b', color: '#94a3b8', border: '#334155' },
  trader:     { bg: '#1e3a5f', color: '#60a5fa', border: '#1d4ed8' },
  admin:      { bg: '#2e1065', color: '#c084fc', border: '#7c3aed' },
  superadmin: { bg: '#450a0a', color: '#fca5a5', border: '#dc2626' },
};
