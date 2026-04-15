import { useState, useEffect } from 'react'
import { Users, TrendingUp, Star, DollarSign, RefreshCw } from 'lucide-react'
import axios from 'axios'

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
}

export function CopyTrading() {
  const [leaders, setLeaders] = useState<Leader[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedLeader, setSelectedLeader] = useState<string | null>(null)
  const [allocation, setAllocation] = useState(10000)
  const [copying, setCopying] = useState(false)
  const [copyMsg, setCopyMsg] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get('/api/leaderboard')
      const data = res.data.leaders ?? res.data ?? []
      setLeaders(data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load leaderboard.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const startCopying = async () => {
    if (!selectedLeader) return
    setCopying(true)
    setCopyMsg(null)
    try {
      await axios.post(`/api/social/copy/${selectedLeader}`, { allocation_usd: allocation })
      setCopyMsg('Copy trading started successfully.')
      setSelectedLeader(null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCopyMsg(detail ?? 'Failed to start copy trading.')
    } finally {
      setCopying(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Copy Trading Marketplace</h2>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}
      {copyMsg && (
        <div className={`rounded-xl p-4 text-sm border ${copyMsg.includes('success') ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>{copyMsg}</div>
      )}

      {loading && (
        <div className="text-center py-12 text-slate-500">Loading leaderboard…</div>
      )}

      {!loading && leaders.length === 0 && !error && (
        <div className="text-center py-12 text-slate-500">No traders on the leaderboard yet.</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {leaders.map((leader) => (
          <div
            key={leader.id}
            className={`bg-slate-900 rounded-lg border p-4 cursor-pointer transition-all ${
              selectedLeader === leader.id
                ? 'border-amber-500 ring-1 ring-amber-500'
                : 'border-slate-800 hover:border-slate-700'
            }`}
            onClick={() => setSelectedLeader(leader.id)}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="font-semibold text-lg">{leader.name}</h3>
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <Users className="w-4 h-4" />
                  {leader.followers.toLocaleString()} followers
                </div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-green-400">
                  +{leader.return_3m}%
                </div>
                <div className="text-xs text-slate-500">3M Return</div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <div className="text-lg font-semibold">{leader.sharpe}</div>
                <div className="text-xs text-slate-500">Sharpe</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-red-400">
                  {leader.max_dd}%
                </div>
                <div className="text-xs text-slate-500">Max DD</div>
              </div>
              <div>
                <div className="text-lg font-semibold">{leader.win_rate}%</div>
                <div className="text-xs text-slate-500">Win Rate</div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-slate-800">
              <div className="text-sm">
                <span className="text-slate-400">AUM: </span>
                <span className="font-medium">${(leader.aum / 1000000).toFixed(2)}M</span>
              </div>
              <div className="text-sm">
                <span className="text-slate-400">Fee: </span>
                <span className="font-medium">{leader.fee}%</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedLeader && (
        <div className="bg-slate-900 rounded-lg border border-amber-500/50 p-6">
          <h3 className="text-lg font-semibold mb-4">Start Copying</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
              <label className="block text-sm text-slate-400 mb-2">
                Allocation Amount
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="1000"
                  max="100000"
                  step="1000"
                  value={allocation}
                  onChange={(e) => setAllocation(Number(e.target.value))}
                  className="flex-1"
                />
                <div className="w-32">
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="number"
                      value={allocation}
                      onChange={(e) => setAllocation(Number(e.target.value))}
                      className="w-full bg-slate-800 border border-slate-700 rounded pl-8 pr-3 py-2"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-slate-400">Estimated Monthly Fee</span>
                <span>${(allocation * 0.002).toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-400">Max Drawdown Stop</span>
                <select className="bg-slate-800 border border-slate-700 rounded px-2 py-1">
                  <option>10%</option>
                  <option>15%</option>
                  <option>20%</option>
                </select>
              </div>
            </div>
          </div>

          <div className="flex gap-4">
            <button onClick={startCopying} disabled={copying}
              className="flex-1 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-slate-950 font-bold py-3 rounded-lg">
              {copying ? 'Starting…' : 'Start Copy Trading'}
            </button>
            <button
              className="px-6 py-3 border border-slate-700 rounded-lg hover:bg-slate-800"
              onClick={() => setSelectedLeader(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
