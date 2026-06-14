import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  Users,
  Trophy,
  Wallet,
  Settings,
  Menu,
  X,
  Bell,
  Shield,
  Sun,
  Moon,
  BarChart2,
  WifiOff,
  Crown,
  Globe,
  BookOpen,
  Target,
  Bell as BellIcon,
  Calendar,
  Star,
  Activity,
  Brain,
  FlaskConical,
  GitBranch,
  Layers,
  LineChart,
  Newspaper,
  User,
  MessageCircle,
  CreditCard,
  Eye,
  Blocks,
  Radio,
  Gauge,
} from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import { useWebSocket } from '../hooks/useWebSocket'
import { ConnectionStatus } from './ConnectionStatus'
import { useStore } from '../store/useStore'
import type { UserRole } from '../store/useStore'

// Nav items visible to all authenticated users
const BASE_NAV = [
  // ── Core trading ──────────────────────────────────────────────────────────
  { path: '/dashboard',    icon: LayoutDashboard, label: 'Dashboard',       minRole: 'user'       as UserRole, group: 'main' },
  { path: '/trading',      icon: TrendingUp,      label: 'Trading',         minRole: 'trader'     as UserRole, group: 'main' },
  { path: '/positions',    icon: Layers,          label: 'Positions',       minRole: 'trader'     as UserRole, group: 'main' },
  { path: '/pnl',          icon: LineChart,       label: 'Live P&L',        minRole: 'trader'     as UserRole, group: 'main' },
  { path: '/performance',  icon: BarChart2,       label: 'Performance',     minRole: 'trader'     as UserRole, group: 'main' },
  // ── Analysis ──────────────────────────────────────────────────────────────
  { path: '/watchlist',    icon: Star,            label: 'Watchlist',       minRole: 'user'       as UserRole, group: 'analysis' },
  { path: '/alerts',       icon: BellIcon,        label: 'Alerts',          minRole: 'user'       as UserRole, group: 'analysis' },
  { path: '/calendar',     icon: Calendar,        label: 'Economic Cal.',   minRole: 'user'       as UserRole, group: 'analysis' },
  { path: '/ai-strategy',  icon: Brain,           label: 'AI Strategy',     minRole: 'trader'     as UserRole, group: 'analysis' },
  { path: '/risk-calc',    icon: Target,          label: 'Risk Calculator', minRole: 'trader'     as UserRole, group: 'analysis' },
  { path: '/correlation',  icon: Activity,        label: 'Correlation',     minRole: 'trader'     as UserRole, group: 'analysis' },
  { path: '/indicators',   icon: FlaskConical,    label: 'Indicators',      minRole: 'trader'     as UserRole, group: 'analysis' },
  { path: '/walk-forward', icon: GitBranch,       label: 'Walk Forward',    minRole: 'trader'     as UserRole, group: 'analysis' },
  { path: '/strategy-builder', icon: Blocks,      label: 'Strategy Builder', minRole: 'trader'    as UserRole, group: 'analysis' },
  { path: '/news',         icon: Radio,           label: 'News & Sentiment', minRole: 'user'      as UserRole, group: 'analysis' },
  { path: '/transparency', icon: Eye,             label: 'Trade Explain',    minRole: 'trader'    as UserRole, group: 'analysis' },
  // ── Social / community ────────────────────────────────────────────────────
  { path: '/copy-trading', icon: Users,           label: 'Copy Trading',    minRole: 'trader'     as UserRole, group: 'social' },
  { path: '/leaderboard',  icon: Trophy,          label: 'Leaderboard',     minRole: 'user'       as UserRole, group: 'social' },
  { path: '/feed',         icon: Newspaper,       label: 'Social Feed',     minRole: 'user'       as UserRole, group: 'social' },
  { path: '/chat',         icon: MessageCircle,   label: 'Community Chat',  minRole: 'user'       as UserRole, group: 'social' },
  // ── Account ───────────────────────────────────────────────────────────────
  { path: '/journal',      icon: BookOpen,        label: 'Trade Journal',   minRole: 'user'       as UserRole, group: 'account' },
  { path: '/prop-firm',    icon: Shield,          label: 'Prop Firm',       minRole: 'trader'     as UserRole, group: 'account' },
  { path: '/wallet',       icon: Wallet,          label: 'Wallet',          minRole: 'user'       as UserRole, group: 'account' },
  { path: '/billing',      icon: CreditCard,      label: 'Billing',         minRole: 'user'       as UserRole, group: 'account' },
  { path: '/notifications',icon: Bell,            label: 'Notifications',   minRole: 'user'       as UserRole, group: 'account' },
  { path: '/profile',      icon: User,            label: 'Profile',         minRole: 'user'       as UserRole, group: 'account' },
  { path: '/settings',     icon: Settings,        label: 'Settings',        minRole: 'user'       as UserRole, group: 'account' },
  // ── Admin ─────────────────────────────────────────────────────────────────
  { path: '/admin',        icon: Shield,          label: 'Admin Panel',     minRole: 'admin'      as UserRole, group: 'admin' },
  { path: '/superadmin',   icon: Crown,           label: 'SuperAdmin',      minRole: 'superadmin' as UserRole, group: 'admin' },
  { path: '/superadmin/ml',icon: Brain,           label: 'ML Operations',   minRole: 'superadmin' as UserRole, group: 'admin' },
  { path: '/superadmin/observability', icon: Gauge, label: 'Observability', minRole: 'superadmin' as UserRole, group: 'admin' },
  { path: '/whitelabel',   icon: Globe,           label: 'Whitelabel',      minRole: 'superadmin' as UserRole, group: 'admin' },
]

const GROUP_LABELS: Record<string, string> = {
  main:     'Trading',
  analysis: 'Analysis',
  social:   'Community',
  account:  'Account',
  admin:    'Admin',
}

const ROLE_RANK: Record<UserRole, number> = {
  user: 0, trader: 1, admin: 2, superadmin: 3,
}

export function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const { connected, latency, noLiveFeed, noLiveFeedMessage } = useWebSocket()
  const { isDark, toggle: toggleTheme } = useTheme()
  const user = useStore((s) => s.user)
  const userRank = ROLE_RANK[user?.role ?? 'user'] ?? 0

  const navItems = BASE_NAV.filter(
    (item) => userRank >= ROLE_RANK[item.minRole]
  )

  return (
    <div className="min-h-screen bg-slate-950 dark:bg-slate-950 text-slate-100 dark:text-slate-100">
      {/* Mobile header */}
      <div className="lg:hidden flex items-center justify-between p-4 border-b border-slate-800">
        <button onClick={() => setSidebarOpen(!sidebarOpen)}>
          {sidebarOpen ? <X /> : <Menu />}
        </button>
        <span className="font-bold text-xl">HOPEFX</span>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          </button>
          <Bell className="w-6 h-6" />
        </div>
      </div>

      <div className="flex">
        {/* Sidebar */}
        <aside className={`
          fixed lg:static inset-y-0 left-0 z-50 w-64 bg-slate-900 border-r border-slate-800
          transform transition-transform duration-200 ease-in-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}>
          <div className="p-6">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-amber-400 to-amber-600 bg-clip-text text-transparent">
              HOPEFX
            </h1>
            <p className="text-xs text-slate-500 mt-1">GodMode v9.5</p>
          </div>

          <nav className="px-3 pb-4 overflow-y-auto flex-1">
            {Object.entries(GROUP_LABELS).map(([groupId, groupLabel]) => {
              const groupItems = navItems.filter((item) => item.group === groupId)
              if (groupItems.length === 0) return null
              return (
                <div key={groupId} className="mb-1">
                  <div className="px-3 py-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wider">
                    {groupLabel}
                  </div>
                  {groupItems.map((item) => {
                    const Icon = item.icon
                    const isActive =
                      location.pathname === item.path ||
                      (item.path !== '/dashboard' && location.pathname.startsWith(item.path + '/'))
                    return (
                      <Link
                        key={item.path}
                        to={item.path}
                        onClick={() => setSidebarOpen(false)}
                        className={`
                          flex items-center gap-3 px-3 py-2 rounded-lg transition-colors mb-0.5
                          ${isActive
                            ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                            : item.minRole === 'superadmin'
                              ? 'text-purple-400 hover:bg-purple-500/10 hover:text-purple-300'
                              : item.minRole === 'admin'
                                ? 'text-amber-400/80 hover:bg-amber-500/10 hover:text-amber-300'
                                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}
                        `}
                      >
                        <Icon className="w-4 h-4 shrink-0" />
                        <span className="font-medium text-sm truncate">{item.label}</span>
                        {item.minRole === 'superadmin' && !isActive && (
                          <Crown className="w-3 h-3 ml-auto opacity-50 shrink-0" />
                        )}
                      </Link>
                    )
                  })}
                </div>
              )
            })}
          </nav>

          <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-slate-800 space-y-3">
            {/* Dark / Light mode toggle */}
            <button
              onClick={toggleTheme}
              className="w-full flex items-center gap-3 px-4 py-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors text-sm"
            >
              {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              <span>{isDark ? 'Light mode' : 'Dark mode'}</span>
            </button>
            <ConnectionStatus connected={connected} latency={latency} />
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-h-screen overflow-auto">
          {/* No live feed banner — shown when broker is disconnected */}
          {noLiveFeed && (
            <div className="flex items-center gap-3 bg-amber-500/10 border-b border-amber-500/20 px-6 py-2 text-sm text-amber-400">
              <WifiOff className="w-4 h-4 shrink-0" />
              <span>{noLiveFeedMessage || 'No live broker connection. Prices are not updating.'}</span>
              <Link
                to="/settings"
                className="ml-auto underline underline-offset-2 hover:text-amber-300 transition-colors whitespace-nowrap"
              >
                Connect broker →
              </Link>
            </div>
          )}
          <div className="p-6 lg:p-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
