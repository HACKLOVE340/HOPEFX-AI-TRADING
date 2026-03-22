import { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  Activity,
  Target,
  Shield
} from 'lucide-react'
import { EquityChart } from '../components/EquityChart'
import { RecentTrades } from '../components/RecentTrades'
import { MLSignals } from '../components/MLSignals'

export function Dashboard() {
  const equity = useStore((state) => state.equity)
  const [stats, setStats] = useState({
    dailyReturn: 1.23,
    totalReturn: 15.4,
    sharpe: 1.8,
    winRate: 62.5,
    maxDD: -3.2,
  })

  return (
    <div className="space-y-6">
      {/* Header Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          title="Equity"
          value={`$${equity.toLocaleString()}`}
          change="+$1,234"
          icon={DollarSign}
          color="amber"
        />
        <StatCard
          title="Daily Return"
          value={`+${stats.dailyReturn}%`}
          change="+$456.78"
          icon={TrendingUp}
          color="green"
        />
        <StatCard
          title="Total Return"
          value={`${stats.totalReturn}%`}
          change="YTD"
          icon={Target}
          color="blue"
        />
        <StatCard
          title="Sharpe Ratio"
          value={stats.sharpe.toString()}
          change="Excellent"
          icon={Activity}
          color="purple"
        />
        <StatCard
          title="Win Rate"
          value={`${stats.winRate}%`}
          change="32W / 19L"
          icon={Shield}
          color="emerald"
        />
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Equity Curve</h3>
            <EquityChart />
          </div>
          
          <RecentTrades />
        </div>

        <div className="space-y-6">
          <MLSignals />
          
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Risk Metrics</h3>
            <div className="space-y-3">
              <RiskBar label="Daily Loss Limit" current={1.2} max={2.0} color="red" />
              <RiskBar label="Position Risk" current={0.8} max={1.0} color="amber" />
              <RiskBar label="Drawdown" current={3.2} max={5.0} color="green" />
              <RiskBar label="Leverage" current={12} max={30} color="blue" />
            </div>
          </div>

          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h3 className="font-semibold mb-4">Active Session</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-400">Started</span>
                <span>2 hours ago</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Trades Today</span>
                <span>8</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">ML Predictions</span>
                <span>1,247</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Latency</span>
                <span className="text-green-400">23ms</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ title, value, change, icon: Icon, color }: any) {
  const colors: Record<string, string> = {
    amber: 'bg-amber-500/10 text-amber-400',
    green: 'bg-green-500/10 text-green-400',
    blue: 'bg-blue-500/10 text-blue-400',
    purple: 'bg-purple-500/10 text-purple-400',
    emerald: 'bg-emerald-500/10 text-emerald-400',
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-slate-400 text-sm">{title}</span>
        <div className={`p-2 rounded ${colors[color]}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-sm text-slate-500">{change}</div>
    </div>
  )
}

function RiskBar({ label, current, max, color }: any) {
  const pct = (current / max) * 100
  const colors: Record<string, string> = {
    red: 'bg-red-500',
    amber: 'bg-amber-500',
    green: 'bg-green-500',
    blue: 'bg-blue-500',
  }

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-400">{label}</span>
        <span>{current} / {max}</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
        <div 
          className={`h-full ${colors[color]} transition-all duration-500`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  )
}
