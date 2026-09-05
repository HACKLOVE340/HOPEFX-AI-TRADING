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

import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  BarChart3,
  Bell,
  BellRing,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  Briefcase,
  Calculator,
  Calendar,
  Cpu,
  CreditCard,
  DollarSign,
  Eye,
  FlaskConical,
  Gauge,
  Globe,
  GraduationCap,
  Handshake,
  HeartPulse,
  IdCard,
  LayoutDashboard,
  LineChart,
  Link2,
  Medal,
  MessageSquare,
  Microscope,
  Newspaper,
  NotebookPen,
  PieChart,
  Puzzle,
  Radiation,
  Radio,
  Repeat,
  Rewind,
  Ruler,
  SatelliteDish,
  ScanSearch,
  ScrollText,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  ShoppingCart,
  Smartphone,
  Sparkles,
  Star,
  Tag,
  Terminal,
  TrendingUp,
  Trophy,
  User,
  Users,
  UsersRound,
  Wallet,
  Wrench,
} from 'lucide-react';

import type { Plan } from '../../lib/subscription';

export interface NavItem {
  path: string;
  label: string;
  /** Lucide icon COMPONENT, not a string.
   *  Emoji were used here previously — 129-181 per rendered page. They render
   *  differently on every OS, cannot inherit `currentColor` so they ignore
   *  theme/hover/disabled state, are announced literally by screen readers,
   *  and cannot sit on the optical grid. See audit F170. */
  icon: LucideIcon;
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
  { path: '/dashboard',    label: 'Dashboard',      icon: LayoutDashboard, group: 'core',      plan: 'free',    featureKey: 'dashboard'    },
  { path: '/trade',        label: 'Trade',          icon: TrendingUp, group: 'core',      plan: 'free',    featureKey: 'trade'        },
  { path: '/portfolio',    label: 'Portfolio',      icon: Briefcase, group: 'core',      plan: 'free',    featureKey: 'portfolio'    },
  { path: '/watchlist',    label: 'Watchlist',      icon: Eye, group: 'core',      plan: 'free',    featureKey: 'watchlist'    },
  { path: '/calendar',     label: 'Economic Calendar', icon: Calendar, group: 'core',      plan: 'free',    featureKey: 'calendar'     },
  { path: '/ai-assistant', label: 'AI Assistant',   icon: Bot, group: 'core',      plan: 'free',    featureKey: 'dashboard'    },
  { path: '/alerts',       label: 'Price Alerts',   icon: Bell, group: 'core',      plan: 'starter', featureKey: 'alerts'       },
  { path: '/status',       label: 'System Status',  icon: Activity, group: 'core',      plan: 'free',    featureKey: 'status'       },
  { path: '/docs',         label: 'Documentation',  icon: BookOpen, group: 'core',      plan: 'free',    featureKey: 'dashboard'    },

  // ── Trading ───────────────────────────────────────────────────────────────
  { path: '/ai-chart',           label: 'AI Chart Bot',      icon: Brain, group: 'trading', plan: 'professional', featureKey: 'ai-chart'          },
  { path: '/ai-chart-dashboard', label: 'AI Chart Dashboard',icon: BarChart3, group: 'trading', plan: 'professional', featureKey: 'ai-chart'          },
  { path: '/terminal',           label: 'Terminal',          icon: Terminal, group: 'trading', plan: 'starter',      featureKey: 'terminal'          },
  { path: '/nuclear',            label: 'Nuclear AI',        icon: Radiation, group: 'trading', plan: 'professional', featureKey: 'nuclear'           },

  // ── Tools ─────────────────────────────────────────────────────────────────
  { path: '/journal',          label: 'Trade Journal',   icon: NotebookPen, group: 'tools', plan: 'free',         featureKey: 'journal'          },
  { path: '/prop-firm',        label: 'Prop Firm',       icon: Shield, group: 'tools', plan: 'professional', featureKey: 'prop-firm'        },
  { path: '/copy-trading',     label: 'Copy Trading',    icon: Repeat, group: 'tools', plan: 'professional', featureKey: 'copy-trading'     },
  { path: '/risk-calculator',  label: 'Risk Calculator', icon: Calculator, group: 'tools', plan: 'starter',      featureKey: 'risk-calculator'  },
  { path: '/strategy-builder', label: 'Strategy Builder', icon: Puzzle, group: 'tools', plan: 'professional', featureKey: 'strategy-builder' },

  // ── Analytics ─────────────────────────────────────────────────────────────
  { path: '/intelligence', label: 'AI Intelligence', icon: Sparkles, group: 'analytics', plan: 'professional', featureKey: 'ai-strategy' },
  { path: '/performance',  label: 'Performance',    icon: Trophy, group: 'analytics', plan: 'free',         featureKey: 'performance'  },
  { path: '/pnl',          label: 'P&L Dashboard',  icon: DollarSign, group: 'analytics', plan: 'starter',      featureKey: 'performance'  },
  { path: '/transparency', label: 'Transparency',   icon: ScanSearch, group: 'analytics', plan: 'free'  },
  { path: '/news',         label: 'News & Sentiment', icon: Newspaper, group: 'analytics', plan: 'free'  },
  { path: '/ai-strategy',  label: 'AI Strategy',    icon: Cpu, group: 'analytics', plan: 'professional', featureKey: 'ai-strategy'  },
  { path: '/correlation',  label: 'Correlation',    icon: Link2, group: 'analytics', plan: 'professional', featureKey: 'correlation'  },
  { path: '/indicators',   label: 'Indicators',     icon: Ruler, group: 'analytics', plan: 'professional', featureKey: 'indicators'   },
  { path: '/pattern-detector', label: 'Pattern Detector', icon: Search, group: 'analytics', plan: 'professional', featureKey: 'pattern-detector' },
  { path: '/walk-forward', label: 'Walk-Forward',   icon: LineChart, group: 'analytics', plan: 'professional', featureKey: 'walk-forward' },
  { path: '/ab-testing',   label: 'A/B Testing',    icon: FlaskConical, group: 'analytics', plan: 'professional', featureKey: 'ab-testing'   },
  { path: '/tca',          label: 'TCA',            icon: PieChart, group: 'analytics', plan: 'professional', featureKey: 'tca'          },
  { path: '/geopolitical', label: 'Geopolitical Research', icon: Globe, group: 'analytics', plan: 'professional', featureKey: 'geopolitical' },
  { path: '/research',     label: 'Research',       icon: Microscope, group: 'analytics', plan: 'enterprise',   featureKey: 'research'     },
  { path: '/replay',       label: 'Market Replay',  icon: Rewind, group: 'analytics', plan: 'enterprise',   featureKey: 'replay'       },

  // ── Community ─────────────────────────────────────────────────────────────
  { path: '/leaderboard',  label: 'Leaderboard',    icon: Medal, group: 'community', plan: 'free',         featureKey: 'leaderboard'  },
  { path: '/signals',      label: 'Signal Feed',    icon: Radio, group: 'community', plan: 'professional', featureKey: 'signals'      },
  { path: '/marketplace',  label: 'Marketplace',    icon: ShoppingCart, group: 'community', plan: 'free',         featureKey: 'marketplace'  },
  { path: '/affiliate',    label: 'Affiliate',      icon: Handshake, group: 'community', plan: 'free',         featureKey: 'affiliate'    },
  { path: '/teams',        label: 'Teams',          icon: Users, group: 'community', plan: 'enterprise',   featureKey: 'teams'        },
  { path: '/chat',         label: 'Chat',           icon: MessageSquare, group: 'community', plan: 'free',         featureKey: 'chat'         },

  // ── Account ───────────────────────────────────────────────────────────────
  { path: '/profile',        label: 'Profile',          icon: User, group: 'account', plan: 'free',     featureKey: 'profile'        },
  { path: '/wallet',         label: 'Wallet',           icon: Wallet, group: 'account', plan: 'starter',  featureKey: 'wallet'         },
  { path: '/notifications',  label: 'Notifications',    icon: BellRing, group: 'account', plan: 'free',     featureKey: 'notifications'  },
  { path: '/kyc',            label: 'KYC Verification', icon: IdCard, group: 'account', plan: 'free',     featureKey: 'kyc'            },
  { path: '/academy',        label: 'Academy',          icon: GraduationCap, group: 'account', plan: 'free',     featureKey: 'academy'        },
  { path: '/mobile',         label: 'Mobile App',       icon: Smartphone, group: 'account', plan: 'free',     featureKey: 'mobile'         },
  { path: '/sub-accounts',   label: 'Sub-Accounts',     icon: UsersRound, group: 'account', plan: 'elite',    featureKey: 'sub-accounts'   },
  { path: '/elite',          label: 'Elite Hub',        icon: Star, group: 'account', plan: 'elite',    featureKey: 'elite'          },
  { path: '/upgrade',        label: 'Upgrade Plan',     icon: CreditCard, group: 'account', plan: 'free',     featureKey: 'settings'       },
  { path: '/settings',       label: 'Settings',         icon: Settings, group: 'account', plan: 'free',     featureKey: 'settings'       },

  // ── Admin (admin + superadmin) ────────────────────────────────────────────
  { path: '/admin',      label: 'Admin Panel',     icon: Wrench, group: 'admin', adminOnly: true },
  { path: '/audit',      label: 'Audit Log',       icon: ScrollText, group: 'admin', adminOnly: true },
  { path: '/security',   label: 'Security Operations', icon: ShieldCheck, group: 'admin', adminOnly: true },
  { path: '/auto-heal',  label: 'Auto-Heal',       icon: HeartPulse, group: 'admin', adminOnly: true },
  { path: '/observability', label: 'Observability', icon: SatelliteDish, group: 'admin', adminOnly: true },
  { path: '/ml-ops',        label: 'ML-Ops',        icon: Boxes, group: 'admin', adminOnly: true },
  { path: '/ai-core',       label: 'AI Core',       icon: Brain, group: 'admin', adminOnly: true },
  { path: '/whitelabel', label: 'Whitelabel',      icon: Tag, group: 'admin', adminOnly: true },

  // ── Super Admin (superadmin only) ─────────────────────────────────────────
  { path: '/master-control', label: 'Master Control', icon: Gauge, group: 'superadmin', superAdminOnly: true },
  { path: '/reliability',    label: 'Reliability',    icon: Microscope, group: 'superadmin', superAdminOnly: true },
];
