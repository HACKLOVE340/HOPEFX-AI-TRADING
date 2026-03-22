import { Wifi, WifiOff, Activity } from 'lucide-react'

interface Props {
  connected: boolean
  latency: number
}

export function ConnectionStatus({ connected, latency }: Props) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 bg-slate-800/50 rounded-lg">
      {connected ? (
        <>
          <Wifi className="w-4 h-4 text-green-400" />
          <div className="flex-1">
            <div className="text-sm font-medium text-green-400">Connected</div>
            <div className="text-xs text-slate-400">
              {latency < 50 ? 'Excellent' : latency < 100 ? 'Good' : 'Fair'} • {latency}ms
            </div>
          </div>
          <Activity className={`w-4 h-4 ${
            latency < 50 ? 'text-green-400' : 
            latency < 100 ? 'text-amber-400' : 'text-red-400'
          }`} />
        </>
      ) : (
        <>
          <WifiOff className="w-4 h-4 text-red-400" />
          <div className="flex-1">
            <div className="text-sm font-medium text-red-400">Disconnected</div>
            <div className="text-xs text-slate-400">Reconnecting...</div>
          </div>
        </>
      )}
    </div>
  )
}
