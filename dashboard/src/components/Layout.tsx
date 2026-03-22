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
  Bell
} from 'lucide-react'
import { useWebSocket } from '../hooks/useWebSocket'
import { ConnectionStatus } from './ConnectionStatus'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/trading', icon: TrendingUp, label: 'Trading' },
  { path: '/copy-trading', icon: Users, label: 'Copy Trading' },
  { path: '/leaderboard', icon: Trophy, label: 'Leaderboard' },
  { path: '/wallet', icon: Wallet, label: 'Wallet' },
  { path: '/settings', icon: Settings, label: 'Settings' },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const { connected, latency } = useWebSocket()

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Mobile header */}
      <div className="lg:hidden flex items-center justify-between p-4 border-b border-slate-800">
        <button onClick={() => setSidebarOpen(!sidebarOpen)}>
          {sidebarOpen ? <X /> : <Menu />}
        </button>
        <span className="font-bold text-xl">HOPEFX</span>
        <Bell className="w-6 h-6" />
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

          <nav className="px-4 space-y-2">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = location.pathname === item.path
              
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setSidebarOpen(false)}
                  className={`
                    flex items-center gap-3 px-4 py-3 rounded-lg transition-colors
                    ${isActive 
                      ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' 
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}
                  `}
                >
                  <Icon className="w-5 h-5" />
                  <span className="font-medium">{item.label}</span>
                </Link>
              )
            })}
          </nav>

          <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-slate-800">
            <ConnectionStatus connected={connected} latency={latency} />
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-h-screen overflow-auto">
          <div className="p-6 lg:p-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
