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

interface ProfileState {
  user: UserProfile | null
  loading: boolean
  error: string | null
}

export default function DashboardPage() {
  const [state, setState] = useState<ProfileState>({ user: null, loading: true, error: null })
  const [authError, setAuthError] = useState(false)

  useEffect(() => {
    loadProfile()
  }, [])

  async function loadProfile() {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const res = await apiFetch('/api/v1/auth/me')
      if (res.status === 401) {
        setAuthError(true)
        return
      }
      const user = await res.json()
      setState({ user, loading: false, error: null })
    } catch (err) {
      setState({
        user: null,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load profile',
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
          <Button onClick={loadProfile}>Retry</Button>
        </div>
      </div>
    )
  }

  const user = state.user

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <div className="flex items-center gap-4">
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
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Portfolio</h2>
            <div className="mt-4">
              <p className="text-sm text-muted-foreground">Belum ada posisi.</p>
              <p className="text-xs text-muted-foreground mt-1">Paper trading tidak aktif saat ini.</p>
            </div>
          </div>
        </section>

        <section className="rounded-lg border p-6">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Open Positions</h2>
          <div className="mt-4">
            <p className="text-sm text-muted-foreground">Belum ada posisi.</p>
          </div>
        </section>

        <section className="rounded-lg border p-6">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">P&L</h2>
          <div className="mt-4">
            <p className="text-sm text-muted-foreground">Tidak ada data P&L saat ini.</p>
          </div>
        </section>

        <p className="text-xs text-muted-foreground">
          QuantX AI is in paper-trading mode. No real money or live trading is active.
        </p>
      </main>
    </div>
  )
}
