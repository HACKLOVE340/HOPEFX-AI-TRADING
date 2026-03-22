import { useEffect, useState } from 'react'

interface Trade {
  id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  entry: number
  exit: number | null
  pnl: number | null
  time: string
  status: 'open' | 'closed'
}

export function RecentTrades() {
  const [trades, setTrades] = useState<Trade[]>([
    { id: '1', symbol: 'XAUUSD', side: 'buy', qty: 0.5, entry: 2034.50, exit: 2041.20, pnl: 335.00, time: '2 min ago', status: 'closed' },
    { id: '2', symbol: 'XAUUSD', side: 'sell', qty: 0.3, entry: 2042.10, exit: null, pnl: null, time: '15 min ago', status: 'open' },
    { id: '3', symbol: 'XAUUSD', side: 'buy', qty: 0.4, entry: 2028.30, exit: 2035.80, pnl: 300.00, time: '1 hour ago', status: 'closed' },
    { id: '4', symbol: 'XAUUSD', side: 'sell', qty: 0.5, entry: 2038.20, exit: 2031.50, pnl: 335.00, time: '3 hours ago', status: 'closed' },
  ])

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <h3 className="font-semibold mb-4">Recent Trades</h3>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left text-sm text-slate-400">
              <th className="pb-3">Time</th>
              <th className="pb-3">Side</th>
              <th className="pb-3">Qty</th>
              <th className="pb-3">Entry</th>
              <th className="pb-3">Exit</th>
              <th className="pb-3 text-right">P&L</th>
              <th className="pb-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t border-slate-800">
                <td className="py-3 text-slate-400">{trade.time}</td>
                <td className="py-3">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    trade.side === 'buy' 
                      ? 'bg-green-500/10 text-green-400' 
                      : 'bg-red-500/10 text-red-400'
                  }`}>
                    {trade.side.toUpperCase()}
                  </span>
                </td>
                <td className="py-3">{trade.qty}</td>
                <td className="py-3">{trade.entry.toFixed(2)}</td>
                <td className="py-3">{trade.exit?.toFixed(2) || '-'}</td>
                <td className={`py-3 text-right font-medium ${
                  trade.pnl && trade.pnl > 0 ? 'text-green-400' : 
                  trade.pnl && trade.pnl < 0 ? 'text-red-400' : 'text-slate-400'
                }`}>
                  {trade.pnl ? (trade.pnl > 0 ? '+' : '') + trade.pnl.toFixed(2) : '-'}
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
    </div>
  )
}
