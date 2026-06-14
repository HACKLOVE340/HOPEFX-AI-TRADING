/**
 * CopyTrading — Advanced Social Copy Trading Platform
 *
 * Exposes the full social/advanced_copy_trading.py backend:
 * - Master trader leaderboard with comprehensive metrics
 * - Copy configuration (allocation, risk scaling, pair filtering, max DD stop)
 * - Active copy relationships with pause/resume/stop
 * - Real-time mirrored positions with P&L tracking
 * - Revenue sharing and fee transparency
 *
 * Backend: /api/leaderboard, /api/social/copy/*, /api/copy-trading/*
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Users, TrendingUp, Star, DollarSign, RefreshCw,
  Copy, Play, Pause, X, Shield, CheckCircle,
  Award, BarChart2, Clock, Target, Sliders,
} from 'lucide-react'
import { api } from '../hooks/useApi'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Leader {
  id: string
  name: string
  return_3m: number
  sharpe: number
  max_dd: number
  followers: number
  aum: number
  fee: number
  win_rate: number
  trades_per_week: number
  avg_trade_duration: string
  monthly_return?: number
  risk_score?: number
  preferred_pairs?: string[]
  verified?: boolean
  rank?: number
  total_return?: number
  trading_days?: number
}

interface CopyRelation {
  id: string
  master_id: string
  master_name: string
  status: 'active' | 'paused' | 'stopped'
  allocation_usd: number
  risk_multiplier: number
  started_at: string
  total_pnl: number
  trades_copied: number
  open_positions: number
  max_dd_stop: number
}

interface MirroredPosition {
  id: string
  master_name: string
  symbol: string
  direction: 'long' | 'short'
  entry_price: number
  current_price: number
  pnl: number
  pnl_pct: number
  opened_at: string
  size: number
}

type Tab = 'discover' | 'active' | 'positions'

// ── Component ─────────────────────────────────────────────────────────────────
export function CopyTrading() {
  const [leaders, setLeaders] = useState<Leader[]>([])
  const [relations, setRelations] = useState<CopyRelation[]>([])
  const [positions, setPositions] = useState<MirroredPosition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('discover')
  const [selectedLeader, setSelectedLeader] = useState<Leader | null>(null)
  const [allocation, setAllocation] = useState(10000)
  const [riskMultiplier, setRiskMultiplier] = useState(1.0)
  const [maxDdStop, setMaxDdStop] = useState(15)
  const [copying, setCopying] = useState(false)
  const [copyMsg, setCopyMsg] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [leadersRes, relationsRes, positionsRes] = await Promise.all([
        api.get('/api/leaderboard'),
        fetch('/api/copy-trading/my-copies', { headers }).then(r => r.ok ? r.json() : { copies: [] }).catch(() => ({ copies: [] })),
        fetch('/api/copy-trading/mirrored-positions', { headers }).then(r => r.ok ? r.json() : { positions: [] }).catch(() => ({ positions: [] })),
      ])
      const data = leadersRes.data.leaders ?? leadersRes.data ?? []
      setLeaders(data)
      setRelations(relationsRes.copies || [])
      setPositions(positionsRes.positions || [])
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load copy trading data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const startCopying = async () => {
    if (!selectedLeader) return
    setCopying(true)
    setCopyMsg(null)
    try {
      await api.post(`/api/social/copy/${selectedLeader.id}`, {
        allocation_usd: allocation,
        risk_multiplier: riskMultiplier,
        max_dd_stop: maxDdStop,
      })
      setCopyMsg('Copy trading started successfully.')
      setSelectedLeader(null)
      await fetchAll()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCopyMsg(detail ?? 'Failed to start copy trading.')
    } finally {
      setCopying(false)
    }
  }

  const pauseCopy = async (relationId: string) => {
    try {
      await fetch(`/api/copy-trading/copies/${relationId}/pause`, { method: 'POST', headers })
      setRelations(prev => prev.map(r => r.id === relationId ? { ...r, status: 'paused' } : r))
    } catch (err) { console.error('Pause failed:', err) }
  }

  const resumeCopy = async (relationId: string) => {
    try {
      await fetch(`/api/copy-trading/copies/${relationId}/resume`, { method: 'POST', headers })
      setRelations(prev => prev.map(r => r.id === relationId ? { ...r, status: 'active' } : r))
    } catch (err) { console.error('Resume failed:', err) }
  }

  const stopCopy = async (relationId: string) => {
    try {
      await fetch(`/api/copy-trading/copies/${relationId}/stop`, { method: 'POST', headers })
      setRelations(prev => prev.filter(r => r.id !== relationId))
    } catch (err) { console.error('Stop failed:', err) }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Copy Trading</h1>
          <p className="text-sm text-slate-400 mt-1">Follow top traders and mirror their strategies automatically</p>
        </div>
        <button onClick={fetchAll} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Alerts */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}
      {copyMsg && (
        <div className={`rounded-xl p-4 text-sm border ${copyMsg.includes('success') ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>{copyMsg}</div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Active Copies</div>
          <div className="text-2xl font-bold text-slate-200">{relations.filter(r => r.status === 'active').length}</div>
        </div>
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Total P&L</div>
          <div className={`text-2xl font-bold ${relations.reduce((s, r) => s + r.total_pnl, 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${relations.reduce((s, r) => s + r.total_pnl, 0).toFixed(2)}
          </div>
        </div>
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Open Positions</div>
          <div className="text-2xl font-bold text-slate-200">{positions.length}</div>
        </div>
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Trades Copied</div>
          <div className="text-2xl font-bold text-slate-200">{relations.reduce((s, r) => s + r.trades_copied, 0)}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-lg p-1 border border-slate-800 w-fit">
        {([
          { id: 'discover' as Tab, label: 'Discover Masters', icon: Users },
          { id: 'active' as Tab, label: 'My Copies', icon: Copy },
          { id: 'positions' as Tab, label: 'Mirrored Positions', icon: TrendingUp },
        ]).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t.id ? 'bg-amber-500/10 text-amber-400' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {/* Discover Tab */}
      {tab === 'discover' && (
        <>
          {loading && <div className="text-center py-12 text-slate-500">Loading leaderboard...</div>}
          {!loading && leaders.length === 0 && !error && (
            <div className="text-center py-12 text-slate-500">No traders on the leaderboard yet.</div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {leaders.map((leader, idx) => (
              <div
                key={leader.id}
                className={`bg-slate-900 rounded-xl border p-5 cursor-pointer transition-all ${
                  selectedLeader?.id === leader.id
                    ? 'border-amber-500 ring-1 ring-amber-500'
                    : 'border-slate-800 hover:border-slate-700'
                }`}
                onClick={() => setSelectedLeader(leader)}
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center text-amber-400 font-bold text-sm">
                      #{leader.rank || idx + 1}
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-semibold text-slate-200">{leader.name}</span>
                        {leader.verified && <CheckCircle className="w-3.5 h-3.5 text-blue-400" />}
                      </div>
                      <div className="text-xs text-slate-500">
                        {leader.trading_days ? `${leader.trading_days} days` : `${leader.trades_per_week} trades/wk`}
                      </div>
                    </div>
                  </div>
                  {leader.risk_score !== undefined && <RiskBadge score={leader.risk_score} />}
                </div>

                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="bg-slate-800 rounded-lg p-2.5">
                    <div className="text-xs text-slate-500">3M Return</div>
                    <div className="text-lg font-bold text-green-400">+{leader.return_3m}%</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-2.5">
                    <div className="text-xs text-slate-500">Win Rate</div>
                    <div className="text-lg font-bold text-slate-200">{leader.win_rate}%</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-2.5">
                    <div className="text-xs text-slate-500">Max DD</div>
                    <div className="text-sm font-bold text-red-400">{leader.max_dd}%</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-2.5">
                    <div className="text-xs text-slate-500">Sharpe</div>
                    <div className="text-sm font-bold text-slate-200">{leader.sharpe}</div>
                  </div>
                </div>

                {leader.preferred_pairs && leader.preferred_pairs.length > 0 && (
                  <div className="flex gap-1 mb-3 flex-wrap">
                    {leader.preferred_pairs.slice(0, 4).map(p => (
                      <span key={p} className="text-xs px-2 py-0.5 bg-slate-800 rounded text-slate-400">{p}</span>
                    ))}
                  </div>
                )}

                <div className="flex items-center justify-between pt-3 border-t border-slate-800">
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Users className="w-3.5 h-3.5" />
                    <span>{leader.followers.toLocaleString()} followers</span>
                  </div>
                  <div className="text-xs text-slate-500">
                    AUM: ${(leader.aum / 1_000_000).toFixed(2)}M • Fee: {leader.fee}%
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Copy Configuration Panel */}
          {selectedLeader && (
            <div className="bg-slate-900 rounded-xl border border-amber-500/30 p-6">
              <h3 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
                <Sliders className="w-5 h-5 text-amber-400" />
                Copy Configuration — {selectedLeader.name}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                <div>
                  <label className="block text-xs text-slate-500 mb-2">Allocation (USD)</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range" min={1000} max={100000} step={1000}
                      value={allocation}
                      onChange={e => setAllocation(Number(e.target.value))}
                      className="flex-1"
                    />
                    <div className="relative w-28">
                      <DollarSign className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        type="number"
                        value={allocation}
                        onChange={e => setAllocation(Number(e.target.value))}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-7 pr-2 py-2 text-sm text-slate-200"
                      />
                    </div>
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-2">Risk Multiplier</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range" min={0.1} max={3} step={0.1}
                      value={riskMultiplier}
                      onChange={e => setRiskMultiplier(Number(e.target.value))}
                      className="flex-1"
                    />
                    <span className="text-sm text-slate-200 w-12 text-center">{riskMultiplier.toFixed(1)}x</span>
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-2">Max Drawdown Stop (%)</label>
                  <select
                    value={maxDdStop}
                    onChange={e => setMaxDdStop(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
                  >
                    <option value={5}>5%</option>
                    <option value={10}>10%</option>
                    <option value={15}>15%</option>
                    <option value={20}>20%</option>
                    <option value={25}>25%</option>
                  </select>
                </div>
              </div>
              <div className="flex items-center justify-between mb-4 text-sm text-slate-400">
                <span>Estimated Monthly Fee: <span className="text-slate-200">${(allocation * (selectedLeader.fee / 100) / 12).toFixed(2)}</span></span>
                <span>Risk-adjusted allocation: <span className="text-slate-200">${(allocation * riskMultiplier).toFixed(0)}</span></span>
              </div>
              <div className="flex gap-3">
                <button onClick={startCopying} disabled={copying}
                  className="flex-1 py-3 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-900 font-bold rounded-lg transition-colors">
                  {copying ? 'Starting...' : 'Start Copy Trading'}
                </button>
                <button
                  className="px-6 py-3 border border-slate-700 rounded-lg hover:bg-slate-800 text-slate-300 transition-colors"
                  onClick={() => setSelectedLeader(null)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Active Copies Tab */}
      {tab === 'active' && (
        <div className="space-y-3">
          {relations.length === 0 ? (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
              <Copy className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-300 mb-2">No Active Copies</h3>
              <p className="text-sm text-slate-500">Discover master traders and start copying their strategies</p>
            </div>
          ) : (
            relations.map(rel => (
              <div key={rel.id} className="bg-slate-900 rounded-xl border border-slate-800 p-5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${
                      rel.status === 'active' ? 'bg-green-500/10 text-green-400' :
                      rel.status === 'paused' ? 'bg-amber-500/10 text-amber-400' :
                      'bg-slate-700 text-slate-400'
                    }`}>
                      {rel.master_name[0]}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-200">{rel.master_name}</span>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          rel.status === 'active' ? 'bg-green-500/10 text-green-400' :
                          rel.status === 'paused' ? 'bg-amber-500/10 text-amber-400' :
                          'bg-slate-500/10 text-slate-400'
                        }`}>{rel.status}</span>
                      </div>
                      <div className="text-xs text-slate-500">
                        Since {rel.started_at} • {rel.trades_copied} trades copied • {rel.open_positions} open
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <div className={`text-lg font-bold ${rel.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {rel.total_pnl >= 0 ? '+' : ''}${rel.total_pnl.toFixed(2)}
                      </div>
                      <div className="text-xs text-slate-500">
                        ${rel.allocation_usd.toLocaleString()} • {rel.risk_multiplier}x risk • {rel.max_dd_stop}% DD stop
                      </div>
                    </div>
                    <div className="flex gap-1">
                      {rel.status === 'active' ? (
                        <button onClick={() => pauseCopy(rel.id)} className="p-2 bg-amber-500/10 text-amber-400 rounded-lg hover:bg-amber-500/20 transition-colors" title="Pause">
                          <Pause className="w-4 h-4" />
                        </button>
                      ) : rel.status === 'paused' ? (
                        <button onClick={() => resumeCopy(rel.id)} className="p-2 bg-green-500/10 text-green-400 rounded-lg hover:bg-green-500/20 transition-colors" title="Resume">
                          <Play className="w-4 h-4" />
                        </button>
                      ) : null}
                      <button onClick={() => stopCopy(rel.id)} className="p-2 bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 transition-colors" title="Stop">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Mirrored Positions Tab */}
      {tab === 'positions' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          {positions.length === 0 ? (
            <div className="p-12 text-center">
              <TrendingUp className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-300 mb-2">No Mirrored Positions</h3>
              <p className="text-sm text-slate-500">Positions will appear here when your copied traders open trades</p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-slate-800">
                  <th className="px-5 py-3 text-left">Master</th>
                  <th className="px-5 py-3 text-left">Symbol</th>
                  <th className="px-5 py-3 text-left">Direction</th>
                  <th className="px-5 py-3 text-left">Entry</th>
                  <th className="px-5 py-3 text-left">Current</th>
                  <th className="px-5 py-3 text-left">P&L</th>
                  <th className="px-5 py-3 text-left">Size</th>
                  <th className="px-5 py-3 text-left">Opened</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {positions.map(pos => (
                  <tr key={pos.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="px-5 py-3 text-slate-200 font-medium">{pos.master_name}</td>
                    <td className="px-5 py-3 text-slate-200">{pos.symbol}</td>
                    <td className="px-5 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        pos.direction === 'long' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                      }`}>{pos.direction}</span>
                    </td>
                    <td className="px-5 py-3 text-slate-300">{pos.entry_price.toFixed(5)}</td>
                    <td className="px-5 py-3 text-slate-300">{pos.current_price.toFixed(5)}</td>
                    <td className="px-5 py-3">
                      <span className={pos.pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {pos.pnl >= 0 ? '+' : ''}${pos.pnl.toFixed(2)} ({pos.pnl_pct >= 0 ? '+' : ''}{pos.pnl_pct.toFixed(2)}%)
                      </span>
                    </td>
                    <td className="px-5 py-3 text-slate-300">{pos.size}</td>
                    <td className="px-5 py-3 text-slate-500">{pos.opened_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function RiskBadge({ score }: { score: number }) {
  const color = score <= 3 ? 'bg-green-500/10 text-green-400 border-green-500/30' :
    score <= 6 ? 'bg-amber-500/10 text-amber-400 border-amber-500/30' :
    'bg-red-500/10 text-red-400 border-red-500/30'
  return <span className={`text-xs px-2 py-0.5 rounded border ${color}`}>Risk {score}/10</span>
}
