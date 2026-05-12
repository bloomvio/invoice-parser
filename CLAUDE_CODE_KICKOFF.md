# Claude Code Kickoff Prompt

Copy everything below the line into Claude Code as your first message.

---

I want to build an invoice parsing service. The full spec is in `INVOICE_PARSER_SPEC.md` at the repo root — read it before doing anything else.

## Before you write any code

1. **Read `INVOICE_PARSER_SPEC.md` end to end.** Pay particular attention to §0 (core principles) and §19 (build order). These are non-negotiable.

2. **Confirm you understand the architecture by answering these three questions in plain English:**
   - Why are we using `DetectDocumentText` and explicitly NOT `AnalyzeExpense`?
   - What does the cross-validation step at stage 6 protect against, and why does it require two *independent* reads?
   - Why is the semantic pick (stage 5) constrained to OCR token IDs instead of free text?
   
   If your answers don't match the spec's reasoning, stop and re-read §0 and §10.

3. **List the prerequisites I need to have ready before you can run anything end-to-end.** At minimum: AWS account with Textract access, Google Cloud API key for Gemini, Neon Postgres connection string, Google service account JSON if I want the Drive source. Tell me which are blocking for which phases.

## Build constraints

- **Phase by phase per §19.** Do not jump ahead. After each phase: stop, summarize what works, what's tested, and what's next. Wait for my "continue" before starting the next phase.
- **Windows + PowerShell is my dev environment.** All commands you suggest must work in PowerShell. No bash-only syntax unless it's running inside a Dockerfile or CI.
- **Surgical edits only.** When you modify a file, use targeted edits with clear before/after. Never rewrite a whole file because one function changed.
- **Pin every dependency** in `pyproject.toml` with exact versions. No floating versions.
- **`.env` stays gitignored.** Provide a `.env.example` with every variable from §4 of the spec, with placeholder values and one-line comments explaining each.
- **No premature optimization.** No caching layers, no Redis, no Celery, no microservices beyond what the spec defines. The spec already made the simplicity-vs-correctness tradeoffs.

## Phase 1 — what I want from you first

Per §19 item 1: skeleton only.

Deliverables:
- Repo layout exactly matching §3
- `pyproject.toml` with all dependencies pinned (use `uv` if available, else poetry)
- `Dockerfile` that builds cleanly
- `railway.json` with both `api` and `worker` service definitions
- `pydantic-settings` config in `src/invoice_parser/config.py` loading all env vars from §4
- FastAPI app at `src/invoice_parser/api/main.py` with a single `GET /health` endpoint returning `{"status": "ok"}`
- SQLAlchemy models in `src/invoice_parser/db/models.py` for `api_keys`, `jobs`, `invoices` per §5
- Alembic initialized with the first migration creating those three tables
- `scripts/create_api_key.py` per §13
- `.env.example`
- Brief `README.md` covering local setup (PowerShell commands), running migrations, and running the API locally

Do NOT yet build:
- Any worker logic
- Any OCR/LLM integration
- Any pipeline stages
- The ingest, render, segment, etc. modules

At the end of phase 1 I should be able to:
1. Clone the repo, install deps, copy `.env.example` to `.env` with my real values
2. Run `alembic upgrade head` against my Neon DB and see the tables created
3. Run `python scripts/create_api_key.py "test key"` and get a real API key printed once
4. Run `uvicorn invoice_parser.api.main:app --reload` and curl `/health` successfully
5. Build the Dockerfile cleanly: `docker build -t invoice-parser .`

When you're done with phase 1, stop and ask me to verify the five things above before you touch phase 2.

## Communication style

- Be direct. Don't ask permission to use sensible defaults — make the call and tell me.
- If you hit a real ambiguity in the spec, flag it and propose an answer. Don't just ask.
- After each file you create, give me a one-line summary of what it does. Don't paste the whole file content back at me.
- Tell me which spec section you're implementing as you go (e.g., "§5 — adding the jobs table model").
- If you change something the spec specified differently, call it out explicitly: "Deviating from §X because Y."

Begin.
