/**
 * PnLDashboard
 *
 * Live P&L dashboard — auditable trade log, equity curve, Sharpe, drawdown.
 * All data sourced from real engine fills via /api/pnl/* endpoints.
 * No synthetic or mock data.
 *
 * Routes consumed:
 *   GET /api/pnl/summary         — headline stats
 *   GET /api/pnl/equity-curve    — equity time series (rendered by EquityChart)
 *   GET /api/pnl/drawdown-curve  — drawdown % time series (rendered by DrawdownChart)
 *   GET /api/pnl/trade-log       — auditable fill-level log
 *   GET /api/pnl/open-positions  — current open positions
 */

import { useCallback, useEffect, useState } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Shield,
  Clock,
  RefreshCw,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { EquityChart } from '../components/EquityChart'
import { DrawdownChart } from '../components/DrawdownChart'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PnLSummary {
  equity: number
  starting_equity: number
  total_return_pct: number
  total_fills: number
  open_positions: number
  win_rate: number | null
  sharpe_ratio: number | null
  max_drawdown_pct: number
  current_drawdown_pct: number
  avg_slippage_bps: number
  avg_latency_ms: number
  last_fill_at: string | null
  note: string
}

interface FillEntry {
  fill_id: string
  order_id: string
  signal_id: string
  symbol: string
  direction: string
  quantity: number
  fill_price: number
  expected_price: number
  slippage_bps: number
  broker: string
  latency_ms: number
  filled_at: string
  lineage_id: string
}

interface OpenPosition {
  symbol: string
  direction: string
  quantity: number
  entry_price: number
  current_price: number | null
  unrealised_pnl: number | null
  stop_loss: number | null
  take_profit: number | null
  opened_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number, decimals = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

const fmtPct = (n: number | null) =>
  n === null ? '—' : `${n >= 0 ? '+' : ''}${fmt(n, 2)}%`

const fmtUSD = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

const PAGE_SIZE = 25

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color = 'amber',
  warn = false,
}: {
  label: string
  value: string
  sub?: string
  icon: React.ElementType
  color?: 'amber' | 'green' | 'red' | 'blue' | 'purple'
  warn?: boolean
}) {
  const colors: Record<string, string> = {
    amber: 'bg-amber-500/10 text-amber-400',
    green: 'bg-emerald-500/10 text-emerald-400',
    red: 'bg-red-500/10 text-red-400',
    blue: 'bg-blue-500/10 text-blue-400',
    purple: 'bg-purple-500/10 text-purple-400',
  }
  return (
    <div className={`bg-slate-900 rounded-lg border p-5 ${warn ? 'border-amber-500/40' : 'border-slate-800'}`}>
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

// ── Main component ────────────────────────────────────────────────────────────

export function PnLDashboard() {
  const [summary, setSummary] = useState<PnLSummary | null>(null)
  const [fills, setFills] = useState<FillEntry[]>([])
  const [positions, setPositions] = useState<OpenPosition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [totalFills, setTotalFills] = useState(0)

  const load = useCallback(async (pageNum = 0) => {
    setLoading(true)
    setError(null)
    try {
      const [summaryRes, fillsRes, posRes] = await Promise.all([
        fetch('/api/pnl/summary'),
        fetch(`/api/pnl/trade-log?limit=${PAGE_SIZE}&offset=${pageNum * PAGE_SIZE}`),
        fetch('/api/pnl/open-positions'),
      ])

      if (!summaryRes.ok) throw new Error(`Summary: HTTP ${summaryRes.status}`)
      if (!fillsRes.ok) throw new Error(`Trade log: HTTP ${fillsRes.status}`)
      if (!posRes.ok) throw new Error(`Positions: HTTP ${posRes.status}`)

      const [s, f, p] = await Promise.all([
        summaryRes.json() as Promise<PnLSummary>,
        fillsRes.json() as Promise<FillEntry[]>,
        posRes.json() as Promise<OpenPosition[]>,
      ])

      setSummary(s)
      setFills(f)
      setPositions(p)
      setTotalFills(s.total_fills)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load P&L data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(0)
    // Auto-refresh every 30 s
    const interval = setInterval(() => load(page), 30_000)
    return () => clearInterval(interval)
  }, [load, page])

  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    load(newPage)
  }

  const totalPages = Math.ceil(totalFills / PAGE_SIZE)

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Live P&amp;L Dashboard</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real fills from the live engine — no synthetic data
          </p>
        </div>
        <button
          onClick={() => load(page)}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {lastUpdated ? `Updated ${lastUpdated}` : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {summary?.note && (
        <div className="flex items-center gap-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-400 text-xs">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          {summary.note}
        </div>
      )}

      {/* Headline stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Equity"
          value={summary ? fmtUSD(summary.equity) : '—'}
          sub={summary ? `Started ${fmtUSD(summary.starting_equity)}` : undefined}
          icon={TrendingUp}
          color={summary && summary.total_return_pct >= 0 ? 'green' : 'red'}
        />
        <StatCard
          label="Total Return"
          value={summary ? fmtPct(summary.total_return_pct) : '—'}
          sub={summary ? `${summary.total_fills} fills` : undefined}
          icon={Activity}
          color={summary && summary.total_return_pct >= 0 ? 'green' : 'red'}
        />
        <StatCard
          label="Sharpe Ratio"
          value={summary?.sharpe_ratio != null ? fmt(summary.sharpe_ratio, 3) : '—'}
          sub={summary?.sharpe_ratio == null ? `Need ${30 - (summary?.total_fills ?? 0)} more fills` : 'Annualised'}
          icon={TrendingUp}
          color={
            summary?.sharpe_ratio == null ? 'amber'
            : summary.sharpe_ratio >= 1.5 ? 'green'
            : summary.sharpe_ratio >= 0.5 ? 'amber'
            : 'red'
          }
        />
        <StatCard
          label="Max Drawdown"
          value={summary ? `${fmt(summary.max_drawdown_pct, 2)}%` : '—'}
          sub={summary ? `Current: ${fmt(summary.current_drawdown_pct, 2)}%` : undefined}
          icon={TrendingDown}
          color={summary && summary.max_drawdown_pct > 10 ? 'red' : 'amber'}
          warn={summary != null && summary.max_drawdown_pct > 10}
        />
        <StatCard
          label="Win Rate"
          value={summary?.win_rate != null ? `${fmt(summary.win_rate, 1)}%` : '—'}
          sub={summary?.win_rate == null ? 'Need 30+ fills' : `${summary.total_fills} fills`}
          icon={Shield}
          color={summary?.win_rate != null && summary.win_rate >= 55 ? 'green' : 'amber'}
        />
        <StatCard
          label="Open Positions"
          value={summary ? String(summary.open_positions) : '—'}
          sub="Live"
          icon={Activity}
          color="blue"
        />
        <StatCard
          label="Avg Slippage"
          value={summary ? `${fmt(summary.avg_slippage_bps, 2)} bps` : '—'}
          sub="Per fill"
          icon={TrendingDown}
          color={summary && summary.avg_slippage_bps > 5 ? 'red' : 'green'}
        />
        <StatCard
          label="Avg Latency"
          value={summary ? `${fmt(summary.avg_latency_ms, 1)} ms` : '—'}
          sub="Order → fill"
          icon={Clock}
          color="purple"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-slate-200">Equity Curve</h3>
            <span className="text-xs text-slate-500">Account currency</span>
          </div>
          <EquityChart />
        </div>
        <DrawdownChart />
      </div>

      {/* Open positions */}
      {positions.length > 0 && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800">
            <h3 className="font-semibold text-slate-200">Open Positions ({positions.length})</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase border-b border-slate-800">
                  {['Symbol', 'Direction', 'Qty', 'Entry', 'Current', 'Unrealised P&L', 'SL', 'TP', 'Opened'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => (
                  <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-mono text-amber-400">{pos.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        pos.direction.toLowerCase().includes('long') || pos.direction.toLowerCase() === 'buy'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : 'bg-red-500/20 text-red-400'
                      }`}>
                        {pos.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono">{fmt(pos.quantity, 4)}</td>
                    <td className="px-4 py-3 font-mono">{fmt(pos.entry_price, 4)}</td>
                    <td className="px-4 py-3 font-mono">{pos.current_price != null ? fmt(pos.current_price, 4) : '—'}</td>
                    <td className={`px-4 py-3 font-mono font-semibold ${
                      pos.unrealised_pnl == null ? 'text-slate-500'
                      : pos.unrealised_pnl >= 0 ? 'text-emerald-400'
                      : 'text-red-400'
                    }`}>
                      {pos.unrealised_pnl != null ? fmtUSD(pos.unrealised_pnl) : '—'}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-400">{pos.stop_loss != null ? fmt(pos.stop_loss, 4) : '—'}</td>
                    <td className="px-4 py-3 font-mono text-slate-400">{pos.take_profit != null ? fmt(pos.take_profit, 4) : '—'}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{pos.opened_at ? new Date(pos.opened_at).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Auditable trade log */}
      <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-slate-200">Auditable Trade Log</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Every fill linked to lineage store — fill_id → signal → model version
            </p>
          </div>
          <span className="text-xs text-slate-500">{totalFills} total fills</span>
        </div>

        {fills.length === 0 ? (
          <div className="px-5 py-12 text-center text-slate-500 text-sm">
            No fills yet. The trade log will populate after the first executed order.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-slate-800">
                    {['Time', 'Symbol', 'Dir', 'Qty', 'Fill Price', 'Expected', 'Slippage', 'Latency', 'Broker', 'Fill ID'].map((h) => (
                      <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {fills.map((f) => (
                    <tr key={f.fill_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                        {new Date(f.filled_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 font-mono text-amber-400">{f.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          f.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {f.direction.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono">{fmt(f.quantity, 4)}</td>
                      <td className="px-4 py-3 font-mono">{fmt(f.fill_price, 4)}</td>
                      <td className="px-4 py-3 font-mono text-slate-400">{fmt(f.expected_price, 4)}</td>
                      <td className={`px-4 py-3 font-mono text-xs ${
                        Math.abs(f.slippage_bps) > 5 ? 'text-amber-400' : 'text-slate-400'
                      }`}>
                        {fmt(f.slippage_bps, 2)} bps
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {fmt(f.latency_ms, 1)} ms
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{f.broker}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-600 truncate max-w-[120px]" title={f.fill_id}>
                        {f.fill_id.slice(0, 12)}…
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-5 py-3 border-t border-slate-800 flex items-center justify-between text-sm text-slate-400">
                <span>Page {page + 1} of {totalPages}</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => handlePageChange(page - 1)}
                    disabled={page === 0}
                    className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-30"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handlePageChange(page + 1)}
                    disabled={page >= totalPages - 1}
                    className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-30"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
