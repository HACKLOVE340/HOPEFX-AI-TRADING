import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface Tick {
  symbol: string
  bid: number
  ask: number
  timestamp: string
}

interface Position {
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  entryPrice: number
  unrealizedPnl: number
}

interface TradeState {
  ticks: Record<string, Tick>
  positions: Position[]
  equity: number
  addTick: (tick: Tick) => void
  updateEquity: (equity: number) => void
  setPositions: (positions: Position[]) => void
}

export const useStore = create<TradeState>()(
  persist(
    (set) => ({
      ticks: {},
      positions: [],
      equity: 100000,
      addTick: (tick) => 
        set((state) => ({
          ticks: { ...state.ticks, [tick.symbol]: tick }
        })),
      updateEquity: (equity) => set({ equity }),
      setPositions: (positions) => set({ positions }),
    }),
    {
      name: 'hopefx-storage',
    }
  )
)
