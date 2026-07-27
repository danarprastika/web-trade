# QuantX AI — Sprint 4 Evaluation Rubric

## Testable Pass/Fail Criteria

### Criterion 1: News CRUD and Pagination
- **Test 1:** `POST /api/v1/news/sources` with valid data → 201
- **Test 2:** `POST /api/v1/news` with valid article data → 201
- **Test 3:** `GET /api/v1/news` → 200, returns list with pagination fields
- **Test 4:** `GET /api/v1/news/{id}` → 200, returns correct article
- **Test 5:** `GET /api/v1/news/999999` → 404
- **Test 6:** `POST /api/v1/news` with invalid data → 422
- **Pass:** All 6 tests pass via actual pytest execution
- **Fail:** Any test fails or was not executed

### Criterion 2: Technical Analysis Indicators Are Numerically Correct
- **Test 1:** Given prices [10, 20, 30, 40, 50], SMA(3) last value = 40
- **Test 2:** Given prices [10, 20, 30, 40, 50], EMA(3) last value matches expected formula
- **Test 3:** Given prices with up/down sequence, RSI(2) returns value between 0 and 100
- **Test 4:** `GET /api/v1/analysis/indicators/{symbol}` returns dict with `sma`, `ema`, `rsi` keys
- **Test 5:** `GET /api/v1/analysis/signals/{symbol}` returns `signal` field with value `buy`|`sell`|`hold`
- **Pass:** All 5 tests pass with exact numeric assertions
- **Fail:** Any test fails, uses hardcoded stubs without real math, or was not executed

### Criterion 3: Dashboard Enriched with Intelligence Data
- **Test 1:** `GET /api/v1/dashboard` returns `latest_news` array with ≤ 5 items
- **Test 2:** `GET /api/v1/dashboard` returns `technical_signals` array
- **Test 3:** Frontend `/dashboard` renders without runtime errors and includes NewsWidget and AnalysisWidget
- **Pass:** Backend tests pass and frontend renders widgets
- **Fail:** Dashboard missing new fields, or frontend crashes

### Criterion 4: News Frontend Page Works
- **Test 1:** Navigate to `/news` → page loads, shows "News" heading
- **Test 2:** When backend has articles, NewsFeed renders ≥ 1 NewsCard
- **Test 3:** Clicking a NewsCard link opens article URL
- **Pass:** All 3 checks pass via Playwright or component test
- **Fail:** Page 500s, empty state is broken, or links are inert

### Criterion 5: GitHub Actions Green on Sprint 4 Commit
- **Jobs:**
  - `lint-backend`: `ruff check .` passes
  - `format-backend`: `ruff format --check .` passes
  - `test-backend`: `pytest` passes with new tests included
  - `lint-frontend`: `npm run lint` passes
- **Pass:** All jobs show green on Sprint 4 commit
- **Fail:** Any job red

## Scoring
- Each criterion is binary: PASS or FAIL
- Sprint 4 is complete only when ALL 5 criteria pass
- A test that compiles but is not executed does NOT count as PASS

## Anti-Patterns (Automatic Failures)
- Hardcoded indicator values instead of real math
- News articles stored as JSON blob without proper schema
- Frontend page using `any` types or broken accessibility
- Missing pagination on news list
- Dashboard widgets that render fake/placeholder data when API is empty
