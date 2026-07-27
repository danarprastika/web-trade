'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/api'

interface UserProfile {
  id: number
  email: string
  username: string
  is_active: boolean
  is_verified: boolean
  created_at: string
}

interface Position {
  id: number
  asset_id: number
  side: string
  quantity: number
  avg_entry_price: number
  current_price: number
  unrealized_pnl: number
  realized_pnl: number
}

interface Trade {
  id: number
  asset_id: number
  side: string
  quantity: number
  price: number
  pnl: number
  executed_at: string
}

interface Portfolio {
  balance: number
  total_unrealized_pnl: number
  total_realized_pnl: number
  portfolio_value: number
  open_positions_count: number
}

interface DashboardState {
  user: UserProfile | null
  portfolio: Portfolio | null
  positions: Position[]
  trades: Trade[]
  loading: boolean
  error: string | null
}

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState>({
    user: null,
    portfolio: null,
    positions: [],
    trades: [],
    loading: true,
    error: null,
  })
  const [authError, setAuthError] = useState(false)

  useEffect(() => {
    loadDashboard()
  }, [])

  async function loadDashboard() {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const profileRes = await apiFetch('/api/v1/auth/me')
      if (profileRes.status === 401) {
        setAuthError(true)
        return
      }
      const user = await profileRes.json()

      const dashRes = await apiFetch('/api/v1/dashboard/summary')
      const dashData = await dashRes.json()

      setState({
        user,
        portfolio: dashData.portfolio,
        positions: dashData.open_positions,
        trades: dashData.recent_trades,
        loading: false,
        error: null,
      })
    } catch (err) {
      setState({
        user: null,
        portfolio: null,
        positions: [],
        trades: [],
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load dashboard',
      })
    }
  }

  if (authError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in required</h1>
          <p className="text-sm text-muted-foreground">Please sign in to view your dashboard</p>
          <Button asChild>
            <Link href="/login">Sign in</Link>
          </Button>
        </div>
      </div>
    )
  }

  if (state.loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-muted-foreground">Loading dashboard...</p>
      </div>
    )
  }

  if (state.error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Error</h1>
          <p className="text-sm text-red-400">{state.error}</p>
          <Button onClick={loadDashboard}>Retry</Button>
        </div>
      </div>
    )
  }

  const user = state.user
  const portfolio = state.portfolio

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <div className="flex items-center gap-4">
            <Link href="/strategies" className="text-sm text-muted-foreground hover:underline">
              Strategies
            </Link>
            <Link href="/watchlist" className="text-sm text-muted-foreground hover:underline">
              Watchlist
            </Link>
            <Button asChild variant="ghost" size="sm">
              <Link href="/login">Sign out</Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8 space-y-8">
        <section className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border p-6">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Profile</h2>
            {user ? (
              <div className="mt-4 space-y-2">
                <div>
                  <p className="text-xs text-muted-foreground">Username</p>
                  <p className="font-mono font-medium">{user.username}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Email</p>
                  <p className="font-mono font-medium">{user.email}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Status</p>
                  <p className="font-medium">{user.is_verified ? 'Verified' : 'Unverified'}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Member since</p>
                  <p className="font-medium">{new Date(user.created_at).toLocaleDateString()}</p>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">No profile data available.</p>
            )}
          </div>

          <div className="rounded-lg border p-6">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Portfolio Value</h2>
            {portfolio ? (
              <div className="mt-4 space-y-2">
                <div>
                  <p className="text-xs text-muted-foreground">Total Value</p>
                  <p className="text-2xl font-bold">${portfolio.portfolio_value.toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Cash Balance</p>
                  <p className="font-mono">${portfolio.balance.toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Unrealized P&L</p>
                  <p className={`font-mono ${portfolio.total_unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {portfolio.total_unrealized_pnl >= 0 ? '+' : ''}{portfolio.total_unrealized_pnl.toFixed(2)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Realized P&L</p>
                  <p className={`font-mono ${portfolio.total_realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {portfolio.total_realized_pnl >= 0 ? '+' : ''}{portfolio.total_realized_pnl.toFixed(2)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">Belum ada posisi.</p>
            )}
          </div>
        </section>

        <section className="rounded-lg border p-6">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Open Positions</h2>
          {state.positions.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Asset</th>
                    <th className="pb-2 font-medium">Side</th>
                    <th className="pb-2 font-medium">Quantity</th>
                    <th className="pb-2 font-medium">Entry Price</th>
                    <th className="pb-2 font-medium">Current Price</th>
                    <th className="pb-2 font-medium">Unrealized P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {state.positions.map((p) => (
                    <tr key={p.id} className="border-b last:border-0">
                      <td className="py-2 font-mono">#{p.asset_id}</td>
                      <td className="py-2">{p.side}</td>
                      <td className="py-2 font-mono">{p.quantity.toFixed(4)}</td>
                      <td className="py-2 font-mono">${p.avg_entry_price.toFixed(2)}</td>
                      <td className="py-2 font-mono">${p.current_price.toFixed(2)}</td>
                      <td className={`py-2 font-mono ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="mt-4">
              <p className="text-sm text-muted-foreground">Belum ada posisi terbuka.</p>
            </div>
          )}
        </section>

        <section className="rounded-lg border p-6">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Recent Trades</h2>
          {state.trades.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Time</th>
                    <th className="pb-2 font-medium">Asset</th>
                    <th className="pb-2 font-medium">Side</th>
                    <th className="pb-2 font-medium">Quantity</th>
                    <th className="pb-2 font-medium">Price</th>
                    <th className="pb-2 font-medium">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {state.trades.map((t) => (
                    <tr key={t.id} className="border-b last:border-0">
                      <td className="py-2 text-xs">{new Date(t.executed_at).toLocaleString()}</td>
                      <td className="py-2 font-mono">#{t.asset_id}</td>
                      <td className="py-2">{t.side}</td>
                      <td className="py-2 font-mono">{t.quantity.toFixed(4)}</td>
                      <td className="py-2 font-mono">${t.price.toFixed(2)}</td>
                      <td className={`py-2 font-mono ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="mt-4">
              <p className="text-sm text-muted-foreground">Tidak ada trade terbaru.</p>
            </div>
          )}
        </section>

        <p className="text-xs text-muted-foreground">
          QuantX AI is in paper-trading mode. No real money or live trading is active.
        </p>
      </main>
    </div>
  )
}
