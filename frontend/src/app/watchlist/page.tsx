'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useMarketData } from '@/hooks/use-market-data'
import { apiFetch } from '@/lib/api'

interface AssetWatch {
  id: number
  asset: {
    id: number
    symbol: string
    name: string
    asset_class: string
    exchange: string | null
    currency: string
    is_active: boolean
  }
  created_at: string
}

export default function WatchlistPage() {
  const [watchlist, setWatchlist] = useState<AssetWatch[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [symbolQuery, setSymbolQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [authError, setAuthError] = useState(false)

  const symbols = watchlist.map((w) => w.asset.symbol.toLowerCase())
  const { state: wsState, prices } = useMarketData(symbols)

  useEffect(() => {
    loadWatchlist()
  }, [])

  async function loadWatchlist() {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch('/api/v1/watchlist/')
      if (res.status === 401) {
        setAuthError(true)
        return
      }
      const data = await res.json()
      setWatchlist(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load watchlist')
    } finally {
      setLoading(false)
    }
  }

  async function addAsset(e: React.FormEvent) {
    e.preventDefault()
    if (!symbolQuery.trim()) return
    setAdding(true)
    setError(null)
    try {
      const searchRes = await fetch(`https://api.binance.com/api/v3/ticker/24hr?symbol=${symbolQuery.trim().toUpperCase()}`)
      if (!searchRes.ok) {
        setError('Asset not found on exchange')
        setAdding(false)
        return
      }
      const ticker = await searchRes.json()
      const symbol = ticker.symbol.toLowerCase()

      const assetRes = await apiFetch('/api/v1/assets/', {
        method: 'POST',
        body: JSON.stringify({
          symbol,
          name: ticker.symbol,
          asset_class: 'crypto',
          exchange: 'binance',
          currency: 'USD',
        }),
      })
      if (!assetRes.ok) {
        const body = await assetRes.json().catch(() => ({}))
        setError(body.detail || 'Failed to create asset')
        setAdding(false)
        return
      }
      const asset = await assetRes.json()

      const addRes = await apiFetch('/api/v1/watchlist/', {
        method: 'POST',
        body: JSON.stringify({ asset_id: asset.id }),
      })
      if (!addRes.ok) {
        const body = await addRes.json().catch(() => ({}))
        setError(body.detail || 'Failed to add to watchlist')
        setAdding(false)
        return
      }
      await loadWatchlist()
      setSymbolQuery('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add asset')
    } finally {
      setAdding(false)
    }
  }

  async function removeAsset(assetId: number) {
    try {
      const res = await apiFetch(`/api/v1/watchlist/${assetId}`, { method: 'DELETE' })
      if (res.status === 401) {
        setAuthError(true)
        return
      }
      await loadWatchlist()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove asset')
    }
  }

  if (authError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in required</h1>
          <p className="text-sm text-muted-foreground">Please sign in to view your watchlist</p>
          <Button asChild>
            <Link href="/login">Sign in</Link>
          </Button>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground">Loading watchlist...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Watchlist</h1>
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 ${wsState === 'connected' ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
              {wsState === 'connected' ? 'Live' : wsState === 'connecting' ? 'Connecting' : 'Offline'}
            </span>
            <Button asChild variant="ghost" size="sm">
              <Link href="/dashboard">Dashboard</Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <form onSubmit={addAsset} className="mb-6 flex gap-3">
          <Input
            value={symbolQuery}
            onChange={(e) => setSymbolQuery(e.target.value)}
            placeholder="Add asset (e.g. BTCUSDT)"
            className="max-w-xs"
          />
          <Button type="submit" disabled={adding || !symbolQuery.trim()}>
            {adding ? 'Adding...' : 'Add'}
          </Button>
        </form>

        {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

        {watchlist.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center">
            <p className="text-muted-foreground">Your watchlist is empty. Add an asset above to track live prices.</p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {watchlist.map((item) => {
              const price = prices[item.asset.symbol.toLowerCase()]
              return (
                <div key={item.id} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-mono text-sm font-medium uppercase">{item.asset.symbol}</p>
                      <p className="text-xs text-muted-foreground">{item.asset.name}</p>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => removeAsset(item.asset.id)}>
                      Remove
                    </Button>
                  </div>
                  <div className="mt-3">
                    {price ? (
                      <div>
                        <p className="text-2xl font-semibold">${price.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                        <p className="text-xs text-muted-foreground">
                          O: {price.open.toLocaleString()} H: {price.high.toLocaleString()} L: {price.low.toLocaleString()}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Vol: {price.volume.toLocaleString()} @ {new Date(price.timestamp).toLocaleTimeString()}
                        </p>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Awaiting price...</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
