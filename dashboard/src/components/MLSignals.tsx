import { useEffect, useState } from 'react'
import { Brain, TrendingUp, TrendingDown, Minus, Activity } from 'lucide-react'

interface Signal {
  timestamp: string
  direction: 'long' | 'short' | 'neutral'
  confidence: number
  model: string
  features: string[]
}

export function MLSignals() {
  const [signals, setSignals] = useState<Signal[]>([
    {
      timestamp: '14:32:05',
      direction: 'long',
      confidence: 0.78,
      model: 'XGB-Ensemble-v2.4',
      features: ['RSI', 'MACD', 'Volatility', 'Order Flow']
    },
    {
      timestamp: '14:28:22',
      direction: 'neutral',
      confidence: 0.52,
      model: 'LSTM-Attn-v1.8',
      features: ['Price Action', 'Volume']
    },
    {
      timestamp: '14:15:10',
      direction: 'short',
      confidence: 0.65,
      model: 'XGB-Ensemble-v2.4',
      features: ['Resistance Break', 'Momentum']
    },
  ])

  const latest = signals[0]

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center gap-2 mb-4">
        <Brain className="w-5 h-5 text-amber-400" />
        <h3 className="font-semibold">ML Signals</h3>
      </div>

      {/* Current Signal */}
      <div className={`p-4 rounded-lg mb-4 ${
        latest.direction === 'long' ? 'bg-green-500/10 border border-green-500/20' :
        latest.direction === 'short' ? 'bg-red-500/10 border border-red-500/20' :
        'bg-slate-800/50'
      }`}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-slate-400">Current Signal</span>
          <span className="text-xs text-slate-500">{latest.timestamp}</span>
        </div>
        <div className="flex items-center gap-3">
          {latest.direction === 'long' && <TrendingUp className="w-8 h-8 text-green-400" />}
          {latest.direction === 'short' && <TrendingDown className="w-8 h-8 text-red-400" />}
          {latest.direction === 'neutral' && <Minus className="w-8 h-8 text-slate-400" />}
          <div>
            <div className="text-2xl font-bold capitalize">{latest.direction}</div>
            <div className="text-sm text-slate-400">
              {(latest.confidence * 100).toFixed(0)}% confidence
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {latest.features.map((f) => (
            <span key={f} className="px-2 py-1 bg-slate-800 rounded text-xs text-slate-300">
              {f}
            </span>
          ))}
        </div>
      </div>

      {/* Signal History */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">
          Recent Predictions
        </div>
        {signals.slice(1).map((sig, idx) => (
          <div key={idx} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
            <div className="flex items-center gap-2">
              {sig.direction === 'long' && <TrendingUp className="w-4 h-4 text-green-400" />}
              {sig.direction === 'short' && <TrendingDown className="w-4 h-4 text-red-400" />}
              {sig.direction === 'neutral' && <Minus className="w-4 h-4 text-slate-400" />}
              <span className="text-sm capitalize">{sig.direction}</span>
            </div>
            <div className="text-sm text-slate-400">
              {(sig.confidence * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>

      {/* Model Status */}
      <div className="mt-4 pt-4 border-t border-slate-800">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-400">Active Model</span>
          <span className="text-amber-400">{latest.model}</span>
        </div>
        <div className="flex items-center justify-between text-sm mt-2">
          <span className="text-slate-400">Drift Status</span>
          <span className="flex items-center gap-1 text-green-400">
            <Activity className="w-3 h-3" />
            Normal
          </span>
        </div>
        <div className="flex items-center justify-between text-sm mt-2">
          <span className="text-slate-400">Last Retrain</span>
          <span className="text-slate-300">2 hours ago</span>
        </div>
      </div>
    </div>
  )
}
