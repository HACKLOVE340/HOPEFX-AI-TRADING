/**
 * User Profile — dashboard version (Tailwind)
 * Wires to: GET /api/auth/me  |  GET /api/performance/public
 */
import { useState, useEffect } from 'react'
import { User, TrendingUp, Award, Copy, Shield, Edit2, Check } from 'lucide-react'
import { api } from '../hooks/useApi'
import { useStore } from '../store/useStore'

interface PublicStats {
  total_trades: number
  win_rate: number | null
  sharpe: number | null
  max_drawdown_pct: number
  avg_return_pct: number | null
  start_date: string
  note: string
}

export default function Profile() {
  const user = useStore(s => s.user)
  const [stats, setStats] = useState<PublicStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.get('/api/performance/public')
      .then(r => setStats(r.data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false))
  }, [])

  const copyRef = () => {
    navigator.clipboard.writeText(`https://hopefx.app/profile/${user?.username ?? 'demo'}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const badges = [
    { label: 'ML Trader',    color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',  earned: true },
    { label: 'Risk Master',  color: 'bg-green-500/20 text-green-400 border-green-500/30',  earned: true },
    { label: 'Paper Pilot',  color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',     earned: true },
    { label: 'Live Trader',  color: 'bg-purple-500/20 text-purple-400 border-purple-500/30', earned: false },
    { label: 'Sharpe 2.0+',  color: 'bg-pink-500/20 text-pink-400 border-pink-500/30',     earned: false },
  ]

  return (
    <div className="space-y-6">
      {/* Header card */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center text-2xl font-bold text-slate-900">
              {(user?.username ?? 'U')[0].toUpperCase()}
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-100">{user?.username ?? 'Demo User'}</h1>
              <p className="text-sm text-slate-400">{user?.email ?? 'demo@hopefx.app'}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded-full">
                  {user?.role ?? 'trader'}
                </span>
                <Shield className="w-3 h-3 text-green-400" />
                <span className="text-xs text-green-400">Verified</span>
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={copyRef}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
              {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? 'Copied!' : 'Share'}
            </button>
            <button className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
              <Edit2 className="w-3.5 h-3.5" />
              Edit
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stats */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Trading Performance</h2>
            {loading ? (
              <div className="text-center py-6 text-slate-500 text-sm">Loading performance data…</div>
            ) : !stats ? (
              <div className="text-center py-6 text-slate-500 text-sm">No performance data available yet.</div>
            ) : (
              <>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {[
                    { label: 'Total Trades',  value: stats.total_trades.toString(),                                          good: stats.total_trades >= 200 },
                    { label: 'Win Rate',      value: stats.win_rate != null ? `${(stats.win_rate*100).toFixed(1)}%` : '—',   good: (stats.win_rate ?? 0) >= 0.55 },
                    { label: 'Sharpe Ratio',  value: stats.sharpe != null ? stats.sharpe.toFixed(2) : '—',                  good: (stats.sharpe ?? 0) >= 1.5 },
                    { label: 'Max Drawdown',  value: `${stats.max_drawdown_pct.toFixed(1)}%`,                               good: stats.max_drawdown_pct < 5 },
                    { label: 'Avg Return',    value: stats.avg_return_pct != null ? `${stats.avg_return_pct.toFixed(2)}%` : '—', good: (stats.avg_return_pct ?? 0) > 0 },
                    { label: 'Since',         value: stats.start_date,                                                      good: true },
                  ].map(({ label, value, good }) => (
                    <div key={label} className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-500 mb-1">{label}</div>
                      <div className={`text-lg font-bold ${good ? 'text-slate-100' : 'text-amber-400'}`}>{value}</div>
                    </div>
                  ))}
                </div>
                {stats.note && <p className="text-xs text-slate-500 mt-4 italic">{stats.note}</p>}
              </>
            )}
          </div>
        </div>

        {/* Badges */}
        <div className="space-y-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Award className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Badges</h2>
            </div>
            <div className="space-y-2">
              {badges.map(({ label, color, earned }) => (
                <div key={label} className={`flex items-center justify-between px-3 py-2 rounded-lg border ${earned ? color : 'bg-slate-800/50 text-slate-600 border-slate-700/50'}`}>
                  <span className="text-sm font-medium">{label}</span>
                  {earned && <Check className="w-3.5 h-3.5" />}
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Rank</h2>
            </div>
            <div className="text-center">
              <div className="text-4xl font-black text-amber-400">#—</div>
              <div className="text-xs text-slate-500 mt-1">Complete 30-day paper run to rank</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
