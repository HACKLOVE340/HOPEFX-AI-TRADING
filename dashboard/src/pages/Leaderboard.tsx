import { Trophy, Medal, TrendingUp, Users } from 'lucide-react'

const RANKINGS = [
  { rank: 1, name: 'GoldMaster', return: 156.4, sharpe: 2.8, followers: 3420, prize: '$10,000' },
  { rank: 2, name: 'XAUWhale', return: 142.8, sharpe: 2.5, followers: 2890, prize: '$5,000' },
  { rank: 3, name: 'BullionKing', return: 138.2, sharpe: 2.3, followers: 2156, prize: '$2,500' },
  { rank: 4, name: 'GoldRush', return: 125.6, sharpe: 2.1, followers: 1890, prize: '$1,000' },
  { rank: 5, name: 'PreciousAI', return: 118.3, sharpe: 2.0, followers: 1654, prize: '$500' },
]

export function Leaderboard() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Global Leaderboard</h2>
        <div className="flex gap-2">
          <button className="px-4 py-2 bg-amber-500/10 text-amber-400 rounded-lg text-sm font-medium">
            Monthly
          </button>
          <button className="px-4 py-2 text-slate-400 hover:bg-slate-800 rounded-lg text-sm">
            Quarterly
          </button>
          <button className="px-4 py-2 text-slate-400 hover:bg-slate-800 rounded-lg text-sm">
            All Time
          </button>
        </div>
      </div>

      {/* Top 3 Podium */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {RANKINGS.slice(0, 3).map((trader, idx) => (
          <div 
            key={trader.rank}
            className={`relative bg-slate-900 rounded-lg border p-6 text-center ${
              idx === 0 ? 'border-yellow-500/50 order-2' : 
              idx === 1 ? 'border-slate-400/50 order-1' : 
              'border-amber-700/50 order-3'
            }`}
          >
            <div className={`absolute -top-4 left-1/2 -translate-x-1/2 w-8 h-8 rounded-full flex items-center justify-center font-bold ${
              idx === 0 ? 'bg-yellow-500 text-yellow-950' :
              idx === 1 ? 'bg-slate-400 text-slate-950' :
              'bg-amber-700 text-amber-100'
            }`}>
              {trader.rank}
            </div>
            <h3 className="text-xl font-bold mt-4">{trader.name}</h3>
            <div className="text-3xl font-bold text-green-400 my-2">
              +{trader.return}%
            </div>
            <div className="text-sm text-slate-400">Prize: {trader.prize}</div>
          </div>
        ))}
      </div>

      {/* Full Table */}
      <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-800/50">
            <tr>
              <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Rank</th>
              <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Trader</th>
              <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Return</th>
              <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Sharpe</th>
              <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Followers</th>
              <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Prize</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {RANKINGS.map((trader) => (
              <tr key={trader.rank} className="hover:bg-slate-800/30">
                <td className="px-6 py-4">
                  {trader.rank <= 3 ? (
                    <Medal className={`w-5 h-5 ${
                      trader.rank === 1 ? 'text-yellow-500' :
                      trader.rank === 2 ? 'text-slate-400' :
                      'text-amber-700'
                    }`} />
                  ) : (
                    <span className="text-slate-500">#{trader.rank}</span>
                  )}
                </td>
                <td className="px-6 py-4 font-medium">{trader.name}</td>
                <td className="px-6 py-4 text-right text-green-400">+{trader.return}%</td>
                <td className="px-6 py-4 text-right">{trader.sharpe}</td>
                <td className="px-6 py-4 text-right">{trader.followers.toLocaleString()}</td>
                <td className="px-6 py-4 text-right font-medium text-amber-400">
                  {trader.prize}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
