'use client'

import { useEffect, useRef, useState } from 'react'

export interface PriceTick {
  symbol: string
  price: number
  open: number
  high: number
  low: number
  volume: number
  timestamp: string
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected'

const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000]

export function useMarketData(symbols: string[]) {
  const [state, setState] = useState<ConnectionState>('disconnected')
  const [prices, setPrices] = useState<Record<string, PriceTick>>({})
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectIndexRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
    // reconnect only on mount/unmount; subscription changes send separate messages
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return
    }
    ws.send(JSON.stringify({ type: 'subscribe', symbols }))
  }, [symbols])

  function connect() {
    if (!mountedRef.current) return
    setState('connecting')
    setError(null)

    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
    const protocols: string[] = []
    if (token) {
      protocols.push(`token.${token}`)
    }

    let ws: WebSocket
    try {
      ws = new WebSocket(
        `${typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${typeof window !== 'undefined' ? window.location.host : 'localhost:3000'}/api/v1/market/ws`,
        protocols,
      )
    } catch (err) {
      setError('WebSocket not supported')
      setState('disconnected')
      return
    }

    ws.onopen = () => {
      if (!mountedRef.current) return
      setState('connected')
      reconnectIndexRef.current = 0
      ws.send(JSON.stringify({ type: 'subscribe', symbols }))
    }

    ws.onmessage = (event) => {
      if (!mountedRef.current) return
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'price') {
          setPrices((prev) => ({ ...prev, [msg.symbol]: msg }))
        } else if (msg.type === 'status') {
          if (!msg.connected && state !== 'connecting') {
            setError('Reconnecting to exchange...')
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      setError('Connection error')
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setState('disconnected')
      scheduleReconnect()
    }

    wsRef.current = ws
  }

  function scheduleReconnect() {
    if (!mountedRef.current) return
    const delay = RECONNECT_DELAYS[Math.min(reconnectIndexRef.current, RECONNECT_DELAYS.length - 1)]
    reconnectIndexRef.current += 1
    reconnectTimerRef.current = setTimeout(() => {
      connect()
    }, delay)
  }

  function reconnect() {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
    }
    reconnectIndexRef.current = 0
    if (wsRef.current) {
      wsRef.current.close()
    }
    connect()
  }

  return { state, prices, error, reconnect }
}
