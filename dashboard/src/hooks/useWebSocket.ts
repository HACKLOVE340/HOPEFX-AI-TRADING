import { useEffect, useState, useCallback } from 'react'
import { useStore } from '../store/useStore'

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [latency, setLatency] = useState(0)
  const [socket, setSocket] = useState<WebSocket | null>(null)
  const setPrice = useStore((state) => state.setPrice)
  const setAccount = useStore((state) => state.setAccount)
  const setWsStatus = useStore((state) => state.setWsStatus)
  const setHeartbeat = useStore((state) => state.setHeartbeat)

  useEffect(() => {
    // VITE_WS_URL takes precedence; fall back to a relative URL derived from
    // the current page origin so the dashboard works behind any reverse proxy.
    const wsUrl = import.meta.env.VITE_WS_URL ||
      `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
    const ws = new WebSocket(wsUrl)

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
      const now = Date.now()

      switch (data.type) {
        case 'pong':
          setLatency(now - new Date(data.timestamp).getTime())
          setHeartbeat(now)
          break
        case 'tick':
          setPrice(data.data)
          break
        case 'order_fill':
          // positions updated via REST poll
          break
        case 'prediction':
          // signals updated via REST poll
          break
        case 'equity_update':
          setAccount(data.data)
          break
        case 'ws_status':
          setWsStatus(data.status)
          break
      }
    }

    setSocket(ws)

    return () => {
      ws.close()
    }
  }, [setPrice, setAccount, setWsStatus, setHeartbeat])

  const sendCommand = useCallback((command: object) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(command))
    }
  }, [socket])

  return { connected, latency, sendCommand }
}
