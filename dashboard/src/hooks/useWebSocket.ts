import { useEffect, useState, useCallback } from 'react'
import { useStore } from '../store/useStore'

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [latency, setLatency] = useState(0)
  const [socket, setSocket] = useState<WebSocket | null>(null)
  const addTick = useStore((state) => state.addTick)
  const updateEquity = useStore((state) => state.updateEquity)

  useEffect(() => {
    const ws = new WebSocket(import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws')

    ws.onopen = () => {
      setConnected(true)
      // Send heartbeat
      setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    ws.onclose = () => {
      setConnected(false)
      // Reconnect logic
      setTimeout(() => window.location.reload(), 5000)
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      
      switch (data.type) {
        case 'pong':
          setLatency(Date.now() - new Date(data.timestamp).getTime())
          break
        case 'tick':
          addTick(data.data)
          break
        case 'order_fill':
          // Update positions
          break
        case 'prediction':
          // Update ML signals
          break
        case 'equity_update':
          updateEquity(data.data.equity)
          break
      }
    }

    setSocket(ws)

    return () => {
      ws.close()
    }
  }, [addTick, updateEquity])

  const sendCommand = useCallback((command: object) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(command))
    }
  }, [socket])

  return { connected, latency, sendCommand }
}
