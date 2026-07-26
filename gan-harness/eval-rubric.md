# QuantX AI — Sprint 1 Evaluation Rubric

## Testable Pass/Fail Criteria

### Criterion 1: Migration from Empty Database
- **Command:** `cd backend && alembic upgrade head`
- **Database:** PostgreSQL running on localhost:5432, empty database `quantx_dev`
- **Pass:** Command exits 0, tables `users`, `trading_accounts`, `assets`, `alembic_version` exist
- **Pass:** Running `alembic upgrade head` a second time is idempotent (no errors)
- **Fail:** Any SQL error, missing table, or duplicate constraint violation

### Criterion 2: User Registration → Login → Valid JWT
- **Test 1:** `POST /api/v1/auth/register` with valid email, username, password, password_confirm
  - Returns 201
  - Response contains user id, email (NOT password hash)
- **Test 2:** `POST /api/v1/auth/login` with same email/password
  - Returns 200
  - Response contains `access_token`, `refresh_token`
- **Test 3:** `GET /api/v1/auth/me` with `Authorization: Bearer <access_token>`
  - Returns 200
  - Response contains user data matching registered user
- **Test 4:** Invalid password returns 401
- **Test 5:** Duplicate email returns 400 with appropriate error
- **Pass:** All 5 tests pass via actual pytest execution (not code reading)
- **Fail:** Any test fails, or tests were written but not executed

### Criterion 3: GitHub Actions Green on Latest Commit
- **Check:** Latest commit triggers GitHub Actions workflow
- **Jobs:**
  - `lint-backend`: `ruff check .` passes
  - `format-backend`: `ruff format --check .` passes
  - `test-backend`: `pytest` passes with coverage >= 80%
  - `lint-frontend`: `npm run lint` passes
  - `test-frontend`: `npm test` passes
- **Pass:** All jobs show green on the commit checked out for this evaluation
- **Fail:** Any job red, skipped, or not present

### Criterion 4: Health Check Detects Real Database Failure
- **Test 1:** `GET /health/ready` with database connected
  - Returns 200
  - JSON: `{"status": "healthy", "checks": {"database": {"status": "healthy", "latency_ms": <number>}}}`
- **Test 2:** Stop PostgreSQL, then call `GET /health/ready`
  - Returns 503 (not 200)
  - JSON: `{"status": "unhealthy", "checks": {"database": {"status": "unhealthy", "message": ...}}}`
  - Pass if the word "database" appears in the response and status is NOT "healthy"
- **Pass:** Both tests pass via actual pytest + Docker/process management
- **Fail:** Health endpoint returns 200 when DB is down, or returns static "ok" without real DB call

## Scoring
- Each criterion is binary: PASS or FAIL
- Sprint 1 is complete only when ALL 4 criteria pass
- A test that compiles but is not executed does NOT count as PASS

## Anti-Patterns (Automatic Failures)
- Using `create_all` in production code instead of Alembic migrations
- Storing JWT in localStorage instead of httpOnly cookies
- Health endpoint returning hardcoded `{"status": "ok"}`
- Placeholder tests like `pass` or `assert True`
- Hardcoded secrets in source code
- Missing input validation on registration (email format, password length)
