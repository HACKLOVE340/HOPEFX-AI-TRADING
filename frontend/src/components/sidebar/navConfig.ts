/**
 * navConfig.ts
 * Single source of truth for sidebar navigation.
 * Each item declares: which plan unlocks it, whether it is admin-only,
 * and which group it belongs to.
 */

export type NavGroup =
  | 'core'
  | 'trading'
  | 'analytics'
  | 'community'
  | 'account'
  | 'admin'
  | 'superadmin';

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  group: NavGroup;
  /** Minimum plan required. Admins always bypass. */
  plan?: 'free' | 'starter' | 'pro' | 'elite';
  /** If true, only admin/superadmin can see this item */
  adminOnly?: boolean;
  /** If true, only superadmin can see this item */
  superAdminOnly?: boolean;
  /** Feature key used by SubscriptionGate */
  featureKey?: string;
}

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: 'core',       label: 'Overview'    },
  { id: 'trading',    label: 'Trading'     },
  { id: 'analytics',  label: 'Analytics'   },
  { id: 'community',  label: 'Community'   },
  { id: 'account',    label: 'Account'     },
  { id: 'admin',      label: 'Admin'       },
  { id: 'superadmin', label: 'Super Admin' },
];

export const NAV_ITEMS: NavItem[] = [
  // ── Core ──────────────────────────────────────────────────────────────────
  { path: '/dashboard',    label: 'Dashboard',      icon: '📊', group: 'core',      plan: 'free',    featureKey: 'dashboard'    },
  { path: '/watchlist',    label: 'Watchlist',      icon: '👁️', group: 'core',      plan: 'free',    featureKey: 'watchlist'    },
  { path: '/calendar',     label: 'Economic Cal.',  icon: '📅', group: 'core',      plan: 'free',    featureKey: 'calendar'     },
  { path: '/alerts',       label: 'Price Alerts',   icon: '🔔', group: 'core',      plan: 'starter', featureKey: 'alerts'       },
  { path: '/status',       label: 'System Status',  icon: '🟢', group: 'core',      plan: 'free',    featureKey: 'status'       },

  // ── Trading ───────────────────────────────────────────────────────────────
  { path: '/trading',      label: 'AI Chart Bot',   icon: '🧠', group: 'trading',   plan: 'pro',     featureKey: 'trading'      },
  { path: '/nuclear',      label: 'Nuclear AI',     icon: '☢️', group: 'trading',   plan: 'pro',     featureKey: 'nuclear'      },
  { path: '/journal',      label: 'Trade Journal',  icon: '📓', group: 'trading',   plan: 'starter', featureKey: 'journal'      },
  { path: '/prop-firm',    label: 'Prop Firm',      icon: '🛡️', group: 'trading',   plan: 'pro',     featureKey: 'prop-firm'    },
  { path: '/copy-trading', label: 'Copy Trading',   icon: '🔁', group: 'trading',   plan: 'pro',     featureKey: 'copy-trading' },
  { path: '/risk-calc',    label: 'Risk Calculator',icon: '🧮', group: 'trading',   plan: 'starter', featureKey: 'risk-calc'    },

  // ── Analytics ─────────────────────────────────────────────────────────────
  { path: '/performance',  label: 'Performance',    icon: '🏆', group: 'analytics', plan: 'starter', featureKey: 'performance'  },
  { path: '/ai-strategy',  label: 'AI Strategy',    icon: '🤖', group: 'analytics', plan: 'pro',     featureKey: 'ai-strategy'  },
  { path: '/correlation',  label: 'Correlation',    icon: '🔗', group: 'analytics', plan: 'pro',     featureKey: 'correlation'  },
  { path: '/indicators',   label: 'Indicators',     icon: '📐', group: 'analytics', plan: 'pro',     featureKey: 'indicators'   },
  { path: '/walk-forward', label: 'Walk-Forward',   icon: '📈', group: 'analytics', plan: 'pro',     featureKey: 'walk-forward' },
  { path: '/ab-testing',   label: 'A/B Testing',    icon: '⚗️', group: 'analytics', plan: 'pro',     featureKey: 'ab-testing'   },
  { path: '/tca',          label: 'TCA',            icon: '📊', group: 'analytics', plan: 'pro',     featureKey: 'tca'          },

  // ── Community ─────────────────────────────────────────────────────────────
  { path: '/leaderboard',  label: 'Leaderboard',    icon: '🥇', group: 'community', plan: 'free',    featureKey: 'leaderboard'  },
  { path: '/feed',         label: 'Signal Feed',    icon: '📡', group: 'community', plan: 'pro',     featureKey: 'feed'         },
  { path: '/marketplace',  label: 'Marketplace',    icon: '🛒', group: 'community', plan: 'free',    featureKey: 'marketplace'  },
  { path: '/affiliate',    label: 'Affiliate',      icon: '🤝', group: 'community', plan: 'free',    featureKey: 'affiliate'    },

  // ── Account ───────────────────────────────────────────────────────────────
  { path: '/profile',      label: 'Profile',        icon: '👤', group: 'account',   plan: 'free',    featureKey: 'profile'      },
  { path: '/wallet',       label: 'Wallet',         icon: '💰', group: 'account',   plan: 'starter', featureKey: 'wallet'       },
  { path: '/sub-accounts', label: 'Sub-Accounts',   icon: '👥', group: 'account',   plan: 'elite',   featureKey: 'sub-accounts' },
  { path: '/checkout',     label: 'Upgrade Plan',   icon: '💳', group: 'account',   plan: 'free',    featureKey: 'settings'     },
  { path: '/settings',     label: 'Settings',       icon: '⚙️', group: 'account',   plan: 'free',    featureKey: 'settings'     },

  // ── Admin (admin/superadmin only) ─────────────────────────────────────────
  { path: '/superadmin',   label: 'Admin Panel',    icon: '🔧', group: 'admin',      adminOnly: true },
  { path: '/audit',        label: 'Audit Log',      icon: '🔍', group: 'admin',      adminOnly: true },
  { path: '/security',     label: 'Security Ops',   icon: '🛡️', group: 'admin',      adminOnly: true },
  { path: '/auto-heal',    label: 'Auto-Heal',      icon: '🩺', group: 'admin',      adminOnly: true },

  // ── Super Admin (superadmin only) ─────────────────────────────────────────
  { path: '/superadmin',   label: 'Master Control', icon: '⚡', group: 'superadmin', superAdminOnly: true },
];
