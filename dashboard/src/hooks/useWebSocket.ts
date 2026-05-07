/**
 * useWebSocket
 *
 * Manages the /ws/live connection lifecycle:
 * - Sends auth token immediately after connect
 * - Handles all server message types including no_live_feed
 * - Exponential back-off reconnect (no page reload)
 * - Tracks no_live_feed state so the UI can show a banner
 * - Dispatches depth, order, and position updates to the store
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { useStore } from '../store/useStore'

const BASE_RECONNECT_MS = 1_000
const MAX_RECONNECT_MS  = 30_000
const PING_INTERVAL_MS  = 25_000

export interface WsHookResult {
  connected: boolean
  latency: number
  noLiveFeed: boolean
  noLiveFeedMessage: string
  sendCommand: (cmd: object) => void
}

export function useWebSocket(): WsHookResult {
  const [connected, setConnected]                 = useState(false)
  const [latency, setLatency]                     = useState(0)
  const [noLiveFeed, setNoLiveFeed]               = useState(false)
  const [noLiveFeedMessage, setNoLiveFeedMessage] = useState('')

  const socketRef      = useRef<WebSocket | null>(null)
  const pingTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectDelay = useRef(BASE_RECONNECT_MS)
  const pingAt         = useRef(0)
  const unmounted      = useRef(false)

  const setPrice          = useStore((s) => s.setPrice)
  const setAccount        = useStore((s) => s.setAccount)
  const addSignal         = useStore((s) => s.addSignal)
  const setWsStatus       = useStore((s) => s.setWsStatus)
  const setHeartbeat      = useStore((s) => s.setHeartbeat)
  const upsertPosition    = useStore((s) => s.upsertPosition)
  const removePosition    = useStore((s) => s.removePosition)
  const setPositions      = useStore((s) => s.setPositions)
  const upsertOrder       = useStore((s) => s.upsertOrder)
  const removeOrder       = useStore((s) => s.removeOrder)
  const setDepth          = useStore((s) => s.setDepth)
  const updatePositionPrice = useStore((s) => s.updatePositionPrice)
  const token             = useStore((s) => s.token)

  const connect = useCallback(() => {
    if (unmounted.current) return

    const wsUrl =
      (import.meta.env.VITE_WS_URL as string | undefined) ||
      `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/live`

    setWsStatus('connecting')
    const ws = new WebSocket(wsUrl)
    socketRef.current = ws

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return }
      reconnectDelay.current = BASE_RECONNECT_MS
      setConnected(true)
      setWsStatus('connected')

      if (token) {
        ws.send(JSON.stringify({ type: 'auth', token: `Bearer ${token}` }))
      }

      ws.send(JSON.stringify({
        type: 'subscribe',
        channels: ['prices', 'signals', 'account', 'positions', 'orders', 'depth'],
      }))

      if (pingTimerRef.current) clearInterval(pingTimerRef.current)
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          pingAt.current = Date.now()
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL_MS)
    }

    ws.onclose = () => {
      if (unmounted.current) return
      setConnected(false)
      setWsStatus('disconnected')
      if (pingTimerRef.current) {
        clearInterval(pingTimerRef.current)
        pingTimerRef.current = null
      }
      const delay = reconnectDelay.current
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_MS)
      reconnectTimer.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      setWsStatus('error')
      ws.close()
    }

    ws.onmessage = (event) => {
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(event.data as string)
      } catch {
        return
      }

      const type = msg.type as string

      switch (type) {
        // ── Price feed ──────────────────────────────────────────────────────
        case 'price_tick': {
          const tick = msg.data as Parameters<typeof setPrice>[0]
          if (tick?.symbol) {
            setNoLiveFeed(false)
            setPrice(tick)
            // Keep position P&L live
            updatePositionPrice(tick.symbol, tick.mid ?? tick.bid)
          }
          break
        }

        // ── No live feed warning ────────────────────────────────────────────
        case 'no_live_feed': {
          setNoLiveFeed(true)
          setNoLiveFeedMessage(
            (msg.message as string) ||
            'No live broker connection. Connect a broker in Settings.',
          )
          break
        }

        // ── Signals ─────────────────────────────────────────────────────────
        case 'signal': {
          const signal = msg.data as Parameters<typeof addSignal>[0]
          if (signal?.id) addSignal(signal)
          break
        }

        // ── Account metrics ─────────────────────────────────────────────────
        case 'account_update': {
          const account = msg.data as Parameters<typeof setAccount>[0]
          if (account) setAccount(account)
          break
        }

        // ── Positions ───────────────────────────────────────────────────────
        case 'position_update': {
          const pos = msg.data as Parameters<typeof upsertPosition>[0]
          if (pos?.id) upsertPosition(pos)
          break
        }
        case 'position_closed': {
          const id = (msg.data as { id: string })?.id
          if (id) removePosition(id)
          break
        }
        case 'positions_snapshot': {
          const positions = msg.data as Parameters<typeof setPositions>[0]
          if (Array.isArray(positions)) setPositions(positions)
          break
        }

        // ── Orders ──────────────────────────────────────────────────────────
        case 'order_update': {
          const order = msg.data as Parameters<typeof upsertOrder>[0]
          if (order?.id) upsertOrder(order)
          break
        }
        case 'order_cancelled': {
          const id = (msg.data as { id: string })?.id
          if (id) removeOrder(id)
          break
        }

        // ── Order book depth ────────────────────────────────────────────────
        case 'depth_update': {
          const depth = msg.data as Parameters<typeof setDepth>[0]
          if (depth?.symbol) setDepth(depth)
          break
        }

        // ── Heartbeat / pong ────────────────────────────────────────────────
        case 'heartbeat': {
          setHeartbeat(Date.now())
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
          break
        }
        case 'pong': {
          if (pingAt.current > 0) {
            setLatency(Date.now() - pingAt.current)
            pingAt.current = 0
          }
          setHeartbeat(Date.now())
          break
        }

        // ── Auth responses ──────────────────────────────────────────────────
        case 'auth_ok':
          break
        case 'error': {
          const code = msg.code as string
          if (code === 'AUTH_FAILED' || code === 'AUTH_REQUIRED') {
            setWsStatus('error')
          }
          break
        }

        // ── Legacy message types ─────────────────────────────────────────────
        case 'tick':
          if (msg.data) {
            setPrice(msg.data as Parameters<typeof setPrice>[0])
          }
          break
        case 'equity_update':
        case 'account':
          if (msg.data) setAccount(msg.data as Parameters<typeof setAccount>[0])
          break

        default:
          break
      }
    }
  }, [
    token, setPrice, setAccount, addSignal, setWsStatus, setHeartbeat,
    upsertPosition, removePosition, setPositions, upsertOrder, removeOrder,
    setDepth, updatePositionPrice,
  ])

  useEffect(() => {
    unmounted.current = false
    connect()
    return () => {
      unmounted.current = true
      if (pingTimerRef.current)   clearInterval(pingTimerRef.current)
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      socketRef.current?.close()
    }
  }, [connect])

  const sendCommand = useCallback((cmd: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(cmd))
    }
  }, [])

  return { connected, latency, noLiveFeed, noLiveFeedMessage, sendCommand }
}
