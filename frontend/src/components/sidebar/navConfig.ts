/**
 * navConfig.ts
 * Single source of truth for sidebar navigation.
 * Each item declares: which plan unlocks it, whether it is admin-only,
 * and which group it belongs to.
 */

export type NavGroup =
  | 'core'
  | 'trading'
  | 'tools'
  | 'analytics'
  | 'community'
  | 'account'
  | 'admin'
  | 'superadmin';

import type { Plan } from '../../lib/subscription';

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  group: NavGroup;
  /** Minimum plan required. Admins always bypass. */
  plan?: Plan;
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
  { id: 'tools',      label: 'Tools'       },
  { id: 'analytics',  label: 'Analytics'   },
  { id: 'community',  label: 'Community'   },
  { id: 'account',    label: 'Account'     },
  { id: 'admin',      label: 'Admin'       },
  { id: 'superadmin', label: 'Super Admin' },
];

export const NAV_ITEMS: NavItem[] = [
  // ── Core ──────────────────────────────────────────────────────────────────
  { path: '/dashboard',    label: 'Dashboard',      icon: '📊', group: 'core',      plan: 'free',    featureKey: 'dashboard'    },
  { path: '/trade',        label: 'Trade',          icon: '⚡', group: 'core',      plan: 'free',    featureKey: 'trade'        },
  { path: '/portfolio',    label: 'Portfolio',      icon: '💼', group: 'core',      plan: 'free',    featureKey: 'portfolio'    },
  { path: '/watchlist',    label: 'Watchlist',      icon: '👁️', group: 'core',      plan: 'free',    featureKey: 'watchlist'    },
  { path: '/calendar',     label: 'Economic Calendar', icon: '📅', group: 'core',      plan: 'free',    featureKey: 'calendar'     },
  { path: '/alerts',       label: 'Price Alerts',   icon: '🔔', group: 'core',      plan: 'starter', featureKey: 'alerts'       },
  { path: '/system-status', label: 'System Status', icon: '🟢', group: 'core',      plan: 'free',    featureKey: 'status'       },

  // ── Trading ───────────────────────────────────────────────────────────────
  { path: '/ai-chart',   label: 'AI Chart Bot',   icon: '🧠', group: 'trading', plan: 'professional', featureKey: 'ai-chart'  },
  { path: '/terminal',   label: 'Terminal',       icon: '🖥️', group: 'trading', plan: 'starter',      featureKey: 'terminal'  },
  { path: '/nuclear',    label: 'Nuclear AI',     icon: '☢️', group: 'trading', plan: 'professional', featureKey: 'nuclear'   },

  // ── Tools ─────────────────────────────────────────────────────────────────
  { path: '/journal',          label: 'Trade Journal',   icon: '📓', group: 'tools', plan: 'free',         featureKey: 'journal'          },
  { path: '/prop-firm',        label: 'Prop Firm',       icon: '🛡️', group: 'tools', plan: 'professional', featureKey: 'prop-firm'        },
  { path: '/copy-trading',     label: 'Copy Trading',    icon: '🔁', group: 'tools', plan: 'professional', featureKey: 'copy-trading'     },
  { path: '/risk-calculator',  label: 'Risk Calculator', icon: '🧮', group: 'tools', plan: 'starter',      featureKey: 'risk-calculator'  },

  // ── Analytics ─────────────────────────────────────────────────────────────
  { path: '/performance',  label: 'Performance',    icon: '🏆', group: 'analytics', plan: 'free',         featureKey: 'performance'  },
  { path: '/pnl',          label: 'P&L Dashboard',  icon: '💹', group: 'analytics', plan: 'starter',      featureKey: 'performance'  },
  { path: '/ai-strategy',  label: 'AI Strategy',    icon: '🤖', group: 'analytics', plan: 'professional', featureKey: 'ai-strategy'  },
  { path: '/correlation',  label: 'Correlation',    icon: '🔗', group: 'analytics', plan: 'professional', featureKey: 'correlation'  },
  { path: '/indicators',   label: 'Indicators',     icon: '📐', group: 'analytics', plan: 'professional', featureKey: 'indicators'   },
  { path: '/walk-forward', label: 'Walk-Forward',   icon: '📈', group: 'analytics', plan: 'professional', featureKey: 'walk-forward' },
  { path: '/ab-testing',   label: 'A/B Testing',    icon: '⚗️', group: 'analytics', plan: 'professional', featureKey: 'ab-testing'   },
  { path: '/tca',          label: 'TCA',            icon: '📊', group: 'analytics', plan: 'professional', featureKey: 'tca'          },
  { path: '/geopolitical', label: 'Geopolitical Research', icon: '🌍', group: 'analytics', plan: 'professional', featureKey: 'geopolitical' },
  { path: '/research',     label: 'Research',       icon: '🔬', group: 'analytics', plan: 'enterprise',   featureKey: 'research'     },
  { path: '/replay',       label: 'Market Replay',  icon: '⏪', group: 'analytics', plan: 'enterprise',   featureKey: 'replay'       },

  // ── Community ─────────────────────────────────────────────────────────────
  { path: '/leaderboard',  label: 'Leaderboard',    icon: '🥇', group: 'community', plan: 'free',         featureKey: 'leaderboard'  },
  { path: '/signals',      label: 'Signal Feed',    icon: '📡', group: 'community', plan: 'professional', featureKey: 'signals'      },
  { path: '/marketplace',  label: 'Marketplace',    icon: '🛒', group: 'community', plan: 'free',         featureKey: 'marketplace'  },
  { path: '/affiliate',    label: 'Affiliate',      icon: '🤝', group: 'community', plan: 'free',         featureKey: 'affiliate'    },
  { path: '/teams',        label: 'Teams',          icon: '👥', group: 'community', plan: 'enterprise',   featureKey: 'teams'        },
  { path: '/chat',         label: 'Chat',           icon: '💬', group: 'community', plan: 'free',         featureKey: 'chat'         },

  // ── Account ───────────────────────────────────────────────────────────────
  { path: '/profile',        label: 'Profile',          icon: '👤', group: 'account', plan: 'free',     featureKey: 'profile'        },
  { path: '/wallet',         label: 'Wallet',           icon: '💰', group: 'account', plan: 'starter',  featureKey: 'wallet'         },
  { path: '/notifications',  label: 'Notifications',    icon: '🔔', group: 'account', plan: 'free',     featureKey: 'notifications'  },
  { path: '/kyc',            label: 'KYC Verification', icon: '🪪', group: 'account', plan: 'free',     featureKey: 'kyc'            },
  { path: '/mobile',         label: 'Mobile App',       icon: '📱', group: 'account', plan: 'free',     featureKey: 'mobile'         },
  { path: '/sub-accounts',   label: 'Sub-Accounts',     icon: '👥', group: 'account', plan: 'elite',    featureKey: 'sub-accounts'   },
  { path: '/elite',          label: 'Elite Hub',        icon: '⭐', group: 'account', plan: 'elite',    featureKey: 'elite'          },
  { path: '/upgrade',        label: 'Upgrade Plan',     icon: '💳', group: 'account', plan: 'free',     featureKey: 'settings'       },
  { path: '/settings',       label: 'Settings',         icon: '⚙️', group: 'account', plan: 'free',     featureKey: 'settings'       },

  // ── Admin (admin + superadmin) ────────────────────────────────────────────
  { path: '/admin',      label: 'Admin Panel',     icon: '🔧', group: 'admin', adminOnly: true },
  { path: '/audit',      label: 'Audit Log',       icon: '🔍', group: 'admin', adminOnly: true },
  { path: '/security',   label: 'Security Operations', icon: '🛡️', group: 'admin', adminOnly: true },
  { path: '/auto-heal',  label: 'Auto-Heal',       icon: '🩺', group: 'admin', adminOnly: true },
  { path: '/whitelabel', label: 'Whitelabel',      icon: '🏷️', group: 'admin', adminOnly: true },

  // ── Super Admin (superadmin only) ─────────────────────────────────────────
  { path: '/master-control', label: 'Master Control', icon: '⚡', group: 'superadmin', superAdminOnly: true },
  { path: '/reliability',    label: 'Reliability',    icon: '🔬', group: 'superadmin', superAdminOnly: true },
];
