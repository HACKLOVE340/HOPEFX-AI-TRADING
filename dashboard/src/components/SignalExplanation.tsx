/**
 * SignalExplanation
 * Shows SHAP feature importances, regime, confidence, and plain-English
 * summary for a given signal. Wires to GET /api/explain/signal/{signal_id}
 * or /api/explain/latest when no signal_id is provided.
 */
import { useEffect, useState } from 'react'
import { Brain, TrendingUp, TrendingDown, Minus, Info } from 'lucide-react'

interface FeatureImportance {
  feature: string
  importance: number
  description: string
}

interface SignalExplanationData {
  signal_id: string
  symbol: string
  direction: string
  confidence: number
  regime: string
  top_features: FeatureImportance[]
  plain_english: string
  timestamp: string
}

function DirectionBadge({ direction }: { direction: string }) {
  const d = direction.toUpperCase()
  if (d === 'BUY') return (
    <span className="flex items-center gap-1 px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded text-xs font-bold">
      <TrendingUp className="w-3 h-3" /> BUY
    </span>
  )
  if (d === 'SELL') return (
    <span className="flex items-center gap-1 px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs font-bold">
      <TrendingDown className="w-3 h-3" /> SELL
    </span>
  )
  return (
    <span className="flex items-center gap-1 px-2 py-0.5 bg-slate-700 text-slate-400 rounded text-xs font-bold">
      <Minus className="w-3 h-3" /> HOLD
    </span>
  )
}

function FeatureBar({ feature, importance, description }: FeatureImportance) {
  const pct = Math.min(Math.abs(importance) * 100, 100)
  const positive = importance >= 0
  return (
    <div className="mb-3">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-slate-300 font-mono">{feature}</span>
        <span className={`text-xs font-semibold ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
          {positive ? '+' : ''}{(importance * 100).toFixed(1)}%
        </span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
        <div
          className={`h-2 rounded-full ${positive ? 'bg-emerald-500' : 'bg-red-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-slate-500 mt-0.5">{description}</div>
    </div>
  )
}

export function SignalExplanation({ signalId }: { signalId?: string }) {
  const [data, setData] = useState<SignalExplanationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const url = signalId
      ? `/api/explain/signal/${signalId}`
      : '/api/explain/latest'

    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: SignalExplanationData) => { setData(d); setError(null) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [signalId])

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Brain className="w-5 h-5 text-amber-400" />
        <h3 className="font-semibold text-slate-200">Why this signal?</h3>
      </div>

      {loading && <div className="text-slate-500 text-sm">Loading explanation…</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {data && (
        <>
          {/* Header row */}
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <span className="font-mono font-bold text-white">{data.symbol}</span>
            <DirectionBadge direction={data.direction} />
            <span className="text-xs text-slate-400">
              Confidence: <span className="text-white font-semibold">{(data.confidence * 100).toFixed(0)}%</span>
            </span>
            <span className="text-xs px-2 py-0.5 bg-slate-800 rounded text-slate-400 capitalize">
              {data.regime} regime
            </span>
          </div>

          {/* Confidence bar */}
          <div className="mb-4">
            <div className="w-full bg-slate-700 rounded-full h-2">
              <div
                className="h-2 rounded-full bg-amber-500"
                style={{ width: `${data.confidence * 100}%` }}
              />
            </div>
          </div>

          {/* Top 5 SHAP features */}
          <div className="mb-4">
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-3">
              Top contributing features
            </div>
            {data.top_features.map((f) => (
              <FeatureBar key={f.feature} {...f} />
            ))}
          </div>

          {/* Plain English summary */}
          <div className="bg-slate-800 rounded-lg p-3 flex gap-2">
            <Info className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-slate-300 leading-relaxed">{data.plain_english}</p>
          </div>

          <div className="text-xs text-slate-600 mt-2 text-right">
            {new Date(data.timestamp).toLocaleString()}
          </div>
        </>
      )}
    </div>
  )
}
