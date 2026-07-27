'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/api'

interface Strategy {
  id: number
  name: string
  strategy_type: string
  asset_id: number
  status: string
  is_running: boolean
  short_window: number
  long_window: number
  parameters: Record<string, unknown>
  created_at: string
}

interface StrategiesState {
  strategies: Strategy[]
  loading: boolean
  error: string | null
}

export default function StrategiesPage() {
  const [state, setState] = useState<StrategiesState>({
    strategies: [],
    loading: true,
    error: null,
  })
  const [authError, setAuthError] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    asset_id: 1,
    strategy_type: 'moving_average_crossover',
    short_window: 5,
    long_window: 20,
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    loadStrategies()
  }, [])

  async function loadStrategies() {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const res = await apiFetch('/api/v1/strategies/')
      if (res.status === 401) {
        setAuthError(true)
        return
      }
      const strategies = await res.json()
      setState({ strategies, loading: false, error: null })
    } catch (err) {
      setState({
        strategies: [],
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load strategies',
      })
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await apiFetch('/api/v1/strategies/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Failed to create strategy' }))
        throw new Error(data.detail || 'Failed to create strategy')
      }
      setShowForm(false)
      setFormData({ name: '', asset_id: 1, strategy_type: 'moving_average_crossover', short_window: 5, long_window: 20 })
      await loadStrategies()
    } catch (err) {
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : 'Unknown error' }))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleStart(id: number) {
    try {
      const res = await apiFetch(`/api/v1/strategies/${id}/start`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Failed to start strategy' }))
        throw new Error(data.detail || 'Failed to start strategy')
      }
      await loadStrategies()
    } catch (err) {
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : 'Unknown error' }))
    }
  }

  async function handlePause(id: number) {
    try {
      const res = await apiFetch(`/api/v1/strategies/${id}/pause`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Failed to pause strategy' }))
        throw new Error(data.detail || 'Failed to pause strategy')
      }
      await loadStrategies()
    } catch (err) {
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : 'Unknown error' }))
    }
  }

  async function handleStop(id: number) {
    try {
      const res = await apiFetch(`/api/v1/strategies/${id}/stop`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Failed to stop strategy' }))
        throw new Error(data.detail || 'Failed to stop strategy')
      }
      await loadStrategies()
    } catch (err) {
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : 'Unknown error' }))
    }
  }

  async function handleDelete(id: number) {
    try {
      const res = await apiFetch(`/api/v1/strategies/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Failed to delete strategy' }))
        throw new Error(data.detail || 'Failed to delete strategy')
      }
      await loadStrategies()
    } catch (err) {
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : 'Unknown error' }))
    }
  }

  if (authError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in required</h1>
          <p className="text-sm text-muted-foreground">Please sign in to manage strategies</p>
          <Button asChild>
            <Link href="/login">Sign in</Link>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Strategies</h1>
          <div className="flex items-center gap-4">
            <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
              Dashboard
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

      <main className="mx-auto max-w-5xl px-6 py-8 space-y-6">
        {state.error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm text-red-400">
            {state.error}
            <button onClick={() => setState((s) => ({ ...s, error: null }))} className="ml-4 underline">
              Dismiss
            </button>
          </div>
        )}

        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Your Strategies</h2>
          <Button onClick={() => setShowForm(!showForm)}>
            {showForm ? 'Cancel' : 'New Strategy'}
          </Button>
        </div>

        {showForm && (
          <form onSubmit={handleCreate} className="rounded-lg border p-6 space-y-4">
            <h3 className="font-medium">Create Strategy</h3>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium">Name</label>
                <input
                  type="text"
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={formData.name}
                  onChange={(e) => setFormData((f) => ({ ...f, name: e.target.value }))}
                  placeholder="MA Crossover"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Asset ID</label>
                <input
                  type="number"
                  required
                  min="1"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={formData.asset_id}
                  onChange={(e) => setFormData((f) => ({ ...f, asset_id: parseInt(e.target.value) || 1 }))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Short Window</label>
                <input
                  type="number"
                  required
                  min="2"
                  max="200"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={formData.short_window}
                  onChange={(e) => setFormData((f) => ({ ...f, short_window: parseInt(e.target.value) || 5 }))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Long Window</label>
                <input
                  type="number"
                  required
                  min="5"
                  max="500"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={formData.long_window}
                  onChange={(e) => setFormData((f) => ({ ...f, long_window: parseInt(e.target.value) || 20 }))}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Creating...' : 'Create Strategy'}
              </Button>
            </div>
          </form>
        )}

        {state.loading ? (
          <p className="text-sm text-muted-foreground">Loading strategies...</p>
        ) : state.strategies.length === 0 ? (
          <div className="rounded-lg border p-8 text-center">
            <p className="text-sm text-muted-foreground">No strategies yet. Create your first strategy to get started.</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {state.strategies.map((s) => (
              <div key={s.id} className="rounded-lg border p-6">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-medium">{s.name}</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      Asset #{s.asset_id} &middot; {s.strategy_type} &middot; MA({s.short_window}, {s.long_window})
                    </p>
                  </div>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
                      s.is_running
                        ? 'bg-green-500/10 text-green-400'
                        : s.status === 'paused'
                        ? 'bg-yellow-500/10 text-yellow-400'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {s.is_running ? 'Running' : s.status}
                  </span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {!s.is_running ? (
                    <Button size="sm" onClick={() => handleStart(s.id)}>Start</Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => handlePause(s.id)}>Pause</Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => handleStop(s.id)}>Stop</Button>
                  <Button size="sm" variant="destructive" onClick={() => handleDelete(s.id)}>Delete</Button>
                </div>
              </div>
            ))}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          QuantX AI is in paper-trading mode. No real money or live trading is active.
        </p>
      </main>
    </div>
  )
}
