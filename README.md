# QuantX AI

Enterprise AI Trading Platform — Fase 0 (Foundation Layer).

## Stack
- Backend: FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL
- Frontend: Next.js, TypeScript, TailwindCSS, shadcn/ui
- Auth: JWT + refresh token (email login)

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 16+
- Docker & Docker Compose (optional)

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
# Edit .env with your DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend
pytest --cov
```

### CI/CD

GitHub Actions runs on every push: lint (ruff), typecheck (mypy), and tests (pytest).

### Architecture

See `docs/ARCHITECTURE.md` for ADRs and `docs/VISION.md` for product vision.
