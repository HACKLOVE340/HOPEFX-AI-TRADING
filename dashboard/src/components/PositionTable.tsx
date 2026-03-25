import { useStore } from '../store/useStore'

export function PositionTable() {
  const positions = useStore((state) => state.positions)

  if (positions.length === 0) {
    return (
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center">
        <p className="text-slate-400">No open positions</p>
        <p className="text-sm text-slate-500 mt-1">Start trading to see positions here</p>
      </div>
    )
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <h3 className="font-semibold mb-4">Open Positions</h3>
      <table className="w-full">
        <thead>
          <tr className="text-left text-sm text-slate-400">
            <th className="pb-3">Symbol</th>
            <th className="pb-3">Side</th>
            <th className="pb-3">Qty</th>
            <th className="pb-3">Entry</th>
            <th className="pb-3">Current</th>
            <th className="pb-3 text-right">P&L</th>
            <th className="pb-3 text-center">Actions</th>
          </tr>
        </thead>
        <tbody className="text-sm">
          {positions.map((pos, idx) => (
            <tr key={idx} className="border-t border-slate-800">
              <td className="py-3 font-medium">{pos.symbol}</td>
              <td className="py-3">
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  pos.side === 'long'
                    ? 'bg-green-500/10 text-green-400' 
                    : 'bg-red-500/10 text-red-400'
                }`}>
                  {pos.side.toUpperCase()}
                </span>
              </td>
              <td className="py-3">{pos.size}</td>
              <td className="py-3">{pos.entry_price.toFixed(2)}</td>
              <td className="py-3">{pos.current_price.toFixed(2)}</td>
              <td className={`py-3 text-right font-medium ${
                pos.unrealized_pnl > 0 ? 'text-green-400' : 
                pos.unrealized_pnl < 0 ? 'text-red-400' : 'text-slate-400'
              }`}>
                {pos.unrealized_pnl > 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(2)}
              </td>
              <td className="py-3 text-center">
                <button className="px-3 py-1 bg-red-500/10 text-red-400 rounded text-xs hover:bg-red-500/20">
                  Close
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
