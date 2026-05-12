# Invoice Parser

Hybrid OCR + Vision LLM invoice extraction service. Architecture: AWS Textract (OCR ground truth) + Gemini 2.5 Flash-Lite (semantic understanding) with cross-validation. Deployed on Railway (API + worker) with Neon Postgres.

---

## Local setup (PowerShell)

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Neon Postgres connection string
- AWS credentials with Textract access (needed for Phase 2+)
- Google API key for Gemini (needed for Phase 2+)

### 1. Install dependencies

```powershell
uv pip install -e ".[dev]"
```

### 2. Configure environment

```powershell
Copy-Item .env.example .env
# Edit .env and fill in DATABASE_URL at minimum
```

### 3. Run database migrations

```powershell
alembic upgrade head
```

### 4. Create an API key

```powershell
python scripts/create_api_key.py "my first key"
# Prints the raw key once — copy it somewhere safe
```

### 5. Run the API

```powershell
uvicorn invoice_parser.api.main:app --reload
```

Verify with:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected: `{ "status": "ok" }`

### 6. Build the Docker image

```powershell
docker build -t invoice-parser .
```

---

## Railway deployment

Two services from this repo, both using the Dockerfile:

| Service | Start command | Public |
|---|---|---|
| `api` | `uvicorn invoice_parser.api.main:app --host 0.0.0.0 --port $PORT` | Yes |
| `worker` | `python -m invoice_parser.worker.main` | No |

Attach the same volume (`/storage`) to both services. Share all env vars.

Run migrations before first deploy:

```powershell
railway run alembic upgrade head
```

---

## Project structure

```
src/invoice_parser/
  api/          FastAPI app, auth middleware, routes
  worker/       Poll loop and pipeline stages
  db/           SQLAlchemy models, session, queue helpers
  storage/      Local and R2 storage backends
  schema/       Canonical Invoice pydantic model
migrations/     Alembic migrations
scripts/        create_api_key.py, run_local.py
tests/          Unit + integration tests
```
