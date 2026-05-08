import { useEffect, useState, useCallback } from 'react'
import { Trophy, Medal, TrendingUp, Users, AlertTriangle, RefreshCw, Loader2 } from 'lucide-react'
import { useStore } from '../store/useStore'
import { extractApiError } from '../lib/utils'

interface LeaderboardEntry {
  id: string
  rank: number
  name: string
  return_3m: number
  return?: number
  sharpe: number
  followers: number
  win_rate: number
  trades: number
  prize?: string
}

type Period = 'monthly' | 'quarterly' | 'all'
type FetchState = 'idle' | 'loading' | 'ok' | 'empty' | 'error'

export function Leaderboard() {
  const token = useStore((s) => s.token)
  const [period, setPeriod] = useState<Period>('monthly')
  const [rankings, setRankings] = useState<LeaderboardEntry[]>([])
  const [fetchState, setFetchState] = useState<FetchState>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const fetchLeaderboard = useCallback(async (p: Period) => {
    setFetchState('loading')
    setErrorMsg('')
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/social/leaderboard?period=${p}&limit=20`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: LeaderboardEntry[] = await res.json()
      setRankings(data)
      setFetchState(data.length === 0 ? 'empty' : 'ok')
    } catch (err: unknown) {
      setErrorMsg(extractApiError(err, 'Unknown error'))
      setFetchState('error')
    }
  }, [token])

  useEffect(() => {
    fetchLeaderboard(period)
  }, [period, fetchLeaderboard])

  const top3 = rankings.slice(0, 3)
  // Podium order: 2nd, 1st, 3rd
  const podium = [top3[1], top3[0], top3[2]].filter(Boolean)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Global Leaderboard</h2>
        <div className="flex gap-2">
          {(['monthly', 'quarterly', 'all'] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                period === p
                  ? 'bg-amber-500/10 text-amber-400'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {p === 'all' ? 'All Time' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Loading skeleton */}
      {fetchState === 'loading' && (
        <div className="flex items-center justify-center py-16 gap-3 text-slate-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading leaderboard…</span>
        </div>
      )}

      {/* Error state */}
      {fetchState === 'error' && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Could not load leaderboard: {errorMsg}</span>
          <button
            onClick={() => fetchLeaderboard(period)}
            className="ml-auto flex items-center gap-1 hover:text-red-300 transition-colors"
          >
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {fetchState === 'empty' && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-slate-500">
          <Trophy className="w-10 h-10 opacity-30" />
          <p className="font-medium">No traders on the leaderboard yet</p>
          <p className="text-sm text-slate-600">
            Traders appear here after opting into the public feed and completing trades.
          </p>
        </div>
      )}

      {/* Podium — top 3 */}
      {fetchState === 'ok' && podium.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-8">
          {podium.map((trader, idx) => {
            // idx 0 = 2nd place, idx 1 = 1st place, idx 2 = 3rd place
            const isFirst  = trader.rank === 1
            const isSecond = trader.rank === 2
            const ret = trader.return ?? trader.return_3m
            return (
              <div
                key={trader.id}
                className={`relative bg-slate-900 rounded-lg border p-6 text-center ${
                  isFirst  ? 'border-yellow-500/50 order-2' :
                  isSecond ? 'border-slate-400/50 order-1' :
                             'border-amber-700/50 order-3'
                }`}
              >
                <div className={`absolute -top-4 left-1/2 -translate-x-1/2 w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm ${
                  isFirst  ? 'bg-yellow-500 text-yellow-950' :
                  isSecond ? 'bg-slate-400 text-slate-950' :
                             'bg-amber-700 text-amber-100'
                }`}>
                  {trader.rank}
                </div>
                <h3 className="text-lg font-bold mt-4 truncate">{trader.name}</h3>
                <div className={`text-2xl font-bold my-2 ${ret >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                </div>
                <div className="text-xs text-slate-500 flex items-center justify-center gap-1">
                  <Users className="w-3 h-3" />
                  {trader.followers.toLocaleString()} followers
                </div>
                {trader.prize && (
                  <div className="text-xs text-amber-400 mt-1">{trader.prize}</div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Full table */}
      {fetchState === 'ok' && rankings.length > 0 && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-800/50">
              <tr>
                <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Rank</th>
                <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Trader</th>
                <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Return</th>
                <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Sharpe</th>
                <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Win Rate</th>
                <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">
                  <TrendingUp className="w-4 h-4 inline" /> Trades
                </th>
                <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Followers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rankings.map((trader) => {
                const ret = trader.return ?? trader.return_3m
                return (
                  <tr key={trader.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-6 py-4">
                      {trader.rank <= 3 ? (
                        <Medal className={`w-5 h-5 ${
                          trader.rank === 1 ? 'text-yellow-500' :
                          trader.rank === 2 ? 'text-slate-400' :
                                             'text-amber-700'
                        }`} />
                      ) : (
                        <span className="text-slate-500">#{trader.rank}</span>
                      )}
                    </td>
                    <td className="px-6 py-4 font-medium">{trader.name}</td>
                    <td className={`px-6 py-4 text-right font-medium ${ret >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 text-right">{trader.sharpe.toFixed(2)}</td>
                    <td className="px-6 py-4 text-right">{trader.win_rate.toFixed(1)}%</td>
                    <td className="px-6 py-4 text-right">{trader.trades.toLocaleString()}</td>
                    <td className="px-6 py-4 text-right text-slate-400">
                      {trader.followers.toLocaleString()}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
