import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, XCircle, TrendingUp, Calendar, Shield } from 'lucide-react'
import { extractApiError } from '../lib/utils'

interface PropFirmStatus {
  daily_loss_pct: number
  daily_loss_limit: number
  max_drawdown_pct: number
  max_drawdown_limit: number
  profit_target_pct: number
  profit_target_amount: number
  profit_target_goal: number
  trading_days_completed: number
  trading_days_required: number
  paused: boolean
  kill_switch_active: boolean
  ai_message: string
  current_equity: number
  starting_equity: number
}

function ProgressBar({
  value,
  limit,
  label,
  amount,
  invert = false,
}: {
  value: number
  limit: number
  label: string
  amount?: string
  invert?: boolean
}) {
  // invert=true means higher is better (profit target)
  const pct = Math.min((value / limit) * 100, 100)
  const danger = invert ? pct >= 100 : pct >= 95
  const warn = invert ? false : pct >= 80

  const barColor = danger
    ? 'bg-red-500'
    : warn
    ? 'bg-amber-400'
    : invert
    ? 'bg-emerald-500'
    : 'bg-blue-500'

  const labelColor = danger ? 'text-red-400' : warn ? 'text-amber-400' : 'text-slate-300'

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-1">
        <span className="text-sm text-slate-400">{label}</span>
        <span className={`text-sm font-mono font-semibold ${labelColor}`}>
          {amount ?? `${(value * 100).toFixed(2)}% / ${(limit * 100).toFixed(0)}%`}
        </span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-3 overflow-hidden">
        <div
          className={`h-3 rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function PropFirmTracker() {
  const [status, setStatus] = useState<PropFirmStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/risk/prop-firm-status')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: PropFirmStatus = await res.json()
      setStatus(data)
      setError(null)
    } catch (e: unknown) {
      setError(extractApiError(e, 'Failed to load status'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 10_000) // refresh every 10s
    return () => clearInterval(interval)
  }, [])

  const StatusIcon = () => {
    if (!status) return null
    if (status.kill_switch_active) return <XCircle className="text-red-500 w-6 h-6" />
    if (status.paused) return <AlertTriangle className="text-amber-400 w-6 h-6" />
    return <CheckCircle className="text-emerald-500 w-6 h-6" />
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Shield className="text-yellow-400 w-7 h-7" />
        <h1 className="text-2xl font-bold text-white">Prop Firm Challenge Tracker</h1>
        <StatusIcon />
      </div>

      {loading && (
        <div className="text-slate-400 text-center py-12">Loading challenge status…</div>
      )}

      {error && (
        <div className="bg-red-900/40 border border-red-700 rounded-lg p-4 text-red-300 mb-4">
          {error}
        </div>
      )}

      {status && (
        <>
          {/* AI message banner */}
          <div
            className={`rounded-lg p-4 mb-6 border text-sm font-medium ${
              status.kill_switch_active
                ? 'bg-red-900/40 border-red-700 text-red-300'
                : status.paused
                ? 'bg-amber-900/40 border-amber-700 text-amber-300'
                : 'bg-emerald-900/30 border-emerald-700 text-emerald-300'
            }`}
          >
            🤖 AI: {status.ai_message}
          </div>

          {/* Equity summary */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-slate-800 rounded-lg p-4">
              <div className="text-xs text-slate-400 mb-1">Current Equity</div>
              <div className="text-xl font-mono font-bold text-white">
                ${status.current_equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
            <div className="bg-slate-800 rounded-lg p-4">
              <div className="text-xs text-slate-400 mb-1">Starting Equity</div>
              <div className="text-xl font-mono font-bold text-slate-300">
                ${status.starting_equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>

          {/* Progress bars */}
          <div className="bg-slate-800 rounded-xl p-6">
            <ProgressBar
              label="Daily Loss"
              value={status.daily_loss_pct}
              limit={status.daily_loss_limit}
              amount={`${(status.daily_loss_pct * 100).toFixed(2)}% / ${(status.daily_loss_limit * 100).toFixed(0)}% limit`}
            />
            <ProgressBar
              label="Max Drawdown"
              value={status.max_drawdown_pct}
              limit={status.max_drawdown_limit}
              amount={`${(status.max_drawdown_pct * 100).toFixed(2)}% / ${(status.max_drawdown_limit * 100).toFixed(0)}% limit`}
            />
            <ProgressBar
              label="Profit Target"
              value={status.profit_target_pct}
              limit={1.0}
              invert
              amount={`$${status.profit_target_amount.toFixed(0)} / $${status.profit_target_goal.toFixed(0)}`}
            />

            {/* Trading days */}
            <div className="mt-2">
              <div className="flex justify-between items-center mb-1">
                <span className="text-sm text-slate-400 flex items-center gap-1">
                  <Calendar className="w-4 h-4" /> Trading Days
                </span>
                <span className="text-sm font-mono text-slate-300">
                  {status.trading_days_completed} / {status.trading_days_required}
                </span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-3 overflow-hidden">
                <div
                  className="h-3 rounded-full bg-blue-500 transition-all duration-500"
                  style={{
                    width: `${Math.min(
                      (status.trading_days_completed / status.trading_days_required) * 100,
                      100
                    )}%`,
                  }}
                />
              </div>
            </div>
          </div>

          {/* Profit trend icon */}
          <div className="flex items-center gap-2 mt-4 text-slate-400 text-sm">
            <TrendingUp className="w-4 h-4" />
            <span>
              P&amp;L:{' '}
              <span
                className={
                  status.profit_target_amount >= 0 ? 'text-emerald-400' : 'text-red-400'
                }
              >
                {status.profit_target_amount >= 0 ? '+' : ''}$
                {status.profit_target_amount.toFixed(2)}
              </span>
            </span>
          </div>
        </>
      )}
    </div>
  )
}
