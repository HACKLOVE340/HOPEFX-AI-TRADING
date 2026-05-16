/**
 * Positioning — Dedicated position management page
 *
 * Sections:
 *   1. Summary bar  — total float P&L, open positions count, margin used, win rate
 *   2. Open positions — PositionCard (full mode) per position
 *   3. Closed trades  — paginated trade history with P&L, duration, R:R
 *   4. Risk per trade — position sizing calculator
 *   5. Correlation matrix — symbol correlation heatmap
 */
import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp, TrendingDown, DollarSign, BarChart2,
  RefreshCw, AlertTriangle, Calculator, Activity,
  ChevronLeft, ChevronRight, Clock,
} from 'lucide-react'
import { useStore } from '../store/useStore'
import { tradingApi, performanceApi } from '../hooks/useApi'
import { PositionCard } from '../components/PositionCard'
import { RiskBar } from '../components/RiskGauge'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ClosedTrade {
  id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  entry_price: number
  exit_price: number | null
  pnl: number | null
  pnl_pct: number | null
  opened_at: string
  closed_at: string | null
  status: 'open' | 'closed'
  duration_minutes?: number | null
  commission?: number
}

interface CorrelationData {
  symbols: string[]
  matrix: number[][]
}

// ─── Summary bar ──────────────────────────────────────────────────────────────

function SummaryBar() {
  const positions = useStore((s) => s.positions)
  const account = useStore((s) => s.account)

  const totalFloat = positions.reduce((s, p) => s + p.unrealized_pnl, 0)
  const longCount = positions.filter((p) => p.side === 'long').length
  const shortCount = positions.filter((p) => p.side === 'short').length
  const marginUsed = account?.margin_used ?? null
  const equity = account?.equity ?? null
  const winRate = account?.win_rate ?? null

  const stats = [
    {
      label: 'Float P&L',
      value: positions.length > 0
        ? `${totalFloat >= 0 ? '+' : ''}$${totalFloat.toFixed(2)}`
        : '—',
      color: totalFloat >= 0 ? 'text-green-400' : 'text-red-400',
      icon: totalFloat >= 0 ? TrendingUp : TrendingDown,
      iconColor: totalFloat >= 0 ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400',
    },
    {
      label: 'Open Positions',
      value: positions.length.toString(),
      sub: `${longCount}L / ${shortCount}S`,
      color: 'text-slate-100',
      icon: BarChart2,
      iconColor: 'bg-blue-500/10 text-blue-400',
    },
    {
      label: 'Margin Used',
      value: marginUsed != null
        ? `$${marginUsed.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        : '—',
      sub: equity && marginUsed != null
        ? `${((marginUsed / equity) * 100).toFixed(1)}% of equity`
        : undefined,
      color: 'text-slate-100',
      icon: DollarSign,
      iconColor: 'bg-amber-500/10 text-amber-400',
    },
    {
      label: 'Win Rate',
      value: winRate != null ? `${winRate.toFixed(1)}%` : '—',
      sub: 'All-time',
      color: winRate != null && winRate >= 50 ? 'text-green-400' : 'text-slate-100',
      icon: Activity,
      iconColor: 'bg-purple-500/10 text-purple-400',
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((s) => {
        const Icon = s.icon
        return (
          <div key={s.label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-400">{s.label}</span>
              <div className={`p-2 rounded-lg ${s.iconColor}`}>
                <Icon className="w-4 h-4" />
              </div>
            </div>
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            {s.sub && <div className="text-xs text-slate-500 mt-0.5">{s.sub}</div>}
          </div>
        )
      })}
    </div>
  )
}

// ─── Risk per trade calculator ───────────────────────────────────────────────

function RiskCalculatorPanel() {
  const account = useStore((s) => s.account)
  const prices = useStore((s) => s.prices)
  const activeSymbol = useStore((s) => s.activeSymbol)

  const [symbol, setSymbol] = useState(activeSymbol)
  const [riskPct, setRiskPct] = useState('1.0')
  const [entryPrice, setEntryPrice] = useState('')
  const [stopLoss, setStopLoss] = useState('')
  const [takeProfit, setTakeProfit] = useState('')

  const tick = prices[symbol]
  const equity = account?.equity ?? 0

  const entry = parseFloat(entryPrice) || tick?.mid || 0
  const sl = parseFloat(stopLoss) || 0
  const tp = parseFloat(takeProfit) || 0
  const risk = parseFloat(riskPct) / 100

  const slDistance = sl > 0 && entry > 0 ? Math.abs(entry - sl) : 0
  const tpDistance = tp > 0 && entry > 0 ? Math.abs(tp - entry) : 0
  const riskAmount = equity * risk
  const lotSize = slDistance > 0 ? riskAmount / (slDistance * 100000) : 0
  const riskReward = slDistance > 0 && tpDistance > 0 ? tpDistance / slDistance : 0
  const potentialProfit = lotSize * tpDistance * 100000

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center gap-2 mb-4">
        <Calculator className="w-4 h-4 text-amber-400" />
        <h3 className="font-semibold text-sm">Position Size Calculator</h3>
      </div>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Symbol</label>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Risk %</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="10"
              value={riskPct}
              onChange={(e) => setRiskPct(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Entry Price</label>
            <input
              type="number"
              step="0.00001"
              value={entryPrice}
              onChange={(e) => setEntryPrice(e.target.value)}
              placeholder={tick?.mid.toFixed(2) ?? ''}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-amber-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Stop Loss</label>
            <input
              type="number"
              step="0.00001"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-red-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Take Profit</label>
            <input
              type="number"
              step="0.00001"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-green-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Results */}
        {equity > 0 && (
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-800">
            <div className="bg-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Risk Amount</div>
              <div className="font-mono font-bold text-amber-400">
                ${riskAmount.toFixed(2)}
              </div>
            </div>
            <div className="bg-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Lot Size</div>
              <div className="font-mono font-bold text-slate-100">
                {lotSize > 0 ? lotSize.toFixed(2) : '—'}
              </div>
            </div>
            <div className="bg-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Risk / Reward</div>
              <div className={`font-mono font-bold ${
                riskReward >= 2 ? 'text-green-400' :
                riskReward >= 1 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {riskReward > 0 ? `1 : ${riskReward.toFixed(2)}` : '—'}
              </div>
            </div>
            <div className="bg-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Potential Profit</div>
              <div className="font-mono font-bold text-green-400">
                {potentialProfit > 0 ? `$${potentialProfit.toFixed(2)}` : '—'}
              </div>
            </div>
          </div>
        )}

        {equity > 0 && (
          <div className="space-y-2 pt-1">
            <RiskBar
              label="Risk of equity"
              value={parseFloat(riskPct)}
              max={5}
              unit="%"
              color="amber"
              warnAt={2}
              dangerAt={4}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Correlation heatmap ──────────────────────────────────────────────────────

function CorrelationMatrix() {
  const [data, setData] = useState<CorrelationData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/analysis/correlation', {
        headers: {
          Authorization: `Bearer ${useStore.getState().token ?? ''}`,
        },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (err: any) {
      setError(err.message ?? 'Failed to load correlation data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const getColor = (v: number) => {
    if (v >= 0.7)  return 'bg-green-500/70 text-green-100'
    if (v >= 0.3)  return 'bg-green-500/30 text-green-300'
    if (v >= -0.3) return 'bg-slate-700 text-slate-300'
    if (v >= -0.7) return 'bg-red-500/30 text-red-300'
    return 'bg-red-500/70 text-red-100'
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-amber-400" />
          <h3 className="font-semibold text-sm">Correlation Matrix</h3>
        </div>
        <button
          onClick={load}
          className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-amber-400 text-xs mb-3">
          <AlertTriangle className="w-3.5 h-3.5" />
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="py-8 text-center text-slate-500 text-sm">Loading correlation data…</div>
      )}

      {data && (
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead>
              <tr>
                <th className="w-16" />
                {data.symbols.map((s) => (
                  <th key={s} className="px-1 py-1 text-slate-400 font-mono font-medium text-center w-14">
                    {s.replace('USD', '')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.symbols.map((rowSym, ri) => (
                <tr key={rowSym}>
                  <td className="pr-2 py-0.5 text-slate-400 font-mono font-medium text-right">
                    {rowSym.replace('USD', '')}
                  </td>
                  {data.matrix[ri].map((val, ci) => (
                    <td key={ci} className="px-0.5 py-0.5">
                      <div className={`w-12 h-8 rounded flex items-center justify-center font-mono font-semibold ${getColor(val)}`}>
                        {val.toFixed(2)}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded bg-green-500/70" />
              Strong positive (≥0.7)
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded bg-slate-700" />
              Neutral
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded bg-red-500/70" />
              Strong negative (≤-0.7)
            </div>
          </div>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="py-6 text-center text-slate-600 text-xs">
          Correlation data requires trade history
        </div>
      )}
    </div>
  )
}

// ─── Closed trades table ──────────────────────────────────────────────────────

const PAGE_SIZE = 15

function ClosedTradesTable() {
  const [trades, setTrades] = useState<ClosedTrade[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [total, setTotal] = useState(0)
  const [filterSymbol, setFilterSymbol] = useState('')

  const load = useCallback(async (p: number, sym: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await tradingApi.trades({
        symbol: sym || undefined,
        limit: PAGE_SIZE,
        offset: p * PAGE_SIZE,
      })
      const raw = (res.data as any)?.trades ?? res.data ?? []
      const arr: ClosedTrade[] = Array.isArray(raw) ? raw : []
      setTrades(arr)
      setTotal((res.data as any)?.total ?? arr.length)
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to load trade history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(page, filterSymbol)
  }, [load, page, filterSymbol])

  const formatDuration = (mins: number | null | undefined) => {
    if (mins == null) return '—'
    if (mins < 60) return `${mins}m`
    if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`
    return `${Math.floor(mins / 1440)}d`
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className="font-semibold text-sm">Trade History</h3>
        <div className="flex items-center gap-2">
          <input
            value={filterSymbol}
            onChange={(e) => { setFilterSymbol(e.target.value.toUpperCase()); setPage(0) }}
            placeholder="Filter symbol…"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-amber-500 focus:outline-none w-32"
          />
          <button
            onClick={() => load(page, filterSymbol)}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 text-red-400 text-sm border-b border-slate-800">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="px-4 py-2.5 text-left">Time</th>
              <th className="px-4 py-2.5 text-left">Symbol</th>
              <th className="px-4 py-2.5 text-left">Side</th>
              <th className="px-4 py-2.5 text-left">Qty</th>
              <th className="px-4 py-2.5 text-left">Entry</th>
              <th className="px-4 py-2.5 text-left">Exit</th>
              <th className="px-4 py-2.5 text-left">Duration</th>
              <th className="px-4 py-2.5 text-right">P&amp;L</th>
              <th className="px-4 py-2.5 text-right">P&amp;L %</th>
              <th className="px-4 py-2.5 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="text-sm divide-y divide-slate-800">
            {trades.length === 0 && !loading ? (
              <tr>
                <td colSpan={10} className="px-4 py-10 text-center text-slate-500 text-sm">
                  No trade history yet
                </td>
              </tr>
            ) : (
              trades.map((t) => (
                <tr key={t.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-2.5 text-xs text-slate-400">
                    <div>{new Date(t.opened_at).toLocaleDateString()}</div>
                    <div className="text-slate-600">
                      {new Date(t.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs font-semibold">{t.symbol}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      t.side === 'buy' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                    }`}>
                      {t.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.quantity}</td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.entry_price.toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-xs font-mono">{t.exit_price?.toFixed(2) ?? '—'}</td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDuration(t.duration_minutes)}
                    </div>
                  </td>
                  <td className={`px-4 py-2.5 text-xs font-mono font-semibold text-right ${
                    t.pnl == null ? 'text-slate-500' :
                    t.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}` : '—'}
                  </td>
                  <td className={`px-4 py-2.5 text-xs font-mono text-right ${
                    t.pnl_pct == null ? 'text-slate-500' :
                    t.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {t.pnl_pct != null ? `${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      t.status === 'open'
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'bg-slate-700 text-slate-300'
                    }`}>
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800">
          <span className="text-xs text-slate-500">
            Page {page + 1} of {totalPages} · {total} trades
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1.5 rounded text-slate-400 hover:bg-slate-800 disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1.5 rounded text-slate-400 hover:bg-slate-800 disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}



// ─── Main page ────────────────────────────────────────────────────────────────

export default function Positioning() {
  const positions = useStore((s) => s.positions)
  const setPositions = useStore((s) => s.setPositions)
  const [activeTab, setActiveTab] = useState<'open' | 'closed' | 'calc' | 'corr'>('open')

  const loadPositions = useCallback(async () => {
    try {
      const res = await tradingApi.positions()
      const raw = Array.isArray(res.data) ? res.data : []
      setPositions(
        raw.map((p: any) => ({
          id: p.id,
          symbol: p.symbol,
          side: p.side === 'buy' || p.side === 'long' ? 'long' : 'short',
          size: p.size ?? p.quantity ?? 0,
          entry_price: p.entry_price ?? 0,
          current_price: p.current_price ?? p.entry_price ?? 0,
          unrealized_pnl: p.unrealized_pnl ?? 0,
          realized_pnl: p.realized_pnl ?? 0,
          stop_loss: p.stop_loss ?? null,
          take_profit: p.take_profit ?? null,
          margin_used: p.margin_used ?? null,
          leverage: p.leverage ?? null,
          opened_at: p.opened_at ?? new Date().toISOString(),
          swap: p.swap ?? null,
          commission: p.commission ?? null,
        })),
      )
    } catch {
      // WS keeps positions updated
    }
  }, [setPositions])

  useEffect(() => {
    loadPositions()
    const id = setInterval(loadPositions, 10_000)
    return () => clearInterval(id)
  }, [loadPositions])

  const tabs = [
    { id: 'open',   label: `Open (${positions.length})` },
    { id: 'closed', label: 'History' },
    { id: 'calc',   label: 'Risk Calc' },
    { id: 'corr',   label: 'Correlation' },
  ] as const

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Manage open positions, review history, and size trades
          </p>
        </div>
        <button
          onClick={loadPositions}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300 hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <SummaryBar />

      <div className="flex gap-1 bg-slate-900 border border-slate-800 rounded-xl p-1 w-fit">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === t.id
                ? 'bg-amber-500/20 text-amber-400'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'open' && (
        <div className="space-y-3">
          {positions.length === 0 ? (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
              <BarChart2 className="w-10 h-10 text-slate-700 mx-auto mb-3" />
              <p className="text-slate-400">No open positions</p>
              <p className="text-sm text-slate-600 mt-1">
                Go to Trading to place your first order
              </p>
            </div>
          ) : (
            positions.map((pos) => (
              <PositionCard key={pos.id} position={pos} compact={false} />
            ))
          )}
        </div>
      )}

      {activeTab === 'closed' && <ClosedTradesTable />}

      {activeTab === 'calc' && (
        <div className="max-w-xl">
          <RiskCalculatorPanel />
        </div>
      )}

      {activeTab === 'corr' && <CorrelationMatrix />}
    </div>
  )
}
