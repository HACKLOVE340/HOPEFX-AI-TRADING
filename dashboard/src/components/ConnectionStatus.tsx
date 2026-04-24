import { Wifi, WifiOff, Activity, AlertTriangle } from 'lucide-react'

interface Props {
  connected: boolean
  latency: number
  noLiveFeed?: boolean
  noLiveFeedMessage?: string
}

export function ConnectionStatus({ connected, latency, noLiveFeed, noLiveFeedMessage }: Props) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 px-4 py-3 bg-slate-800/50 rounded-lg">
        {connected ? (
          <>
            <Wifi className="w-4 h-4 text-green-400 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-green-400">Connected</div>
              <div className="text-xs text-slate-400">
                {latency > 0
                  ? `${latency < 50 ? 'Excellent' : latency < 100 ? 'Good' : 'Fair'} · ${latency}ms`
                  : 'Live feed active'}
              </div>
            </div>
            <Activity className={`w-4 h-4 shrink-0 ${
              latency === 0    ? 'text-green-400' :
              latency < 50     ? 'text-green-400' :
              latency < 100    ? 'text-amber-400' : 'text-red-400'
            }`} />
          </>
        ) : (
          <>
            <WifiOff className="w-4 h-4 text-red-400 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-red-400">Disconnected</div>
              <div className="text-xs text-slate-400">Reconnecting…</div>
            </div>
          </>
        )}
      </div>

      {/* No live broker feed warning */}
      {connected && noLiveFeed && (
        <div className="flex items-start gap-2 px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{noLiveFeedMessage || 'No live broker connected. Configure a broker in Settings.'}</span>
        </div>
      )}
    </div>
  )
}
