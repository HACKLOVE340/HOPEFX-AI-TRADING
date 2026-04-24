import { useEffect, useState, useCallback } from 'react'
import { Brain, TrendingUp, TrendingDown, Minus, Activity, RefreshCw, AlertTriangle } from 'lucide-react'
import { useStore } from '../store/useStore'
import { api } from '../hooks/useApi'

interface MLSignal {
  id: string
  symbol: string
  direction: 'long' | 'short' | 'neutral'
  confidence: number
  model: string
  entry_price: number
  stop_loss: number
  take_profit: number
  generated_at: string
  status: 'active' | 'triggered' | 'expired'
}

interface MLHealth {
  model_available: boolean
  model_version: string
  oos_accuracy: number | null
  drift_detected: boolean
  last_retrain: string | null
}

type FetchState = 'idle' | 'loading' | 'ok' | 'error'

export function MLSignals() {
  const storeSignals = useStore((s) => s.signals)
  const [health, setHealth] = useState<MLHealth | null>(null)
  const [fetchState, setFetchState] = useState<FetchState>('idle')

  const fetchHealth = useCallback(async () => {
    try {
      const res = await api.get<MLHealth>('/ml/health')
      setHealth(res.data)
    } catch {
      // non-fatal
    }
  }, [])

  const fetchSignals = useCallback(async () => {
    if (storeSignals.length > 0) return
    setFetchState('loading')
    try {
      const res = await api.get<{ signals: MLSignal[] }>('/signals/active')
      const sigs = res.data?.signals ?? []
      if (sigs.length > 0) {
        useStore.getState().setSignals(sigs)
      }
      setFetchState('ok')
    } catch {
      setFetchState('error')
    }
  }, [storeSignals.length])

  useEffect(() => {
    fetchHealth()
    fetchSignals()
    const id = setInterval(fetchSignals, 30_000)
    return () => clearInterval(id)
  }, [fetchHealth, fetchSignals])

  const signals = storeSignals.slice(0, 5)
  const latest = signals[0] ?? null

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-amber-400" />
          <h3 className="font-semibold">ML Signals</h3>
        </div>
        <button
          onClick={() => { fetchSignals(); fetchHealth() }}
          className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          title="Refresh signals"
        >
          <RefreshCw className={`w-4 h-4 ${fetchState === 'loading' ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {latest ? (
        <div className={`p-4 rounded-lg mb-4 ${
          latest.direction === 'long'  ? 'bg-green-500/10 border border-green-500/20' :
          latest.direction === 'short' ? 'bg-red-500/10 border border-red-500/20' :
                                         'bg-slate-800/50 border border-slate-700'
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Current Signal — {latest.symbol}</span>
            <span className="text-xs text-slate-500">
              {new Date(latest.generated_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {latest.direction === 'long'    && <TrendingUp   className="w-8 h-8 text-green-400" />}
            {latest.direction === 'short'   && <TrendingDown className="w-8 h-8 text-red-400" />}
            {latest.direction === 'neutral' && <Minus        className="w-8 h-8 text-slate-400" />}
            <div>
              <div className="text-2xl font-bold capitalize">{latest.direction}</div>
              <div className="text-sm text-slate-400">
                {(latest.confidence * 100).toFixed(0)}% confidence
              </div>
            </div>
          </div>
          {(latest.entry_price > 0 || latest.stop_loss > 0 || latest.take_profit > 0) && (
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">Entry</div>
                <div className="font-mono text-slate-200">{latest.entry_price.toFixed(2)}</div>
              </div>
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">SL</div>
                <div className="font-mono text-red-400">{latest.stop_loss.toFixed(2)}</div>
              </div>
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">TP</div>
                <div className="font-mono text-green-400">{latest.take_profit.toFixed(2)}</div>
              </div>
            </div>
          )}
          <div className="mt-2 text-xs text-slate-500 font-mono">{latest.model}</div>
        </div>
      ) : (
        <div className="p-4 rounded-lg mb-4 bg-slate-800/50 border border-slate-700 text-center">
          {fetchState === 'loading' ? (
            <span className="text-slate-500 text-sm">Loading signals…</span>
          ) : fetchState === 'error' ? (
            <div className="flex items-center justify-center gap-2 text-amber-400 text-sm">
              <AlertTriangle className="w-4 h-4" />
              <span>Signal engine warming up</span>
            </div>
          ) : (
            <span className="text-slate-500 text-sm">No active signals — awaiting market data</span>
          )}
        </div>
      )}

      {signals.length > 1 && (
        <div className="space-y-2 mb-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">
            Recent Predictions
          </div>
          {signals.slice(1).map((sig) => (
            <div key={sig.id} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
              <div className="flex items-center gap-2">
                {sig.direction === 'long'    && <TrendingUp   className="w-4 h-4 text-green-400" />}
                {sig.direction === 'short'   && <TrendingDown className="w-4 h-4 text-red-400" />}
                {sig.direction === 'neutral' && <Minus        className="w-4 h-4 text-slate-400" />}
                <span className="text-sm capitalize">{sig.direction}</span>
                <span className="text-xs text-slate-500">{sig.symbol}</span>
              </div>
              <div className="text-sm text-slate-400">
                {(sig.confidence * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="pt-4 border-t border-slate-800">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-400">Active Model</span>
          <span className="text-amber-400 font-mono text-xs">
            {health?.model_version ?? latest?.model ?? '—'}
          </span>
        </div>
        <div className="flex items-center justify-between text-sm mt-2">
          <span className="text-slate-400">Drift Status</span>
          <span className={`flex items-center gap-1 ${health?.drift_detected ? 'text-amber-400' : 'text-green-400'}`}>
            <Activity className="w-3 h-3" />
            {health?.drift_detected ? 'Drift detected' : 'Normal'}
          </span>
        </div>
        {health?.oos_accuracy != null && (
          <div className="flex items-center justify-between text-sm mt-2">
            <span className="text-slate-400">OOS Accuracy</span>
            <span className="text-slate-300">{(health.oos_accuracy * 100).toFixed(1)}%</span>
          </div>
        )}
        {health?.last_retrain && (
          <div className="flex items-center justify-between text-sm mt-2">
            <span className="text-slate-400">Last Retrain</span>
            <span className="text-slate-300">
              {new Date(health.last_retrain).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
