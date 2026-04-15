/**
 * Admin Panel — dashboard version (Tailwind)
 * Wires to: GET /api/admin/stats  |  GET /api/admin/activity
 * Requires: admin or superadmin role
 */
import { useState, useEffect } from 'react'
import { Shield, Users, Activity, AlertTriangle, Server, Database, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import axios from 'axios'

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

interface ActivityEntry {
  id: string
  timestamp: string
  user: string
  action: string
  level: 'info' | 'warning' | 'error'
}

const EMPTY_STATS: SystemStats = {
  total_users: 0, active_sessions: 0, open_positions: 0, signals_today: 0,
  api_requests_1h: 0, error_rate_pct: 0, uptime_hours: 0,
  db_pool_used: 0, db_pool_max: 20, redis_connected: false,
  broker_connected: false, ml_model_loaded: false,
}

const StatusDot = ({ ok }: { ok: boolean }) => (
  <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${ok ? 'text-green-400' : 'text-red-400'}`}>
    {ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
    {ok ? 'OK' : 'DOWN'}
  </span>
)

export default function AdminPanel() {
  const [stats, setStats] = useState<SystemStats>(EMPTY_STATS)
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [killSwitchActive, setKillSwitchActive] = useState(false)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, a] = await Promise.all([
        axios.get('/api/admin/stats'),
        axios.get('/api/admin/activity'),
      ])
      setStats(s.data ?? EMPTY_STATS)
      setActivity(a.data.entries ?? a.data ?? [])
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load admin data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const toggleKillSwitch = async () => {
    try {
      await axios.post(`/api/admin/kill-switch/${killSwitchActive ? 'deactivate' : 'activate'}`)
      setKillSwitchActive(k => !k)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Kill switch toggle failed.')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Admin Panel</h1>
            <p className="text-sm text-slate-400">System health, user management, and risk controls.</p>
          </div>
        </div>
        <button onClick={refresh} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}

      {/* Kill switch */}
      <div className={`rounded-xl border p-4 flex items-center justify-between ${killSwitchActive ? 'bg-red-500/10 border-red-500/30' : 'bg-slate-900 border-slate-800'}`}>
        <div className="flex items-center gap-3">
          <AlertTriangle className={`w-5 h-5 ${killSwitchActive ? 'text-red-400' : 'text-slate-500'}`} />
          <div>
            <div className="font-semibold text-slate-200">Kill Switch</div>
            <div className="text-xs text-slate-400">{killSwitchActive ? 'All trading halted — manual reactivation required' : 'Trading active — click to halt all positions'}</div>
          </div>
        </div>
        <button onClick={toggleKillSwitch}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${killSwitchActive ? 'bg-green-500 hover:bg-green-400 text-slate-900' : 'bg-red-500 hover:bg-red-400 text-white'}`}>
          {killSwitchActive ? 'Reactivate Trading' : 'Halt All Trading'}
        </button>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { icon: Users,    label: 'Total Users',      value: stats.total_users.toString(),       sub: `${stats.active_sessions} active` },
          { icon: Activity, label: 'API Req / Hour',   value: stats.api_requests_1h.toLocaleString(), sub: `${stats.error_rate_pct.toFixed(2)}% errors` },
          { icon: Server,   label: 'Uptime',           value: `${stats.uptime_hours}h`,           sub: 'since last restart' },
          { icon: Database, label: 'DB Pool',          value: `${stats.db_pool_used}/${stats.db_pool_max}`, sub: 'connections used' },
        ].map(({ icon: Icon, label, value, sub }) => (
          <div key={label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon className="w-4 h-4 text-amber-400" />
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
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {[
            { label: 'Database',    ok: true },
            { label: 'Redis',       ok: stats.redis_connected },
            { label: 'Broker',      ok: stats.broker_connected },
            { label: 'ML Model',    ok: stats.ml_model_loaded },
            { label: 'WebSocket',   ok: true },
            { label: 'Prometheus',  ok: true },
          ].map(({ label, ok }) => (
            <div key={label} className="flex items-center justify-between bg-slate-800 rounded-lg px-4 py-3">
              <span className="text-sm text-slate-300">{label}</span>
              <StatusDot ok={ok} />
            </div>
          ))}
        </div>
      </div>

      {/* Activity log */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-300">Activity Log</h2>
        </div>
        <div className="divide-y divide-slate-800/50">
          {activity.length === 0 && (
            <div className="px-6 py-8 text-center text-slate-500 text-sm">No activity entries yet.</div>
          )}
          {activity.map(entry => (
            <div key={entry.id} className="flex items-start gap-3 px-6 py-3">
              <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                entry.level === 'error' ? 'bg-red-400' : entry.level === 'warning' ? 'bg-amber-400' : 'bg-green-400'
              }`} />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-slate-300">{entry.action}</div>
                <div className="text-xs text-slate-600 mt-0.5">{entry.user} · {entry.timestamp}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
