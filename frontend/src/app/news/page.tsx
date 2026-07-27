'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { NewsCard } from '@/components/news/NewsCard'
import { apiFetch } from '@/lib/api'

interface NewsArticle {
  id: number
  source_id: number
  title: string
  url: string
  summary: string | null
  published_at: string | null
  created_at: string
}

interface NewsListResponse {
  items: NewsArticle[]
  total: number
  page: number
  page_size: number
}

export default function NewsPage() {
  const [articles, setArticles] = useState<NewsArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [authError, setAuthError] = useState(false)

  useEffect(() => {
    loadNews()
  }, [])

  async function loadNews() {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch('/api/v1/news/')
      if (res.status === 401) {
        setAuthError(true)
        return
      }
      const data: NewsListResponse = await res.json()
      setArticles(data.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load news')
    } finally {
      setLoading(false)
    }
  }

  if (authError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in required</h1>
          <p className="text-sm text-muted-foreground">Please sign in to view news</p>
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
        <p className="text-muted-foreground">Loading news...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">News Intelligence</h1>
          <Button asChild variant="ghost" size="sm">
            <Link href="/dashboard">Dashboard</Link>
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

        {articles.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center">
            <p className="text-muted-foreground">No news articles yet. Check back later for market updates.</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {articles.map((article) => (
              <NewsCard key={article.id} article={article} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
