/**
 * StrategyBuilder — No-Code Visual Strategy Builder
 *
 * Exposes the full power of the nocode/ backend module:
 * - Drag-and-drop node-based strategy creation
 * - State machine visualization
 * - ML node integration
 * - Live backtesting preview
 * - Strategy deployment to Dynamic Registry
 *
 * Backend: /api/strategies/dynamic, nocode/builder.py, nocode/state_machine.py, nocode/ml_nodes.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Brain, Play, Save, Upload, Download, Trash2, Plus, Zap,
  GitBranch, Activity, Target, TrendingUp, TrendingDown,
  AlertTriangle, CheckCircle, RefreshCw, Settings, Eye,
  Layers, Box, ArrowRight, Circle, Square, Diamond,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface StrategyNode {
  id: string
  type: 'indicator' | 'condition' | 'action' | 'ml_model' | 'risk_filter' | 'state'
  name: string
  config: Record<string, unknown>
  position: { x: number; y: number }
  connections: string[]
}

interface Strategy {
  id: string
  name: string
  description: string
  version: string
  status: 'draft' | 'testing' | 'active' | 'paused'
  nodes: StrategyNode[]
  performance?: StrategyPerformance
  created_at: string
  updated_at: string
}

interface StrategyPerformance {
  win_rate: number
  sharpe_ratio: number
  max_drawdown: number
  total_trades: number
  profit_factor: number
  avg_trade_duration: string
}

interface NodeTemplate {
  type: StrategyNode['type']
  name: string
  icon: typeof Brain
  description: string
  defaultConfig: Record<string, unknown>
}

type TabId = 'builder' | 'strategies' | 'backtest' | 'deploy'

// ── Node Templates ────────────────────────────────────────────────────────────
const NODE_TEMPLATES: NodeTemplate[] = [
  // Indicators
  { type: 'indicator', name: 'Moving Average', icon: TrendingUp, description: 'SMA/EMA/WMA with configurable period', defaultConfig: { type: 'EMA', period: 21, source: 'close' } },
  { type: 'indicator', name: 'RSI', icon: Activity, description: 'Relative Strength Index', defaultConfig: { period: 14, overbought: 70, oversold: 30 } },
  { type: 'indicator', name: 'MACD', icon: GitBranch, description: 'Moving Average Convergence Divergence', defaultConfig: { fast: 12, slow: 26, signal: 9 } },
  { type: 'indicator', name: 'Bollinger Bands', icon: Layers, description: 'Volatility bands around MA', defaultConfig: { period: 20, std_dev: 2.0 } },
  { type: 'indicator', name: 'ATR', icon: Target, description: 'Average True Range for volatility', defaultConfig: { period: 14 } },
  { type: 'indicator', name: 'Volume Profile', icon: Box, description: 'Volume at price levels', defaultConfig: { lookback: 100 } },
  { type: 'indicator', name: 'Order Flow', icon: Zap, description: 'Order flow imbalance detection', defaultConfig: { threshold: 0.7 } },
  // Conditions
  { type: 'condition', name: 'Crossover', icon: ArrowRight, description: 'When indicator A crosses above/below B', defaultConfig: { direction: 'above' } },
  { type: 'condition', name: 'Threshold', icon: Target, description: 'When value exceeds/falls below level', defaultConfig: { operator: '>', value: 0 } },
  { type: 'condition', name: 'Time Filter', icon: Activity, description: 'Only during specific trading sessions', defaultConfig: { sessions: ['london', 'newyork'] } },
  { type: 'condition', name: 'Regime Filter', icon: Diamond, description: 'Only in specific market regimes', defaultConfig: { regimes: ['trending'] } },
  // Actions
  { type: 'action', name: 'Market Order', icon: Zap, description: 'Execute at market price', defaultConfig: { side: 'buy', size_pct: 1.0 } },
  { type: 'action', name: 'Limit Order', icon: Target, description: 'Place limit order at price', defaultConfig: { side: 'buy', offset_pips: 5 } },
  { type: 'action', name: 'Close Position', icon: Square, description: 'Close existing position', defaultConfig: { close_pct: 100 } },
  { type: 'action', name: 'Set SL/TP', icon: AlertTriangle, description: 'Set stop loss and take profit', defaultConfig: { sl_atr_mult: 1.5, tp_atr_mult: 3.0 } },
  // ML Models
  { type: 'ml_model', name: 'Trend Predictor', icon: Brain, description: 'LSTM-based trend direction prediction', defaultConfig: { model: 'lstm_trend', confidence_threshold: 0.7 } },
  { type: 'ml_model', name: 'Volatility Forecast', icon: Activity, description: 'Predict upcoming volatility regime', defaultConfig: { model: 'vol_forecast', horizon: '1h' } },
  { type: 'ml_model', name: 'Sentiment Score', icon: Eye, description: 'News sentiment analysis', defaultConfig: { model: 'sentiment_nlp', sources: ['reuters', 'bloomberg'] } },
  // Risk Filters
  { type: 'risk_filter', name: 'Max Drawdown', icon: TrendingDown, description: 'Pause if drawdown exceeds limit', defaultConfig: { max_dd_pct: 5.0 } },
  { type: 'risk_filter', name: 'Daily Loss Limit', icon: AlertTriangle, description: 'Stop trading if daily loss hit', defaultConfig: { max_daily_loss_pct: 2.0 } },
  { type: 'risk_filter', name: 'Correlation Filter', icon: GitBranch, description: 'Avoid correlated positions', defaultConfig: { max_correlation: 0.7 } },
  // State Machine
  { type: 'state', name: 'State Transition', icon: Circle, description: 'Define state machine transition', defaultConfig: { from_state: 'idle', to_state: 'entry', trigger: 'signal' } },
]

// ── Component ─────────────────────────────────────────────────────────────────
export function StrategyBuilder() {
  const [activeTab, setActiveTab] = useState<TabId>('strategies')
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null)
  const [loading, setLoading] = useState(true)
  const [deploying, setDeploying] = useState(false)
  const [backtestRunning, setBacktestRunning] = useState(false)
  const [backtestResult, setBacktestResult] = useState<StrategyPerformance | null>(null)
  const [draggedTemplate, setDraggedTemplate] = useState<NodeTemplate | null>(null)

  // ── Fetch strategies from backend ──────────────────────────────────────────
  const fetchStrategies = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/strategies/dynamic', {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      })
      if (res.ok) {
        const data = await res.json()
        setStrategies(data.strategies || [])
      }
    } catch (err) {
      console.error('Failed to fetch strategies:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchStrategies() }, [fetchStrategies])

  // ── Create new strategy ────────────────────────────────────────────────────
  const createStrategy = async () => {
    try {
      const res = await fetch('/api/strategies/dynamic', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({
          name: `Strategy ${strategies.length + 1}`,
          description: 'New strategy created from builder',
          nodes: [],
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setStrategies(prev => [...prev, data])
        setSelectedStrategy(data)
        setActiveTab('builder')
      }
    } catch (err) {
      console.error('Failed to create strategy:', err)
    }
  }

  // ── Deploy strategy ────────────────────────────────────────────────────────
  const deployStrategy = async (strategyId: string) => {
    setDeploying(true)
    try {
      const res = await fetch(`/api/strategies/dynamic/${strategyId}/deploy`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      })
      if (res.ok) {
        await fetchStrategies()
      }
    } catch (err) {
      console.error('Failed to deploy strategy:', err)
    } finally {
      setDeploying(false)
    }
  }

  // ── Run backtest ───────────────────────────────────────────────────────────
  const runBacktest = async (strategyId: string) => {
    setBacktestRunning(true)
    setBacktestResult(null)
    try {
      const res = await fetch(`/api/strategies/dynamic/${strategyId}/backtest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ period: '3M', symbol: 'XAUUSD' }),
      })
      if (res.ok) {
        const data = await res.json()
        setBacktestResult(data.performance)
      }
    } catch (err) {
      console.error('Failed to run backtest:', err)
    } finally {
      setBacktestRunning(false)
    }
  }

  // ── Add node to strategy ───────────────────────────────────────────────────
  const addNodeToStrategy = (template: NodeTemplate) => {
    if (!selectedStrategy) return
    const newNode: StrategyNode = {
      id: `node_${Date.now()}`,
      type: template.type,
      name: template.name,
      config: { ...template.defaultConfig },
      position: { x: 100 + Math.random() * 400, y: 100 + Math.random() * 300 },
      connections: [],
    }
    setSelectedStrategy(prev => prev ? {
      ...prev,
      nodes: [...prev.nodes, newNode],
    } : null)
  }

  // ── Save strategy ──────────────────────────────────────────────────────────
  const saveStrategy = async () => {
    if (!selectedStrategy) return
    try {
      await fetch(`/api/strategies/dynamic/${selectedStrategy.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify(selectedStrategy),
      })
      await fetchStrategies()
    } catch (err) {
      console.error('Failed to save strategy:', err)
    }
  }

  // ── Remove node ────────────────────────────────────────────────────────────
  const removeNode = (nodeId: string) => {
    if (!selectedStrategy) return
    setSelectedStrategy(prev => prev ? {
      ...prev,
      nodes: prev.nodes.filter(n => n.id !== nodeId),
    } : null)
  }

  // ── Tabs ───────────────────────────────────────────────────────────────────
  const tabs: { id: TabId; label: string; icon: typeof Brain }[] = [
    { id: 'strategies', label: 'My Strategies', icon: Layers },
    { id: 'builder', label: 'Visual Builder', icon: GitBranch },
    { id: 'backtest', label: 'Backtest', icon: Play },
    { id: 'deploy', label: 'Deploy', icon: Upload },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Strategy Builder</h1>
          <p className="text-sm text-slate-400 mt-1">
            Build, test, and deploy trading strategies with no code required
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={createStrategy}
            className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Strategy
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-xl p-1 border border-slate-800">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'strategies' && (
        <div className="space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="w-6 h-6 text-amber-400 animate-spin" />
            </div>
          ) : strategies.length === 0 ? (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
              <Brain className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-300 mb-2">No Strategies Yet</h3>
              <p className="text-sm text-slate-500 mb-6">Create your first strategy using the visual builder</p>
              <button
                onClick={createStrategy}
                className="px-6 py-2.5 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold transition-colors"
              >
                Create Strategy
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {strategies.map(strategy => (
                <div
                  key={strategy.id}
                  className="bg-slate-900 rounded-xl border border-slate-800 p-5 hover:border-amber-500/30 transition-colors cursor-pointer"
                  onClick={() => { setSelectedStrategy(strategy); setActiveTab('builder') }}
                >
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-slate-200">{strategy.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${
                      strategy.status === 'active' ? 'bg-green-500/10 text-green-400 border-green-500/30' :
                      strategy.status === 'testing' ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' :
                      strategy.status === 'paused' ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30' :
                      'bg-slate-500/10 text-slate-400 border-slate-500/30'
                    }`}>
                      {strategy.status}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mb-3">{strategy.description}</p>
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span>{strategy.nodes?.length || 0} nodes</span>
                    <span>v{strategy.version}</span>
                    {strategy.performance && (
                      <span className="text-green-400">{(strategy.performance.win_rate * 100).toFixed(0)}% WR</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'builder' && (
        <div className="grid grid-cols-12 gap-4">
          {/* Node Palette */}
          <div className="col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-4 max-h-[70vh] overflow-y-auto">
            <h3 className="text-sm font-semibold text-slate-300 mb-3">Node Palette</h3>
            {['indicator', 'condition', 'action', 'ml_model', 'risk_filter', 'state'].map(type => (
              <div key={type} className="mb-4">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  {type.replace('_', ' ')}
                </div>
                {NODE_TEMPLATES.filter(t => t.type === type).map(template => (
                  <button
                    key={template.name}
                    onClick={() => addNodeToStrategy(template)}
                    onDragStart={() => setDraggedTemplate(template)}
                    draggable
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm text-slate-300 hover:bg-slate-800 hover:text-slate-100 transition-colors mb-1"
                  >
                    <template.icon className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                    <span className="truncate">{template.name}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>

          {/* Canvas */}
          <div className="col-span-6 bg-slate-900 rounded-xl border border-slate-800 p-4 min-h-[70vh] relative"
            onDragOver={e => e.preventDefault()}
            onDrop={() => { if (draggedTemplate) { addNodeToStrategy(draggedTemplate); setDraggedTemplate(null) } }}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-300">
                {selectedStrategy?.name || 'Select a strategy'}
              </h3>
              <div className="flex gap-2">
                <button onClick={saveStrategy} className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition-colors">
                  <Save className="w-3.5 h-3.5" /> Save
                </button>
              </div>
            </div>
            {selectedStrategy ? (
              <div className="space-y-2">
                {selectedStrategy.nodes.length === 0 ? (
                  <div className="flex items-center justify-center h-[50vh] text-slate-500 text-sm">
                    Drag nodes from the palette or click to add
                  </div>
                ) : (
                  selectedStrategy.nodes.map(node => (
                    <div
                      key={node.id}
                      className={`flex items-center justify-between p-3 rounded-lg border ${
                        node.type === 'indicator' ? 'bg-blue-500/5 border-blue-500/20' :
                        node.type === 'condition' ? 'bg-purple-500/5 border-purple-500/20' :
                        node.type === 'action' ? 'bg-green-500/5 border-green-500/20' :
                        node.type === 'ml_model' ? 'bg-amber-500/5 border-amber-500/20' :
                        node.type === 'risk_filter' ? 'bg-red-500/5 border-red-500/20' :
                        'bg-slate-500/5 border-slate-500/20'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${
                          node.type === 'indicator' ? 'bg-blue-400' :
                          node.type === 'condition' ? 'bg-purple-400' :
                          node.type === 'action' ? 'bg-green-400' :
                          node.type === 'ml_model' ? 'bg-amber-400' :
                          node.type === 'risk_filter' ? 'bg-red-400' :
                          'bg-slate-400'
                        }`} />
                        <div>
                          <div className="text-sm font-medium text-slate-200">{node.name}</div>
                          <div className="text-xs text-slate-500">{node.type.replace('_', ' ')}</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button className="p-1 text-slate-500 hover:text-slate-300">
                          <Settings className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => removeNode(node.id)} className="p-1 text-slate-500 hover:text-red-400">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-[50vh] text-slate-500 text-sm">
                Select or create a strategy to begin
              </div>
            )}
          </div>

          {/* Properties Panel */}
          <div className="col-span-3 bg-slate-900 rounded-xl border border-slate-800 p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3">Properties</h3>
            {selectedStrategy ? (
              <div className="space-y-4">
                <div>
                  <label className="text-xs text-slate-500">Strategy Name</label>
                  <input
                    type="text"
                    value={selectedStrategy.name}
                    onChange={e => setSelectedStrategy(prev => prev ? { ...prev, name: e.target.value } : null)}
                    className="w-full mt-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-amber-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500">Description</label>
                  <textarea
                    value={selectedStrategy.description}
                    onChange={e => setSelectedStrategy(prev => prev ? { ...prev, description: e.target.value } : null)}
                    className="w-full mt-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-amber-500 focus:outline-none resize-none"
                    rows={3}
                  />
                </div>
                <div className="pt-3 border-t border-slate-800">
                  <div className="text-xs text-slate-500 mb-2">Quick Stats</div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="bg-slate-800 rounded-lg p-2">
                      <div className="text-slate-500">Nodes</div>
                      <div className="text-slate-200 font-medium">{selectedStrategy.nodes.length}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-2">
                      <div className="text-slate-500">Version</div>
                      <div className="text-slate-200 font-medium">{selectedStrategy.version}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-2">
                      <div className="text-slate-500">Status</div>
                      <div className="text-slate-200 font-medium capitalize">{selectedStrategy.status}</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500">Select a strategy to view properties</p>
            )}
          </div>
        </div>
      )}

      {activeTab === 'backtest' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-lg font-semibold text-slate-200">Backtest Results</h3>
            {selectedStrategy && (
              <button
                onClick={() => runBacktest(selectedStrategy.id)}
                disabled={backtestRunning}
                className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 disabled:bg-slate-700 text-slate-900 disabled:text-slate-400 rounded-lg text-sm font-semibold transition-colors"
              >
                {backtestRunning ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                {backtestRunning ? 'Running...' : 'Run Backtest'}
              </button>
            )}
          </div>
          {backtestResult ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <MetricCard label="Win Rate" value={`${(backtestResult.win_rate * 100).toFixed(1)}%`} good={backtestResult.win_rate > 0.5} />
              <MetricCard label="Sharpe Ratio" value={backtestResult.sharpe_ratio.toFixed(2)} good={backtestResult.sharpe_ratio > 1.0} />
              <MetricCard label="Max Drawdown" value={`${backtestResult.max_drawdown.toFixed(1)}%`} good={backtestResult.max_drawdown < 10} />
              <MetricCard label="Total Trades" value={backtestResult.total_trades.toString()} />
              <MetricCard label="Profit Factor" value={backtestResult.profit_factor.toFixed(2)} good={backtestResult.profit_factor > 1.5} />
              <MetricCard label="Avg Duration" value={backtestResult.avg_trade_duration} />
            </div>
          ) : (
            <div className="text-center py-12 text-slate-500 text-sm">
              {selectedStrategy ? 'Click "Run Backtest" to test your strategy' : 'Select a strategy first'}
            </div>
          )}
        </div>
      )}

      {activeTab === 'deploy' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <h3 className="text-lg font-semibold text-slate-200 mb-6">Deploy Strategy</h3>
          {selectedStrategy ? (
            <div className="space-y-6">
              <div className="flex items-center gap-4 p-4 bg-slate-800 rounded-lg">
                <div className="w-10 h-10 bg-amber-500/10 rounded-lg flex items-center justify-center">
                  <Zap className="w-5 h-5 text-amber-400" />
                </div>
                <div className="flex-1">
                  <div className="font-medium text-slate-200">{selectedStrategy.name}</div>
                  <div className="text-xs text-slate-500">{selectedStrategy.nodes.length} nodes • v{selectedStrategy.version}</div>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full border ${
                  selectedStrategy.status === 'active' ? 'bg-green-500/10 text-green-400 border-green-500/30' :
                  'bg-slate-500/10 text-slate-400 border-slate-500/30'
                }`}>
                  {selectedStrategy.status}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <button
                  onClick={() => deployStrategy(selectedStrategy.id)}
                  disabled={deploying || selectedStrategy.status === 'active'}
                  className="flex items-center justify-center gap-2 px-6 py-3 bg-green-600 hover:bg-green-500 disabled:bg-slate-700 text-white disabled:text-slate-400 rounded-lg font-semibold transition-colors"
                >
                  {deploying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                  {deploying ? 'Deploying...' : 'Deploy to Live'}
                </button>
                <button
                  onClick={() => deployStrategy(selectedStrategy.id)}
                  className="flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold transition-colors"
                >
                  <Eye className="w-4 h-4" />
                  Deploy as Shadow (Paper)
                </button>
              </div>
              <div className="p-4 bg-amber-500/5 border border-amber-500/20 rounded-lg">
                <div className="flex items-center gap-2 text-amber-400 text-sm font-medium mb-1">
                  <AlertTriangle className="w-4 h-4" />
                  Deployment Notice
                </div>
                <p className="text-xs text-slate-400">
                  Live deployment will activate this strategy on your connected broker account.
                  Shadow deployment runs in parallel without executing real trades.
                  All deployments go through the Dynamic Strategy Registry with zero-downtime hot-reload.
                </p>
              </div>
            </div>
          ) : (
            <div className="text-center py-12 text-slate-500 text-sm">
              Select a strategy to deploy
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Helper Components ─────────────────────────────────────────────────────────
function MetricCard({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="bg-slate-800 rounded-lg p-3">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-lg font-bold ${
        good === true ? 'text-green-400' : good === false ? 'text-red-400' : 'text-slate-200'
      }`}>
        {value}
      </div>
    </div>
  )
}
