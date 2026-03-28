import { useEffect, useState, useCallback } from 'react'
import { useStore } from '../store/useStore'
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Activity,
  Target,
  Shield,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react'
import { EquityChart } from '../components/EquityChart'
import { DrawdownChart } from '../components/DrawdownChart'
import { RecentTrades } from '../components/RecentTrades'
import { MLSignals } from '../components/MLSignals'
import { SignalExplanation } from '../components/SignalExplanation'
import { MacroPanel } from '../components/MacroPanel'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PublicPerformance {
  total_trades: number
  win_rate: number | null
  avg_return_pct: number | null
  sharpe: number | null
  max_drawdown_pct: number
  start_date: string
  note: string
}

type FetchState = 'idle' | 'loading' | 'ok' | 'error'

// ── Dashboard ─────────────────────────────────────────────────────────────────

export function Dashboard() {
  const account = useStore((state) => state.account)
  const equity = account?.equity ?? 0
  const dailyPnl = account?.daily_pnl ?? null
  const dailyPnlPct = account?.daily_pnl_pct ?? null
  const winRate = account?.win_rate ?? null
  const sharpe = account?.sharpe_ratio ?? null
  const maxDrawdown = account?.max_drawdown ?? null
  const marginUsed = account?.margin_used ?? null
  const marginFree = account?.margin_free ?? null
  const openTrades = account?.open_trades ?? null

  const [perf, setPerf] = useState<PublicPerformance | null>(null)
  const [perfState, setPerfState] = useState<FetchState>('idle')

  const fetchPerf = useCallback(async () => {
    setPerfState('loading')
    try {
      const res = await fetch('/api/performance/public')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: PublicPerformance = await res.json()
      setPerf(data)
      setPerfState('ok')
    } catch {
      setPerfState('error')
    }
  }, [])

  useEffect(() => {
    fetchPerf()
    // Refresh every 60 s so stats stay current without hammering the server
    const id = setInterval(fetchPerf, 60_000)
    return () => clearInterval(id)
  }, [fetchPerf])

  // Prefer live account data from WebSocket; fall back to REST performance stats
  const displayDailyReturnPct =
    dailyPnlPct !== null ? dailyPnlPct : perf?.avg_return_pct ?? null
  const displaySharpe = sharpe !== null ? sharpe : perf?.sharpe ?? null
  const displayWinRate = winRate !== null ? winRate : perf?.win_rate ?? null
  const displayMaxDD =
    maxDrawdown !== null ? maxDrawdown : perf?.max_drawdown_pct ?? null

  return (
    <div className="space-y-6">
      {/* Header Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          title="Equity"
          value={equity > 0 ? `$${equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
          sub={
            dailyPnl !== null
              ? `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)} today`
              : 'Awaiting account data'
          }
          icon={DollarSign}
          color="amber"
          loading={account === null}
        />
        <StatCard
          title="Daily Return"
          value={
            displayDailyReturnPct !== null
              ? `${displayDailyReturnPct >= 0 ? '+' : ''}${displayDailyReturnPct.toFixed(2)}%`
              : '—'
          }
          sub={
            dailyPnl !== null
              ? `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`
              : perfState === 'loading' ? 'Loading…' : 'No data yet'
          }
          icon={displayDailyReturnPct !== null && displayDailyReturnPct >= 0 ? TrendingUp : TrendingDown}
          color={displayDailyReturnPct !== null && displayDailyReturnPct >= 0 ? 'green' : 'red'}
          loading={account === null && perfState === 'loading'}
        />
        <StatCard
          title="Total Trades"
          value={
            perf?.total_trades !== undefined && perf.total_trades > 0
              ? perf.total_trades.toLocaleString()
              : openTrades !== null
              ? openTrades.toString()
              : '—'
          }
          sub={perf?.start_date ? `Since ${perf.start_date}` : 'No history yet'}
          icon={Target}
          color="blue"
          loading={perfState === 'loading'}
        />
        <StatCard
          title="Sharpe Ratio"
          value={displaySharpe !== null ? displaySharpe.toFixed(2) : '—'}
          sub={
            displaySharpe === null
              ? perf?.note?.includes('50')
                ? perf.note
                : 'Need 50+ trades'
              : displaySharpe >= 1.5
              ? 'Excellent'
              : displaySharpe >= 1.0
              ? 'Good'
              : 'Below target'
          }
          icon={Activity}
          color="purple"
          loading={account === null && perfState === 'loading'}
        />
        <StatCard
          title="Win Rate"
          value={displayWinRate !== null ? `${displayWinRate.toFixed(1)}%` : '—'}
          sub={
            perf?.total_trades && perf.win_rate !== null
              ? `${Math.round((perf.win_rate / 100) * perf.total_trades)}W / ${Math.round((1 - perf.win_rate / 100) * perf.total_trades)}L`
              : 'No closed trades'
          }
          icon={Shield}
          color="emerald"
          loading={account === null && perfState === 'loading'}
        />
      </div>

      {/* Performance fetch error banner */}
      {perfState === 'error' && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Could not load performance stats from server.</span>
          <button
            onClick={fetchPerf}
            className="ml-auto flex items-center gap-1 hover:text-red-300 transition-colors"
          >
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      )}

      {/* Performance note (e.g. "accumulating data") */}
      {perfState === 'ok' && perf?.note && (
        <p className="text-xs text-slate-500 px-1">{perf.note}</p>
      )}

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Equity Curve</h3>
            <EquityChart />
          </div>

          <DrawdownChart />

          <RecentTrades />
        </div>

        <div className="space-y-6">
          <MLSignals />

          <SignalExplanation />

          <MacroPanel />

          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Risk Metrics</h3>
            <div className="space-y-3">
              <RiskBar
                label="Daily Loss Limit"
                current={displayDailyReturnPct !== null ? Math.abs(Math.min(displayDailyReturnPct, 0)) : null}
                max={2.0}
                color="red"
                unit="%"
              />
              <RiskBar
                label="Position Risk"
                current={
                  marginUsed !== null && equity > 0
                    ? (marginUsed / equity) * 100
                    : null
                }
                max={100}
                color="amber"
                unit="%"
              />
              <RiskBar
                label="Drawdown"
                current={displayMaxDD !== null ? Math.abs(displayMaxDD) : null}
                max={5.0}
                color="green"
                unit="%"
              />
              <RiskBar
                label="Margin Used"
                current={marginUsed ?? null}
                max={(marginUsed ?? 0) + (marginFree ?? 50000)}
                color="blue"
                unit="$"
                formatValue={(v) =>
                  `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                }
              />
            </div>
          </div>

          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Active Session</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-400">Open Trades</span>
                <span>{openTrades !== null ? openTrades : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Margin Used</span>
                <span>
                  {marginUsed !== null
                    ? `$${marginUsed.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Margin Free</span>
                <span>
                  {marginFree !== null
                    ? `$${marginFree.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Daily P&L</span>
                <span
                  className={
                    dailyPnl === null
                      ? 'text-slate-400'
                      : dailyPnl >= 0
                      ? 'text-green-400'
                      : 'text-red-400'
                  }
                >
                  {dailyPnl !== null
                    ? `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`
                    : '—'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface StatCardProps {
  title: string
  value: string
  sub: string
  icon: React.ElementType
  color: string
  loading?: boolean
}

function StatCard({ title, value, sub, icon: Icon, color, loading }: StatCardProps) {
  const colors: Record<string, string> = {
    amber: 'bg-amber-500/10 text-amber-400',
    green: 'bg-green-500/10 text-green-400',
    red: 'bg-red-500/10 text-red-400',
    blue: 'bg-blue-500/10 text-blue-400',
    purple: 'bg-purple-500/10 text-purple-400',
    emerald: 'bg-emerald-500/10 text-emerald-400',
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-slate-400 text-sm">{title}</span>
        <div className={`p-2 rounded ${colors[color] ?? colors.blue}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      {loading ? (
        <div className="h-8 w-24 bg-slate-800 rounded animate-pulse mb-1" />
      ) : (
        <div className="text-2xl font-bold">{value}</div>
      )}
      <div className="text-xs text-slate-500 mt-1 truncate">{sub}</div>
    </div>
  )
}

interface RiskBarProps {
  label: string
  current: number | null
  max: number
  color: string
  unit?: string
  formatValue?: (v: number) => string
}

function RiskBar({ label, current, max, color, unit = '', formatValue }: RiskBarProps) {
  const pct = current !== null && max > 0 ? (Math.abs(current) / max) * 100 : 0
  const colors: Record<string, string> = {
    red: 'bg-red-500',
    amber: 'bg-amber-500',
    green: 'bg-green-500',
    blue: 'bg-blue-500',
  }

  const displayCurrent =
    current === null
      ? '—'
      : formatValue
      ? formatValue(current)
      : `${current.toFixed(unit === '%' ? 1 : 0)}${unit}`

  const displayMax = formatValue ? formatValue(max) : `${max}${unit}`

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-400">{label}</span>
        <span className={current === null ? 'text-slate-500' : ''}>
          {displayCurrent}
          {current !== null && ` / ${displayMax}`}
        </span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${colors[color]} transition-all duration-500`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  )
}
