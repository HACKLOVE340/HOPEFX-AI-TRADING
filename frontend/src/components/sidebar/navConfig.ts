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
  Headphones,
  LifeBuoy,
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
  UserCircle,
  ServerCog,
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
  /**
   * The hub page that owns this item.
   *
   * The sidebar listed 61 destinations in one flat column — 15 under
   * Analytics alone, and 11 under Account of which Profile, Notifications,
   * Billing and Privacy already existed as sections inside Settings. A list
   * that long is not navigation, it is an index, and it hid the eight or nine
   * things anyone opens daily among fifty they open twice a year.
   *
   * An item with a `hub` is NOT removed and NOT unreachable: its route is
   * untouched, and it renders on that hub's page as a described, clickable
   * card instead of as one more line in the column.
   * `nav_hub_reachability.test.ts` fails if any item becomes reachable from
   * neither place.
   */
  hub?: HubId;
}

/** The five pages that hold what the sidebar used to list. */
export type HubId = 'ai' | 'analytics' | 'community' | 'account' | 'operations';

export interface HubMeta {
  id: HubId;
  path: string;
  label: string;
  /** One line, from the reader's side: what is behind this, and why go there. */
  description: string;
  icon: LucideIcon;
  group: NavGroup;
  plan?: Plan;
  adminOnly?: boolean;
}

export const HUBS: HubMeta[] = [
  {
    id: 'ai', path: '/ai', label: 'AI',
    description: 'Every model-facing surface: the assistant, the chart bot, strategy generation, pattern detection and the control plane.',
    icon: Brain, group: 'trading', plan: 'free',
  },
  {
    id: 'analytics', path: '/analytics', label: 'Analytics',
    description: 'What happened and what is about to: performance, P&L, execution quality, correlation, calendar and research.',
    icon: BarChart3, group: 'analytics', plan: 'free',
  },
  {
    id: 'community', path: '/community', label: 'Community',
    description: 'Other traders — leaderboard, marketplace, copy trading, teams and chat.',
    icon: Users, group: 'community', plan: 'free',
  },
  {
    id: 'account', path: '/account', label: 'Account',
    description: 'You, your money and your plan: profile, wallet, verification, billing, and how to learn the product.',
    icon: UserCircle, group: 'account', plan: 'free',
  },
  {
    id: 'operations', path: '/operations', label: 'Operations',
    description: 'Running the platform rather than trading on it: admin, audit, security, observability and ML-Ops.',
    icon: ServerCog, group: 'admin', adminOnly: true,
  },
];

/** Items the sidebar shows directly — the daily ones. */
export function topLevelItems(): NavItem[] {
  return NAV_ITEMS.filter((i) => !i.hub);
}

/** Items a hub page shows. Order follows NAV_ITEMS, which is plan order. */
export function itemsInHub(id: HubId): NavItem[] {
  return NAV_ITEMS.filter((i) => i.hub === id);
}

export function hubByPath(path: string): HubMeta | undefined {
  return HUBS.find((h) => h.path === path);
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
  { path: '/calendar',     label: 'Economic Calendar', icon: Calendar, group: 'core',      plan: 'free',    featureKey: 'calendar', hub: 'analytics' },
  { path: '/ai-assistant', label: 'AI Assistant',   icon: Bot, group: 'core',      plan: 'free',    featureKey: 'dashboard', hub: 'ai' },
  { path: '/alerts',       label: 'Price Alerts',   icon: Bell, group: 'core',      plan: 'starter', featureKey: 'alerts'       },
  { path: '/status',       label: 'System Status',  icon: Activity, group: 'core',      plan: 'free',    featureKey: 'status', hub: 'operations' },
  { path: '/docs',         label: 'Documentation',  icon: BookOpen, group: 'core',      plan: 'free',    featureKey: 'dashboard', hub: 'account' },

  // ── Trading ───────────────────────────────────────────────────────────────
  { path: '/ai-chart',           label: 'AI Chart Bot',      icon: Brain, group: 'trading', plan: 'professional', featureKey: 'ai-chart', hub: 'ai' },
  { path: '/ai-chart-dashboard', label: 'AI Chart Dashboard',icon: BarChart3, group: 'trading', plan: 'professional', featureKey: 'ai-chart', hub: 'ai' },
  { path: '/terminal',           label: 'Terminal',          icon: Terminal, group: 'trading', plan: 'starter',      featureKey: 'terminal'          },
  { path: '/nuclear',            label: 'Nuclear AI',        icon: Radiation, group: 'trading', plan: 'professional', featureKey: 'nuclear', hub: 'ai' },

  // ── Tools ─────────────────────────────────────────────────────────────────
  { path: '/journal',          label: 'Trade Journal',   icon: NotebookPen, group: 'tools', plan: 'free',         featureKey: 'journal'          },
  { path: '/prop-firm',        label: 'Prop Firm',       icon: Shield, group: 'tools', plan: 'professional', featureKey: 'prop-firm', hub: 'analytics' },
  { path: '/copy-trading',     label: 'Copy Trading',    icon: Repeat, group: 'tools', plan: 'professional', featureKey: 'copy-trading', hub: 'community' },
  { path: '/risk-calculator',  label: 'Risk Calculator', icon: Calculator, group: 'tools', plan: 'starter',      featureKey: 'risk-calculator', hub: 'analytics' },
  { path: '/strategy-builder', label: 'Strategy Builder', icon: Puzzle, group: 'tools', plan: 'professional', featureKey: 'strategy-builder', hub: 'ai' },

  // ── Analytics ─────────────────────────────────────────────────────────────
  { path: '/intelligence', label: 'AI Intelligence', icon: Sparkles, group: 'analytics', plan: 'professional', featureKey: 'ai-strategy', hub: 'ai' },
  { path: '/performance',  label: 'Performance',    icon: Trophy, group: 'analytics', plan: 'free',         featureKey: 'performance', hub: 'analytics' },
  { path: '/pnl',          label: 'P&L Dashboard',  icon: DollarSign, group: 'analytics', plan: 'starter',      featureKey: 'performance', hub: 'analytics' },
  { path: '/transparency', label: 'Transparency',   icon: ScanSearch, group: 'analytics', plan: 'free', hub: 'analytics' },
  { path: '/news',         label: 'News & Sentiment', icon: Newspaper, group: 'analytics', plan: 'free', hub: 'analytics' },
  { path: '/ai-strategy',  label: 'AI Strategy',    icon: Cpu, group: 'analytics', plan: 'professional', featureKey: 'ai-strategy', hub: 'ai' },
  { path: '/correlation',  label: 'Correlation',    icon: Link2, group: 'analytics', plan: 'professional', featureKey: 'correlation', hub: 'analytics' },
  { path: '/indicators',   label: 'Indicators',     icon: Ruler, group: 'analytics', plan: 'professional', featureKey: 'indicators', hub: 'analytics' },
  { path: '/pattern-detector', label: 'Pattern Detector', icon: Search, group: 'analytics', plan: 'professional', featureKey: 'pattern-detector', hub: 'ai' },
  { path: '/walk-forward', label: 'Walk-Forward',   icon: LineChart, group: 'analytics', plan: 'professional', featureKey: 'walk-forward', hub: 'analytics' },
  { path: '/ab-testing',   label: 'A/B Testing',    icon: FlaskConical, group: 'analytics', plan: 'professional', featureKey: 'ab-testing', hub: 'analytics' },
  { path: '/tca',          label: 'TCA',            icon: PieChart, group: 'analytics', plan: 'professional', featureKey: 'tca', hub: 'analytics' },
  { path: '/geopolitical', label: 'Geopolitical Research', icon: Globe, group: 'analytics', plan: 'professional', featureKey: 'geopolitical', hub: 'analytics' },
  { path: '/research',     label: 'Research',       icon: Microscope, group: 'analytics', plan: 'enterprise',   featureKey: 'research', hub: 'analytics' },
  { path: '/replay',       label: 'Market Replay',  icon: Rewind, group: 'analytics', plan: 'enterprise',   featureKey: 'replay', hub: 'analytics' },

  // ── Community ─────────────────────────────────────────────────────────────
  { path: '/leaderboard',  label: 'Leaderboard',    icon: Medal, group: 'community', plan: 'free',         featureKey: 'leaderboard', hub: 'community' },
  { path: '/signals',      label: 'Signal Feed',    icon: Radio, group: 'community', plan: 'professional', featureKey: 'signals'      },
  { path: '/marketplace',  label: 'Marketplace',    icon: ShoppingCart, group: 'community', plan: 'free',         featureKey: 'marketplace', hub: 'community' },
  { path: '/affiliate',    label: 'Affiliate',      icon: Handshake, group: 'community', plan: 'free',         featureKey: 'affiliate', hub: 'community' },
  { path: '/teams',        label: 'Teams',          icon: Users, group: 'community', plan: 'enterprise',   featureKey: 'teams', hub: 'community' },
  { path: '/chat',         label: 'Chat',           icon: MessageSquare, group: 'community', plan: 'free',         featureKey: 'chat', hub: 'community' },

  // ── Account ───────────────────────────────────────────────────────────────
  { path: '/profile',        label: 'Profile',          icon: User, group: 'account', plan: 'free',     featureKey: 'profile', hub: 'account' },
  { path: '/wallet',         label: 'Wallet',           icon: Wallet, group: 'account', plan: 'starter',  featureKey: 'wallet', hub: 'account' },
  { path: '/notifications',  label: 'Notifications',    icon: BellRing, group: 'account', plan: 'free',     featureKey: 'notifications', hub: 'account' },
  { path: '/support',        label: 'Support',          icon: LifeBuoy, group: 'account', plan: 'free', hub: 'account' },
  { path: '/kyc',            label: 'KYC Verification', icon: IdCard, group: 'account', plan: 'free',     featureKey: 'kyc', hub: 'account' },
  { path: '/academy',        label: 'Academy',          icon: GraduationCap, group: 'account', plan: 'free',     featureKey: 'academy', hub: 'account' },
  { path: '/mobile',         label: 'Mobile App',       icon: Smartphone, group: 'account', plan: 'free',     featureKey: 'mobile', hub: 'account' },
  { path: '/sub-accounts',   label: 'Sub-Accounts',     icon: UsersRound, group: 'account', plan: 'elite',    featureKey: 'sub-accounts', hub: 'account' },
  { path: '/elite',          label: 'Elite Hub',        icon: Star, group: 'account', plan: 'elite',    featureKey: 'elite', hub: 'account' },
  { path: '/upgrade',        label: 'Upgrade Plan',     icon: CreditCard, group: 'account', plan: 'free',     featureKey: 'settings', hub: 'account' },
  { path: '/settings',       label: 'Settings',         icon: Settings, group: 'account', plan: 'free',     featureKey: 'settings'       },

  // ── Admin (admin + superadmin) ────────────────────────────────────────────
  { path: '/admin',      label: 'Admin Panel',     icon: Wrench, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/audit',      label: 'Audit Log',       icon: ScrollText, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/security',   label: 'Security Operations', icon: ShieldCheck, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/auto-heal',  label: 'Auto-Heal',       icon: HeartPulse, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/observability', label: 'Observability', icon: SatelliteDish, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/ml-ops',        label: 'ML-Ops',        icon: Boxes, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/ai-core',       label: 'AI Core',       icon: Brain, group: 'admin', adminOnly: true, hub: 'ai' },
  { path: '/support-console', label: 'Support Console', icon: Headphones, group: 'admin', adminOnly: true, hub: 'operations' },
  { path: '/whitelabel', label: 'Whitelabel',      icon: Tag, group: 'admin', adminOnly: true, hub: 'operations' },

  // ── Super Admin (superadmin only) ─────────────────────────────────────────
  { path: '/master-control', label: 'Master Control', icon: Gauge, group: 'superadmin', superAdminOnly: true, hub: 'operations' },
  { path: '/reliability',    label: 'Reliability',    icon: Microscope, group: 'superadmin', superAdminOnly: true, hub: 'operations' },
];
