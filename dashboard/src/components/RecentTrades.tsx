import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, AlertTriangle } from 'lucide-react'
import { api } from '../hooks/useApi'

interface Trade {
  id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  entry_price: number
  exit_price: number | null
  pnl: number | null
  opened_at: string
  closed_at: string | null
  status: 'open' | 'closed'
}

type FetchState = 'idle' | 'loading' | 'ok' | 'error'

export function RecentTrades() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [fetchState, setFetchState] = useState<FetchState>('idle')

  const load = useCallback(async () => {
    setFetchState('loading')
    try {
      const res = await api.get<{ trades: Trade[] } | Trade[]>('/trading/trades')
      const raw = Array.isArray(res.data) ? res.data : (res.data as any)?.trades ?? []
      setTrades(raw.slice(0, 10))
      setFetchState('ok')
    } catch {
      setFetchState('error')
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 15_000)
    return () => clearInterval(id)
  }, [load])

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return iso
    }
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">Recent Trades</h3>
        <button
          onClick={load}
          className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          title="Refresh trades"
        >
          <RefreshCw className={`w-4 h-4 ${fetchState === 'loading' ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {fetchState === 'error' && (
        <div className="flex items-center gap-2 text-amber-400 text-sm mb-3">
          <AlertTriangle className="w-4 h-4" />
          <span>Could not load trades</span>
        </div>
      )}

      {trades.length === 0 ? (
        <div className="text-center py-8 text-slate-500 text-sm">
          {fetchState === 'loading' ? 'Loading trades…' : 'No trades yet — place your first order to see history here.'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-sm text-slate-400">
                <th className="pb-3">Time</th>
                <th className="pb-3">Symbol</th>
                <th className="pb-3">Side</th>
                <th className="pb-3">Qty</th>
                <th className="pb-3">Entry</th>
                <th className="pb-3">Exit</th>
                <th className="pb-3 text-right">P&amp;L</th>
                <th className="pb-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {trades.map((trade) => (
                <tr key={trade.id} className="border-t border-slate-800">
                  <td className="py-3 text-slate-400">{formatTime(trade.opened_at)}</td>
                  <td className="py-3 font-mono text-xs">{trade.symbol}</td>
                  <td className="py-3">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${
                      trade.side === 'buy'
                        ? 'bg-green-500/10 text-green-400'
                        : 'bg-red-500/10 text-red-400'
                    }`}>
                      {trade.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-3">{trade.quantity}</td>
                  <td className="py-3 font-mono">{trade.entry_price.toFixed(2)}</td>
                  <td className="py-3 font-mono">{trade.exit_price?.toFixed(2) ?? '—'}</td>
                  <td className={`py-3 text-right font-medium font-mono ${
                    trade.pnl == null   ? 'text-slate-400' :
                    trade.pnl > 0       ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {trade.pnl != null
                      ? `${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}`
                      : '—'}
                  </td>
                  <td className="py-3 text-center">
                    <span className={`px-2 py-1 rounded text-xs ${
                      trade.status === 'open'
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'bg-slate-700 text-slate-300'
                    }`}>
                      {trade.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
