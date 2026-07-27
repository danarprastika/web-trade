# QuantX AI — Sprint 4 Specification (Fase 2: Intelligence Layer)

## Vision Summary
QuantX AI is an enterprise-grade AI trading platform. Fase 2 delivers the Intelligence layer: News Intelligence and the first AI engine (Technical Analysis). These modules feed strategy decisions and dashboard context.

## Users
- **Primary:** Retail/algorithmic traders who need news context and technical signals for strategy decisions
- **Secondary:** Developers extending AI modules

## Scope — In (Sprint 4)
1. **News Intelligence:** backend model/service/router + frontend `/news` page
2. **Technical Analysis Engine:** basic indicator calculation service + API
3. **Dashboard integration:** news widget + analysis widget on `/dashboard`

## Scope — Out (Sprint 4)
- Advanced AI engines (Sentiment, Whale Tracking, Pattern Recognition)
- News sentiment scoring
- Backtesting framework
- Market Intelligence (deferred to Sprint 5)

## Architecture
Extends existing modular monolith. New modules:
- `app/models/news.py` — `NewsSource`, `NewsArticle`
- `app/services/news_service.py` — fetch, store, query news
- `app/routers/news.py` — `/api/v1/news` endpoints
- `app/services/analysis_service.py` — technical indicator calculations (SMA, EMA, RSI)
- `app/routers/analysis.py` — `/api/v1/analysis` endpoints

Frontend:
- `frontend/src/app/news/page.tsx`
- `frontend/src/components/news/` — NewsFeed, NewsCard
- `frontend/src/components/analysis/` — IndicatorPanel
- Extend `dashboard/page.tsx` with NewsWidget and AnalysisWidget

## Vertical Slices

### Slice 1: News Intelligence Backend
- Database models: `NewsSource` (id, name, url, active), `NewsArticle` (id, source_id, title, url, summary, published_at, created_at)
- Alembic migration: `004_add_news.py`
- Service: `NewsService` with CRUD + fetch_from_source (mock real fetch for now, structure ready for real RSS/API)
- Router: `/api/v1/news`
  - `GET /` — list articles with pagination
  - `GET /{article_id}` — single article
  - `POST /` — admin ingest article
  - `GET /sources` — list active news sources
- Tests: 12+ tests covering CRUD, pagination, 404s

### Slice 2: News Intelligence Frontend
- Page: `/news` with feed layout
- Components:
  - `NewsFeed` — paginated list of news cards
  - `NewsCard` — title, source, timestamp, link
- API client integration with existing `fetch` wrapper
- Dark-mode styling matching existing design tokens
- Tests: component tests for NewsFeed and NewsCard

### Slice 3: Technical Analysis Backend
- Service: `AnalysisService`
  - `calculate_sma(prices, period)` — Simple Moving Average
  - `calculate_ema(prices, period)` — Exponential Moving Average
  - `calculate_rsi(prices, period)` — Relative Strength Index
  - `get_signals(symbol)` — aggregate signal from indicators
- Router: `/api/v1/analysis`
  - `GET /indicators/{symbol}` — latest indicators for symbol
  - `GET /signals/{symbol}` — buy/sell/hold signal summary
- Data source: reads from existing market data (can use recent cached prices)
- Tests: 10+ tests with known price series and expected indicator values

### Slice 4: Dashboard Intelligence Widgets
- Extend `GET /api/v1/dashboard` to include:
  - `latest_news` — top 5 recent articles
  - `technical_signals` — signals for watchlist symbols
- Frontend: add `NewsWidget` and `AnalysisWidget` to dashboard grid
- Tests: dashboard endpoint returns new fields

## Design Direction (Frontend)
- **Purpose:** Information density for traders monitoring news and technical signals
- **Audience:** Same trader/quant audience as dashboard
- **Tone:** Industrial precision, calm, data-dense
- **Memorable detail:** Compact cards with subtle accent colors for signal strength (green/red muted, not neon)
- **Constraints:** shadcn/ui, TailwindCSS, dark mode default, no decorative gradients, maintain existing spacing/typography tokens

## Commit Strategy
Conventional commits:
- `feat(backend): add news models, service, and router`
- `feat(backend): add Alembic migration for news tables`
- `feat(backend): add technical analysis service with SMA/EMA/RSI`
- `feat(backend): add analysis router and dashboard enrichment`
- `feat(frontend): add news page and components`
- `feat(frontend): add analysis widget to dashboard`
- `test: add news and analysis tests`
- `docs: update RELEASE-PLAN and BUILD-REPORT for Sprint 4`
