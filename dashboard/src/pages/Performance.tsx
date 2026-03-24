import { useEffect, useState } from 'react'
import { TrendingUp, Award, BarChart2, Shield, Clock, RefreshCw } from 'lucide-react'
import { EquityChart } from '../components/EquityChart'
import { DrawdownChart } from '../components/DrawdownChart'

interface PublicPerformance {
  total_trades: number
  win_rate: number | null
  avg_return_pct: number | null
  sharpe: number | null
  max_drawdown_pct: number
  start_date: string
  note: string
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color = 'amber',
}: {
  label: string
  value: string
  sub?: string
  icon: any
  color?: string
}) {
  const colors: Record<string, string> = {
    amber: 'bg-amber-500/10 text-amber-400',
    green: 'bg-emerald-500/10 text-emerald-400',
    blue: 'bg-blue-500/10 text-blue-400',
    red: 'bg-red-500/10 text-red-400',
    purple: 'bg-purple-500/10 text-purple-400',
  }
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-slate-400">{label}</span>
        <div className={`p-2 rounded-lg ${colors[color]}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="text-2xl font-bold text-slate-100">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  )
}

export function Performance() {
  const [data, setData] = useState<PublicPerformance | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/performance/public')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5 * 60 * 1000) // refresh every 5 min
    return () => clearInterval(id)
  }, [])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Live Performance</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real paper trading results — updated continuously
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-slate-500">Updated {lastUpdated}</span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          Failed to load performance data: {error}
        </div>
      )}

      {/* Stats grid */}
      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard
              label="Total Trades"
              value={data.total_trades.toString()}
              sub="Paper trading"
              icon={BarChart2}
              color="blue"
            />
            <StatCard
              label="Win Rate"
              value={data.win_rate !== null ? `${data.win_rate}%` : '—'}
              sub={data.win_rate === null ? 'Need 50+ trades' : 'Winning trades'}
              icon={TrendingUp}
              color="green"
            />
            <StatCard
              label="Avg Return / Trade"
              value={
                data.avg_return_pct !== null
                  ? `${data.avg_return_pct > 0 ? '+' : ''}${data.avg_return_pct}%`
                  : '—'
              }
              sub="Per completed trade"
              icon={Award}
              color="amber"
            />
            <StatCard
              label="Sharpe Ratio"
              value={data.sharpe !== null ? data.sharpe.toString() : '—'}
              sub={data.sharpe === null ? 'Need 50+ data points' : 'Annualised'}
              icon={BarChart2}
              color="purple"
            />
            <StatCard
              label="Max Drawdown"
              value={`${data.max_drawdown_pct}%`}
              sub="Peak-to-trough"
              icon={Shield}
              color="red"
            />
          </div>

          {/* Honest caveat */}
          <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-400">
            <div className="flex items-start gap-2">
              <Clock className="w-4 h-4 mt-0.5 shrink-0 text-amber-400" />
              <div>
                <span className="text-slate-300 font-medium">Transparency note: </span>
                {data.note}
                {data.start_date !== '—' && (
                  <span className="ml-1">Paper trading started: {data.start_date}.</span>
                )}
              </div>
            </div>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
              <h3 className="font-semibold mb-4">Equity Curve</h3>
              <EquityChart />
            </div>
            <DrawdownChart />
          </div>
        </>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center h-48 text-slate-500">
          Loading performance data…
        </div>
      )}

      {/* Public API link */}
      <div className="p-4 rounded-lg bg-slate-900 border border-slate-800 text-sm">
        <p className="text-slate-400">
          Raw data available at{' '}
          <a
            href="/api/performance/public"
            target="_blank"
            rel="noopener noreferrer"
            className="text-amber-400 hover:text-amber-300 font-mono"
          >
            /api/performance/public
          </a>{' '}
          — no authentication required.
        </p>
      </div>
    </div>
  )
}
