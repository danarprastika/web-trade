'use client'

interface NewsArticle {
  id: number
  title: string
  url: string
  summary: string | null
  published_at: string | null
}

interface NewsCardProps {
  article: NewsArticle
}

function formatDate(iso: string | null): string {
  if (!iso) return 'Unknown date'
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function NewsCard({ article }: NewsCardProps) {
  return (
    <article className="rounded-lg border p-4 transition-colors hover:bg-muted/50">
      <a
        href={article.url}
        target="_blank"
        rel="noopener noreferrer"
        className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded"
      >
        <h2 className="font-semibold leading-tight hover:underline">{article.title}</h2>
      </a>
      {article.summary && (
        <p className="mt-2 text-sm text-muted-foreground line-clamp-2">{article.summary}</p>
      )}
      <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
        <time dateTime={article.published_at || undefined}>{formatDate(article.published_at)}</time>
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:underline"
        >
          Read more
        </a>
      </div>
    </article>
  )
}
