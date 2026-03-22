import { useState } from 'react'
import { useStore } from '../store/useStore'

export function OrderPanel() {
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [size, setSize] = useState('0.01')
  const [stopLoss, setStopLoss] = useState('')
  const [takeProfit, setTakeProfit] = useState('')
  const tick = useStore((state) => state.ticks['XAUUSD'])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    const response = await fetch('/api/v1/trades', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify({
        symbol: 'XAUUSD',
        side,
        quantity: parseFloat(size),
        stop_loss: stopLoss ? parseFloat(stopLoss) : null,
        take_profit: takeProfit ? parseFloat(takeProfit) : null,
      })
    })

    if (response.ok) {
      // Show success notification
    }
  }

  const currentPrice = side === 'buy' ? tick?.ask : tick?.bid

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setSide('buy')}
          className={`flex-1 py-2 rounded font-medium transition-colors ${
            side === 'buy' 
              ? 'bg-green-600 text-white' 
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          BUY
        </button>
        <button
          onClick={() => setSide('sell')}
          className={`flex-1 py-2 rounded font-medium transition-colors ${
            side === 'sell' 
              ? 'bg-red-600 text-white' 
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          SELL
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-slate-400 mb-1">Size (lots)</label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-white focus:border-amber-500 focus:outline-none"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Stop Loss</label>
            <input
              type="number"
              step="0.01"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              placeholder={currentPrice ? (currentPrice * 0.99).toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-white focus:border-amber-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Take Profit</label>
            <input
              type="number"
              step="0.01"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              placeholder={currentPrice ? (currentPrice * 1.02).toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-white focus:border-amber-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="pt-2 border-t border-slate-800">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-slate-400">Margin Required</span>
            <span className="text-white">
              ${currentPrice ? (parseFloat(size) * currentPrice / 30).toFixed(2) : '-'}
            </span>
          </div>
          <div className="flex justify-between text-sm mb-4">
            <span className="text-slate-400">Commission</span>
            <span className="text-white">${(parseFloat(size) * 3.5).toFixed(2)}</span>
          </div>
        </div>

        <button
          type="submit"
          className={`w-full py-3 rounded-lg font-bold text-white transition-transform active:scale-95 ${
            side === 'buy' 
              ? 'bg-gradient-to-r from-green-600 to-green-500 hover:from-green-500 hover:to-green-400' 
              : 'bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-400'
          }`}
        >
          {side === 'buy' ? 'BUY LONG' : 'SELL SHORT'} @ {currentPrice?.toFixed(2) || '-'}
        </button>
      </form>
    </div>
  )
}
