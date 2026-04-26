/**
 * SuperAdmin Dashboard
 *
 * Provides a unified control surface for superadmin users:
 *   - Platform-wide stats (users, revenue, tenants, ML health)
 *   - Toggle to view the full Admin Panel inline (no separate navigation)
 *   - Quick-links to every superadmin sub-section
 *   - "Back to SuperAdmin" button always visible when in admin view
 *
 * API endpoints used:
 *   GET /api/admin/stats          — system health (shared with AdminPanel)
 *   GET /api/admin/activity       — recent activity log
 *   GET /api/whitelabel/tenants   — tenant count
 *   GET /api/superadmin/overview  — platform-wide metrics
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Crown, Shield, Users, Activity, Server, Database,
  RefreshCw, CheckCircle, XCircle, AlertTriangle,
  TrendingUp, Globe, Cpu, Lock, ChevronRight,
  LayoutDashboard, ArrowLeft, ToggleLeft, ToggleRight,
  Zap, Eye, Settings2, FileText, Wrench,
} from 'lucide-react'
import axios from 'axios'
import AdminPanel from './AdminPanel'

// ── Types ─────────────────────────────────────────────────────────────────────

interface SystemStats {
  total_users: number
  active_sessions: number
  open_positions: number
  signals_today: number
  api_requests_1h: number
  error_rate_pct: number
  uptime_hours: number
  db_pool_used: number
  db_pool_max: number
  redis_connected: boolean
  broker_connected: boolean
  ml_model_loaded: boolean
}

interface OverviewStats {
  total_revenue_usd: number
  active_tenants: number
  total_tenants: number
  platform_version: string
  ml_models_loaded: number
  active_strategies: number
  nuclear_level: number
  kill_switch_active: boolean
}

const EMPTY_STATS: SystemStats = {
  total_users: 0, active_sessions: 0, open_positions: 0, signals_today: 0,
  api_requests_1h: 0, error_rate_pct: 0, uptime_hours: 0,
  db_pool_used: 0, db_pool_max: 20, redis_connected: false,
  broker_connected: false, ml_model_loaded: false,
}

const EMPTY_OVERVIEW: OverviewStats = {
  total_revenue_usd: 0, active_tenants: 0, total_tenants: 0,
  platform_version: '—', ml_models_loaded: 0, active_strategies: 0,
  nuclear_level: 0, kill_switch_active: false,
}

// ── Sub-components ────────────────────────────────────────────────────────────

const StatusDot = ({ ok }: { ok: boolean }) => (
  <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${ok ? 'text-green-400' : 'text-red-400'}`}>
    {ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
    {ok ? 'OK' : 'DOWN'}
  </span>
)

interface QuickLinkProps {
  icon: React.ElementType
  label: string
  description: string
  href: string
  badge?: string
  badgeColor?: string
}

const QuickLink = ({ icon: Icon, label, description, href, badge, badgeColor = 'bg-amber-500/20 text-amber-400' }: QuickLinkProps) => {
  const navigate = useNavigate()
  return (
    <button
      onClick={() => navigate(href)}
      className="group flex items-center gap-4 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 rounded-xl p-4 transition-all text-left w-full"
    >
      <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
        <Icon className="w-5 h-5 text-amber-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-200 text-sm">{label}</span>
          {badge && <span className={`text-xs px-1.5 py-0.5 rounded-full border ${badgeColor}`}>{badge}</span>}
        </div>
        <p className="text-xs text-slate-500 mt-0.5 truncate">{description}</p>
      </div>
      <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors flex-shrink-0" />
    </button>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function SuperAdminDashboard() {
  const [stats, setStats] = useState<SystemStats>(EMPTY_STATS)
  const [overview, setOverview] = useState<OverviewStats>(EMPTY_OVERVIEW)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Toggle: when true, renders the full AdminPanel inline
  const [showAdminView, setShowAdminView] = useState(false)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const [sysRes, overviewRes, tenantsRes] = await Promise.allSettled([
        axios.get('/api/admin/stats'),
        axios.get('/api/superadmin/overview'),
        axios.get('/api/whitelabel/tenants'),
      ])

      if (sysRes.status === 'fulfilled') {
        setStats(sysRes.value.data ?? EMPTY_STATS)
      }

      // Build overview from superadmin endpoint or fall back to system stats
      const ov: OverviewStats = { ...EMPTY_OVERVIEW }
      if (overviewRes.status === 'fulfilled') {
        Object.assign(ov, overviewRes.value.data ?? {})
      }
      if (tenantsRes.status === 'fulfilled') {
        const t = tenantsRes.value.data
        ov.total_tenants = t?.total ?? ov.total_tenants
        ov.active_tenants = (t?.tenants ?? []).filter((x: { status: string }) => x.status === 'active').length
      }
      setOverview(ov)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load superadmin data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  // ── Admin view toggle ──────────────────────────────────────────────────────
  if (showAdminView) {
    return (
      <div className="space-y-4">
        {/* Sticky back bar */}
        <div className="flex items-center justify-between bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 text-amber-400 text-sm font-medium">
            <Crown className="w-4 h-4" />
            <span>Viewing as Admin — SuperAdmin context active</span>
          </div>
          <button
            onClick={() => setShowAdminView(false)}
            className="flex items-center gap-2 px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to SuperAdmin
          </button>
        </div>
        {/* Full admin panel rendered inline */}
        <AdminPanel />
      </div>
    )
  }

  // ── SuperAdmin main view ───────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
            <Crown className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-100">SuperAdmin</h1>
            <p className="text-sm text-slate-400">Full platform control — all systems visible.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAdminView(true)}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-lg text-sm font-medium transition-colors"
          >
            <Shield className="w-4 h-4 text-amber-400" />
            Admin View
            <ToggleLeft className="w-4 h-4 text-slate-500" />
          </button>
          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}

      {/* Nuclear / kill switch alert */}
      {(overview.kill_switch_active || overview.nuclear_level > 0) && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <div className="font-semibold text-red-300 text-sm">
              {overview.kill_switch_active ? 'Kill Switch Active — All trading halted' : `Nuclear Level ${overview.nuclear_level} — Elevated risk mode`}
            </div>
            <div className="text-xs text-red-400/70 mt-0.5">
              Navigate to Nuclear Supervisor to manage risk state.
            </div>
          </div>
        </div>
      )}

      {/* Platform KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            icon: Users,
            label: 'Total Users',
            value: stats.total_users.toLocaleString(),
            sub: `${stats.active_sessions} active sessions`,
            color: 'text-blue-400',
          },
          {
            icon: Globe,
            label: 'Tenants',
            value: overview.total_tenants.toString(),
            sub: `${overview.active_tenants} active`,
            color: 'text-cyan-400',
          },
          {
            icon: TrendingUp,
            label: 'Revenue',
            value: `$${(overview.total_revenue_usd / 1000).toFixed(1)}k`,
            sub: 'platform total',
            color: 'text-green-400',
          },
          {
            icon: Cpu,
            label: 'ML Models',
            value: overview.ml_models_loaded.toString(),
            sub: `${overview.active_strategies} strategies active`,
            color: 'text-purple-400',
          },
          {
            icon: Activity,
            label: 'API Req / hr',
            value: stats.api_requests_1h.toLocaleString(),
            sub: `${stats.error_rate_pct.toFixed(2)}% error rate`,
            color: 'text-amber-400',
          },
          {
            icon: Server,
            label: 'Uptime',
            value: `${stats.uptime_hours}h`,
            sub: 'since last restart',
            color: 'text-slate-400',
          },
          {
            icon: Database,
            label: 'DB Pool',
            value: `${stats.db_pool_used}/${stats.db_pool_max}`,
            sub: 'connections used',
            color: 'text-slate-400',
          },
          {
            icon: Zap,
            label: 'Signals Today',
            value: stats.signals_today.toString(),
            sub: `${stats.open_positions} open positions`,
            color: 'text-yellow-400',
          },
        ].map(({ icon: Icon, label, value, sub, color }) => (
          <div key={label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`w-4 h-4 ${color}`} />
              <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
            </div>
            <div className="text-2xl font-bold text-slate-100">{value}</div>
            <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
          </div>
        ))}
      </div>

      {/* Service health */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Service Health</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: 'Database',  ok: true },
            { label: 'Redis',     ok: stats.redis_connected },
            { label: 'Broker',    ok: stats.broker_connected },
            { label: 'ML Model',  ok: stats.ml_model_loaded },
            { label: 'WebSocket', ok: true },
            { label: 'Prometheus',ok: true },
          ].map(({ label, ok }) => (
            <div key={label} className="flex items-center justify-between bg-slate-800 rounded-lg px-3 py-2.5">
              <span className="text-xs text-slate-300">{label}</span>
              <StatusDot ok={ok} />
            </div>
          ))}
        </div>
      </div>

      {/* Quick navigation — all superadmin sections */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Platform Controls</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <QuickLink
            icon={Shield}
            label="Admin Panel"
            description="System health, kill switch, user management, feature flags"
            href="/admin"
            badge="admin+"
          />
          <QuickLink
            icon={Globe}
            label="Whitelabel Tenants"
            description="Create and manage reseller tenants, API keys, branding"
            href="/whitelabel"
            badge="superadmin"
            badgeColor="bg-purple-500/20 text-purple-400 border-purple-500/30"
          />
          <QuickLink
            icon={Users}
            label="User Management"
            description="Ban, unban, impersonate, reset passwords, view trade history"
            href="/admin"
          />
          <QuickLink
            icon={Lock}
            label="Nuclear Supervisor"
            description="Kill switch, risk orchestrator, hedge controls, event history"
            href="/admin"
            badge="critical"
            badgeColor="bg-red-500/20 text-red-400 border-red-500/30"
          />
          <QuickLink
            icon={Cpu}
            label="ML & AI Controls"
            description="Model retraining, anomaly detection, online learner, brain status"
            href="/admin"
          />
          <QuickLink
            icon={Eye}
            label="Chaos & Mutation"
            description="Run chaos scenarios, mutation testing, view results"
            href="/admin"
            badge="admin"
          />
          <QuickLink
            icon={TrendingUp}
            label="Revenue Analytics"
            description="MRR, ARR, churn, LTV, revenue breakdown by source and tier"
            href="/admin"
          />
          <QuickLink
            icon={Settings2}
            label="Feature Flags"
            description="Enable/disable features at runtime, per-user overrides"
            href="/admin"
          />
          <QuickLink
            icon={FileText}
            label="Audit Log"
            description="Full platform audit trail — filter by user, event type, export CSV"
            href="/admin"
          />
          <QuickLink
            icon={Wrench}
            label="Platform Settings"
            description="Risk parameters, broker config, system settings"
            href="/settings"
          />
          <QuickLink
            icon={Activity}
            label="Reliability"
            description="Circuit breakers, hot standby, auto-rollback history, component probes"
            href="/superadmin/reliability"
            badge="live"
            badgeColor="bg-green-500/20 text-green-400 border-green-500/30"
          />
        </div>
      </div>

      {/* Admin view toggle — bottom CTA */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="w-5 h-5 text-amber-400" />
          <div>
            <div className="font-medium text-slate-200 text-sm">Admin Dashboard View</div>
            <div className="text-xs text-slate-500 mt-0.5">
              See exactly what an admin sees — kill switch, stats, activity log, feature flags.
            </div>
          </div>
        </div>
        <button
          onClick={() => setShowAdminView(v => !v)}
          className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold transition-colors"
        >
          {showAdminView ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
          {showAdminView ? 'Exit Admin View' : 'Enter Admin View'}
        </button>
      </div>

    </div>
  )
}
