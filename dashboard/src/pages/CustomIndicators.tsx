/**
 * Custom Indicators — dashboard version (Tailwind)
 * Lets users define, save, and apply custom technical indicators.
 */
import { useState } from 'react'
import { BarChart, Plus, Trash2, Play, Save, Code } from 'lucide-react'

interface Indicator {
  id: string
  name: string
  type: 'overlay' | 'oscillator'
  formula: string
  params: Record<string, number>
  color: string
  enabled: boolean
}

const BUILT_IN: Indicator[] = [
  { id: 'ema20',  name: 'EMA 20',          type: 'overlay',    formula: 'EMA(close, 20)',                color: '#60a5fa', params: { period: 20 },        enabled: true },
  { id: 'ema50',  name: 'EMA 50',          type: 'overlay',    formula: 'EMA(close, 50)',                color: '#f59e0b', params: { period: 50 },        enabled: true },
  { id: 'atr14',  name: 'ATR 14',          type: 'oscillator', formula: 'ATR(high, low, close, 14)',     color: '#a78bfa', params: { period: 14 },        enabled: false },
  { id: 'rsi14',  name: 'RSI 14',          type: 'oscillator', formula: 'RSI(close, 14)',                color: '#34d399', params: { period: 14 },        enabled: true },
  { id: 'macd',   name: 'MACD (12,26,9)',  type: 'oscillator', formula: 'MACD(close, 12, 26, 9)',       color: '#f87171', params: { fast: 12, slow: 26, signal: 9 }, enabled: false },
  { id: 'bb20',   name: 'Bollinger 20,2',  type: 'overlay',    formula: 'BB(close, 20, 2)',              color: '#94a3b8', params: { period: 20, std: 2 }, enabled: false },
]

const TEMPLATES = [
  { name: 'Hurst Exponent',    formula: 'HURST(close, 100)',                  description: 'Measures trend persistence. >0.5 = trending, <0.5 = mean-reverting.' },
  { name: 'COT Proxy',         formula: 'COT_PROXY(close, dxy, yields)',      description: 'Central bank demand signature used in the ML feature pipeline.' },
  { name: 'Volume Z-Score',    formula: 'ZSCORE(volume, 20)',                 description: 'Flags volume anomalies (dark pool detection heuristic).' },
  { name: 'ATR Normalised MA', formula: 'MA_DIST_ATR(close, 20, atr14)',     description: 'MA distance normalised by ATR — stationary feature for ML.' },
]

export default function CustomIndicators() {
  const [indicators, setIndicators] = useState<Indicator[]>(BUILT_IN)
  const [editing, setEditing] = useState<Indicator | null>(null)
  const [newName, setNewName] = useState('')
  const [newFormula, setNewFormula] = useState('')
  const [newColor, setNewColor] = useState('#60a5fa')
  const [newType, setNewType] = useState<'overlay' | 'oscillator'>('overlay')
  const [saved, setSaved] = useState(false)

  const toggle = (id: string) =>
    setIndicators(prev => prev.map(i => i.id === id ? { ...i, enabled: !i.enabled } : i))

  const remove = (id: string) =>
    setIndicators(prev => prev.filter(i => i.id !== id))

  const addCustom = () => {
    if (!newName.trim() || !newFormula.trim()) return
    const ind: Indicator = {
      id: `custom_${Date.now()}`, name: newName, type: newType,
      formula: newFormula, params: {}, color: newColor, enabled: true,
    }
    setIndicators(prev => [...prev, ind])
    setNewName(''); setNewFormula('')
    setSaved(true); setTimeout(() => setSaved(false), 2000)
  }

  const useTemplate = (t: typeof TEMPLATES[0]) => {
    setNewName(t.name); setNewFormula(t.formula)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BarChart className="w-7 h-7 text-amber-400" />
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Custom Indicators</h1>
          <p className="text-sm text-slate-400">Define, enable, and apply technical indicators to your charts.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active indicators */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-300">Active Indicators</h2>
              <span className="text-xs text-slate-500">{indicators.filter(i => i.enabled).length} enabled</span>
            </div>
            <div className="divide-y divide-slate-800/50">
              {indicators.map(ind => (
                <div key={ind.id} className="flex items-center gap-3 px-6 py-3">
                  <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: ind.color }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-200">{ind.name}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${ind.type === 'overlay' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'}`}>
                        {ind.type}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 font-mono mt-0.5">{ind.formula}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => toggle(ind.id)}
                      className={`relative w-10 h-5 rounded-full transition-colors ${ind.enabled ? 'bg-amber-500' : 'bg-slate-700'}`}>
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${ind.enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
                    </button>
                    <button onClick={() => remove(ind.id)}
                      className="p-1 text-slate-600 hover:text-red-400 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Apply button */}
          <button className="w-full flex items-center justify-center gap-2 py-2.5 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
            <Play className="w-4 h-4" />
            Apply to Chart
          </button>
        </div>

        {/* Add custom + templates */}
        <div className="space-y-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Plus className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-300">Add Custom Indicator</h2>
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="My Indicator"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500" />
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Type</label>
              <select value={newType} onChange={e => setNewType(e.target.value as 'overlay' | 'oscillator')}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none">
                <option value="overlay">Overlay (on price)</option>
                <option value="oscillator">Oscillator (separate pane)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Formula</label>
              <textarea value={newFormula} onChange={e => setNewFormula(e.target.value)} rows={3}
                placeholder="EMA(close, 20)"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm font-mono focus:outline-none focus:border-amber-500 resize-none" />
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1">Color</label>
              <div className="flex items-center gap-2">
                <input type="color" value={newColor} onChange={e => setNewColor(e.target.value)}
                  className="w-8 h-8 rounded cursor-pointer bg-transparent border-0" />
                <span className="text-xs text-slate-500 font-mono">{newColor}</span>
              </div>
            </div>

            <button onClick={addCustom}
              className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-colors ${
                saved ? 'bg-green-500 text-white' : 'bg-amber-500 hover:bg-amber-400 text-slate-900'
              }`}>
              <Save className="w-4 h-4" />
              {saved ? 'Saved!' : 'Add Indicator'}
            </button>
          </div>

          {/* Templates */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Code className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-300">ML Feature Templates</h2>
            </div>
            <div className="space-y-2">
              {TEMPLATES.map(t => (
                <button key={t.name} onClick={() => useTemplate(t)}
                  className="w-full text-left bg-slate-800 hover:bg-slate-700 rounded-lg p-3 transition-colors">
                  <div className="text-sm font-medium text-slate-200">{t.name}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{t.description}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
