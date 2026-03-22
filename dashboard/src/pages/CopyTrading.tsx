import { useState } from 'react'
import { Users, TrendingUp, Star, DollarSign } from 'lucide-react'

const LEADERS = [
  {
    id: '1',
    name: 'GoldHunter Pro',
    return_3m: 45.2,
    sharpe: 2.1,
    max_dd: -5.8,
    followers: 1234,
    aum: 2500000,
    fee: 20,
    win_rate: 68,
    trades_per_week: 12,
    avg_trade_duration: '4h 30m',
  },
  {
    id: '2',
    name: 'XAU Scalper',
    return_3m: 32.8,
    sharpe: 1.9,
    max_dd: -3.2,
    followers: 892,
    aum: 1200000,
    fee: 15,
    win_rate: 72,
    trades_per_week: 45,
    avg_trade_duration: '45m',
  },
  {
    id: '3',
    name: 'Macro Trend',
    return_3m: 28.5,
    sharpe: 1.6,
    max_dd: -8.1,
    followers: 567,
    aum: 890000,
    fee: 25,
    win_rate: 58,
    trades_per_week: 6,
    avg_trade_duration: '3d 12h',
  },
]

export function CopyTrading() {
  const [selectedLeader, setSelectedLeader] = useState<string | null>(null)
  const [allocation, setAllocation] = useState(10000)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Copy Trading Marketplace</h2>
        <div className="flex gap-2">
          <select className="bg-slate-800 border border-slate-700 rounded px-3 py-2">
            <option>All Strategies</option>
            <option>Scalping</option>
            <option>Swing Trading</option>
            <option>Position Trading</option>
          </select>
          <select className="bg-slate-800 border border-slate-700 rounded px-3 py-2">
            <option>Sort by Return</option>
            <option>Sort by Sharpe</option>
            <option>Sort by Followers</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {LEADERS.map((leader) => (
          <div 
            key={leader.id}
            className={`bg-slate-900 rounded-lg border p-4 cursor-pointer transition-all ${
              selectedLeader === leader.id 
                ? 'border-amber-500 ring-1 ring-amber-500' 
                : 'border-slate-800 hover:border-slate-700'
            }`}
            onClick={() => setSelectedLeader(leader.id)}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="font-semibold text-lg">{leader.name}</h3>
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <Users className="w-4 h-4" />
                  {leader.followers.toLocaleString()} followers
                </div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-green-400">
                  +{leader.return_3m}%
                </div>
                <div className="text-xs text-slate-500">3M Return</div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <div className="text-lg font-semibold">{leader.sharpe}</div>
                <div className="text-xs text-slate-500">Sharpe</div>
              </div>
              <div>
                <div className="text-lg font-semibold text-red-400">
                  {leader.max_dd}%
                </div>
                <div className="text-xs text-slate-500">Max DD</div>
              </div>
              <div>
                <div className="text-lg font-semibold">{leader.win_rate}%</div>
                <div className="text-xs text-slate-500">Win Rate</div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-slate-800">
              <div className="text-sm">
                <span className="text-slate-400">AUM: </span>
                <span className="font-medium">${(leader.aum / 1000000).toFixed(2)}M</span>
              </div>
              <div className="text-sm">
                <span className="text-slate-400">Fee: </span>
                <span className="font-medium">{leader.fee}%</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedLeader && (
        <div className="bg-slate-900 rounded-lg border border-amber-500/50 p-6">
          <h3 className="text-lg font-semibold mb-4">Start Copying</h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
              <label className="block text-sm text-slate-400 mb-2">
                Allocation Amount
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="1000"
                  max="100000"
                  step="1000"
                  value={allocation}
                  onChange={(e) => setAllocation(Number(e.target.value))}
                  className="flex-1"
                />
                <div className="w-32">
                  <div className="relative">
                    <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="number"
                      value={allocation}
                      onChange={(e) => setAllocation(Number(e.target.value))}
                      className="w-full bg-slate-800 border border-slate-700 rounded pl-8 pr-3 py-2"
                    />
                  </div>
                </div>
              </div>
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-slate-400">Estimated Monthly Fee</span>
                <span>${(allocation * 0.002).toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-400">Max Drawdown Stop</span>
                <select className="bg-slate-800 border border-slate-700 rounded px-2 py-1">
                  <option>10%</option>
                  <option>15%</option>
                  <option>20%</option>
                </select>
              </div>
            </div>
          </div>

          <div className="flex gap-4">
            <button className="flex-1 bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold py-3 rounded-lg">
              Start Copy Trading
            </button>
            <button 
              className="px-6 py-3 border border-slate-700 rounded-lg hover:bg-slate-800"
              onClick={() => setSelectedLeader(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
