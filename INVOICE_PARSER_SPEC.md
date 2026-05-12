# Invoice Parser Service — Build Spec

**Purpose:** A hosted service that ingests invoice PDFs from a folder location (local path *or* Google Drive folder), extracts structured data using a hybrid OCR + Vision LLM architecture with cross-validation, and returns the result as an Excel file *or* JSON — downloadable via API.

**Target deployment:** Railway (API + worker), Neon Postgres (DB), Cloudflare R2 or Railway volume (file storage).

**Audience for this doc:** Claude Code, executing against an empty repo.

---

## 0. Read this first — core principles

These are non-negotiable. Every implementation decision flows from them.

1. **OCR provides ground truth from pixels.** It returns words, bounding boxes, and per-character confidence. It cannot hallucinate — its output is constrained to what the pixels say.

2. **Vision LLM provides semantic understanding.** It reads the document image directly, understands layout, handwriting, stamps, language. It *can* hallucinate plausible values, which is its primary risk.

3. **Cross-validation is the linchpin.** OCR and LLM run independently on the same invoice. Their outputs are compared field-by-field. Agreement → high confidence. Disagreement → flag for review. This catches silent errors that pure-LLM systems miss.

4. **No per-vendor templates.** The system must be generic. Intelligence lives in the prompt and validators, not in vendor-specific rules.

5. **The model is the smart part. Code is the boring part.** Resist encoding "intelligence" in Python (regex for invoice numbers, vendor normalization, etc.). Push intelligence into prompts; push verification into validators; keep orchestration plumbing dead simple.

6. **Auditability matters.** Every extracted value must trace back to a specific pixel region with a confidence score. When the CFO asks "where did this number come from?" the answer is a bbox coordinate.

7. **Failures are loud, never silent.** A field we couldn't confidently extract gets flagged for REVIEW. We never guess and emit.

---

## 1. High-level architecture

```
┌────────────────────────────────────────────────────────────────┐
│  CLIENT (curl, Python script, web UI, Augence, anything HTTP)  │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  API SERVICE (FastAPI on Railway)                              │
│  - POST /jobs              create a job                        │
│  - GET  /jobs/{id}         poll status                         │
│  - GET  /jobs/{id}/download?format=xlsx|json                   │
└────────────────────────────────────────────────────────────────┘
                              ↓ (jobs table in Postgres)
┌────────────────────────────────────────────────────────────────┐
│  WORKER SERVICE (same image, separate process)                 │
│  Polls Postgres for queued jobs, processes them.               │
│                                                                │
│  Per job:                                                      │
│    1. INGEST    - pull PDFs (local path OR Google Drive)       │
│    2. RENDER    - PDF pages → images (hi-res + thumbnail)      │
│    3. SEGMENT   - LLM: identify distinct invoices per file     │
│    4. EXTRACT   - parallel per invoice:                        │
│         a. OCR pass (Textract DetectDocumentText)              │
│         b. Vision LLM pass (Gemini 2.5 Flash-Lite)             │
│         c. Semantic pick (LLM picks fields from OCR tokens)    │
│         d. Cross-validate (compare OCR pick vs Vision LLM)     │
│         e. Escalate disagreements (Gemini 2.5 Pro)             │
│         f. Arithmetic + sanity validators                      │
│    5. PERSIST   - write invoices + audit to Postgres           │
│    6. EMIT      - generate xlsx and json output files          │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  STORAGE                                                       │
│  - Neon Postgres: jobs, invoices, fields, audit trail          │
│  - Object storage: input PDFs + output xlsx/json               │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Tech stack — locked decisions

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for PDF, OCR, LLM, Excel |
| API framework | FastAPI | Async, typed, OpenAPI for free |
| Worker pattern | Postgres-backed queue (no Redis) | Already have Neon, fewer moving parts |
| OCR engine | **AWS Textract `DetectDocumentText`** | Raw tokens + bbox + confidence. Commodity layer, swappable. NOT `AnalyzeExpense` — that collapses OCR and classification into a black box and defeats cross-validation. |
| Vision LLM (primary) | **Gemini 2.5 Flash-Lite** | Cheapest capable vision model, ~$0.10/M input tokens |
| LLM (semantic pick) | **Gemini 2.5 Flash-Lite** | Same model, different prompt — picks token IDs from OCR output |
| LLM (escalation) | **Gemini 2.5 Pro** | Stronger model, only for disagreement cases |
| LLM (segmentation) | **Gemini 2.5 Flash-Lite** | Cheap call to count invoices per PDF |
| PDF rendering | `pypdfium2` | Fast, reliable, no system deps |
| Database | Neon Postgres | Already in use |
| ORM | SQLAlchemy 2.0 + Alembic | Standard, async-friendly |
| Object storage | Railway volume (v1) → Cloudflare R2 (v2) | Behind a `Storage` abstraction |
| Excel generation | `openpyxl` | Mature, no Excel install needed |
| Google Drive | `google-api-python-client` + service account | Standard Google auth |
| Concurrency (in worker) | `asyncio` + `aiohttp` | Native, no Celery/RQ |
| Deployment | Railway (two services from one image) | Already in use |

---

## 3. Repository layout

```
invoice-parser/
├── README.md
├── pyproject.toml                  # uv or poetry
├── Dockerfile
├── railway.json                    # Railway config
├── alembic.ini
├── migrations/
│   └── versions/
├── src/
│   └── invoice_parser/
│       ├── __init__.py
│       ├── config.py               # env vars, settings (pydantic-settings)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py             # FastAPI app
│       │   ├── routes.py           # POST /jobs, GET /jobs/{id}, etc.
│       │   ├── auth.py             # API key auth middleware
│       │   └── schemas.py          # pydantic request/response models
│       ├── worker/
│       │   ├── __init__.py
│       │   ├── main.py             # entrypoint: poll loop
│       │   ├── pipeline.py         # per-invoice pipeline orchestration
│       │   ├── ingest.py           # local folder + Google Drive
│       │   ├── render.py           # PDF → images
│       │   ├── segment.py          # multi-invoice detection
│       │   ├── ocr.py              # Textract wrapper
│       │   ├── vision_llm.py       # Gemini vision extraction
│       │   ├── semantic_pick.py    # LLM picks fields from OCR tokens
│       │   ├── cross_validate.py   # compare OCR + Vision results
│       │   ├── escalate.py         # strong-model fallback
│       │   ├── validators.py       # arithmetic, date, currency, sanity
│       │   └── emit.py             # xlsx + json generation
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py           # SQLAlchemy ORM
│       │   ├── session.py
│       │   └── queue.py            # SKIP LOCKED queue helpers
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── base.py             # Storage abstraction
│       │   ├── local.py            # Railway volume impl
│       │   └── r2.py               # Cloudflare R2 impl (stub for v2)
│       └── schema/
│           ├── __init__.py
│           └── invoice.py          # canonical Invoice data class
├── tests/
│   ├── fixtures/                   # sample PDFs (committed)
│   ├── test_pipeline.py
│   ├── test_validators.py
│   ├── test_cross_validate.py
│   └── test_api.py
└── scripts/
    ├── create_api_key.py           # one-off: insert an API key row
    └── run_local.py                # process one folder locally for dev
```

---

## 4. Environment variables

All required unless marked optional. Use `pydantic-settings`.

```
# Database
DATABASE_URL=postgresql+asyncpg://...

# Storage
STORAGE_BACKEND=local                # local | r2
STORAGE_LOCAL_PATH=/storage          # if local
R2_ACCOUNT_ID=                       # if r2
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=

# AWS (Textract)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Gemini
GOOGLE_API_KEY=

# Google Drive (service account)
GDRIVE_SERVICE_ACCOUNT_JSON=         # full JSON string OR path to file

# Worker tuning
WORKER_CONCURRENCY=15                # parallel invoices per worker process
WORKER_POLL_INTERVAL_SECONDS=2

# Limits
MAX_FILES_PER_JOB=200
MAX_FILE_SIZE_MB=20
MAX_TOTAL_UPLOAD_MB=500

# Logging
LOG_LEVEL=INFO
```

---

## 5. Database schema

Use Alembic migrations. All tables use `id` as TEXT (prefix-based IDs like `job_abc123`).

### `api_keys`
```sql
CREATE TABLE api_keys (
  id TEXT PRIMARY KEY,                     -- key_xxx
  hashed_key TEXT NOT NULL UNIQUE,         -- sha256 of the raw key
  name TEXT NOT NULL,
  rate_limit_per_minute INT DEFAULT 60,
  monthly_cost_cap_usd NUMERIC(10,2),
  created_at TIMESTAMPTZ DEFAULT now(),
  revoked_at TIMESTAMPTZ
);
```

### `jobs`
```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,                     -- job_xxx
  api_key_id TEXT NOT NULL REFERENCES api_keys(id),
  status TEXT NOT NULL,                    -- queued | running | done | failed
  input_source TEXT NOT NULL,              -- upload | local_path | gdrive
  input_manifest JSONB NOT NULL,           -- list of {file_id, filename, storage_key}
  output_format TEXT NOT NULL,             -- xlsx | json | both
  file_count INT,
  files_completed INT DEFAULT 0,
  files_failed INT DEFAULT 0,
  invoices_extracted INT DEFAULT 0,
  invoices_review INT DEFAULT 0,
  result_xlsx_key TEXT,                    -- storage key
  result_json_key TEXT,
  cost_usd NUMERIC(10,4) DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,                  -- 30 days from finished_at
  error TEXT
);

CREATE INDEX idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX idx_jobs_api_key ON jobs(api_key_id);
```

### `invoices`
```sql
CREATE TABLE invoices (
  id TEXT PRIMARY KEY,                     -- inv_xxx
  job_id TEXT NOT NULL REFERENCES jobs(id),
  source_file TEXT NOT NULL,
  source_pages INT[],
  invoice_index_in_file INT DEFAULT 1,
  status TEXT NOT NULL,                    -- ok | review | failed
  notes TEXT,
  cost_usd NUMERIC(10,4),
  models_used TEXT[],                      -- ['textract', 'gemini-flash-lite', ...]
  extracted JSONB NOT NULL,                -- full Invoice schema (see §7)
  audit JSONB NOT NULL,                    -- per-field provenance (see §8)
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_invoices_job ON invoices(job_id);
CREATE INDEX idx_invoices_status ON invoices(job_id, status);
```

---

## 6. API contract

### `POST /jobs`

**Auth:** `Authorization: Bearer <api_key>` (required for all endpoints)

**Request — Option A: file upload**
```
Content-Type: multipart/form-data

files[]:        invoice1.pdf, invoice2.pdf, ...
output_format:  xlsx | json | both
```

**Request — Option B: local folder path** (only for self-hosted use, requires worker to have filesystem access)
```json
Content-Type: application/json

{
  "source": "local_path",
  "path": "/mnt/invoices",
  "recursive": true,
  "output_format": "xlsx"
}
```

**Request — Option C: Google Drive folder**
```json
Content-Type: application/json

{
  "source": "gdrive",
  "folder_id": "1A2B3C4D5E6F...",
  "recursive": true,
  "output_format": "json"
}
```

The folder must be shared with the service account email (returned in `GET /config/gdrive-email`).

**Response (immediate, <1s)**
```json
{
  "job_id": "job_abc123",
  "status": "queued",
  "file_count": 47,
  "estimated_cost_usd": 0.235,
  "poll_url": "/jobs/job_abc123",
  "expires_at": "2026-06-11T00:00:00Z"
}
```

### `GET /jobs/{job_id}`

```json
{
  "job_id": "job_abc123",
  "status": "running",
  "progress": {
    "files_total": 47,
    "files_completed": 23,
    "files_failed": 1,
    "invoices_extracted": 25,
    "invoices_review": 2
  },
  "cost_usd": 0.118,
  "result": null
}
```

When `status == "done"`:
```json
{
  "job_id": "job_abc123",
  "status": "done",
  "progress": { ... },
  "cost_usd": 0.235,
  "result": {
    "downloads": {
      "xlsx": "/jobs/job_abc123/download?format=xlsx",
      "json": "/jobs/job_abc123/download?format=json"
    },
    "summary": {
      "invoices_total": 52,
      "invoices_ok": 48,
      "invoices_review": 3,
      "invoices_failed": 1
    }
  }
}
```

### `GET /jobs/{job_id}/download?format=xlsx|json`

Returns the file as a binary stream. `Content-Disposition: attachment` header included.

### `GET /config/gdrive-email`

Returns the service account email so users know what to share Drive folders with.

```json
{ "email": "invoice-parser@your-project.iam.gserviceaccount.com" }
```

---

## 7. Canonical Invoice schema

This is the source of truth. Defined as Pydantic models in `src/invoice_parser/schema/invoice.py`. All extraction outputs conform to this shape.

```python
from datetime import date
from decimal import Decimal
from typing import Optional, Literal
from pydantic import BaseModel, Field

class LineItem(BaseModel):
    line_number: int
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    confidence: int = Field(ge=1, le=5)  # self-rated 1-5

class Invoice(BaseModel):
    # Identity
    source_file: str
    source_pages: list[int]
    invoice_index_in_file: int = 1

    # Vendor
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    vendor_email: Optional[str] = None
    vendor_phone: Optional[str] = None

    # Bill-to
    bill_to_name: Optional[str] = None
    bill_to_address: Optional[str] = None

    # Document identifiers
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    po_number: Optional[str] = None
    reference_numbers: list[str] = []

    # Money
    currency: Optional[str] = None  # ISO 4217
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    shipping: Optional[Decimal] = None
    total: Optional[Decimal] = None
    amount_due: Optional[Decimal] = None

    # Line items
    line_items: list[LineItem] = []

    # Self-reported confidence per field (1-5)
    confidence: dict[str, int] = {}

    # Status from pipeline
    status: Literal["ok", "review", "failed"]
    notes: Optional[str] = None
```

**Rules:**
- Everything except `source_file`, `source_pages`, `status` is nullable. Real invoices don't always have due dates, POs, etc.
- `confidence` is per-field, 1–5. Aggregate confidence is not meaningful.
- `status` is computed by the validation layer, never set by the LLM directly.

---

## 8. Audit trail schema

Stored in `invoices.audit` as JSONB. Per-field provenance.

```json
{
  "invoice_number": {
    "final_value": "INV-4421",
    "decision": "agree",
    "ocr": {
      "value": "INV-4421",
      "token_id": "t_001",
      "bbox": [850, 120, 95, 22],
      "confidence": 0.987,
      "page": 1
    },
    "vision_llm": {
      "value": "INV-4421",
      "self_confidence": 5,
      "model": "gemini-2.5-flash-lite"
    },
    "escalation": null
  },
  "total": {
    "final_value": "1299.00",
    "decision": "escalated_resolved",
    "ocr": { "value": "1299.00", "bbox": [...], "confidence": 0.994 },
    "vision_llm": { "value": "1289.00", "self_confidence": 4 },
    "escalation": {
      "model": "gemini-2.5-pro",
      "value": "1299.00",
      "resolved_in_favor_of": "ocr"
    }
  }
}
```

The `decision` field is one of:
- `agree` — both engines returned the same value
- `ocr_only` — vision LLM didn't return a value
- `vision_only` — OCR didn't find it (likely handwriting or stamp)
- `escalated_resolved` — disagreement, escalation broke the tie
- `escalated_review` — disagreement, escalation produced a third answer → REVIEW
- `low_confidence` — both engines agree but OCR confidence below threshold → REVIEW

---

## 9. The per-invoice pipeline (the heart)

`src/invoice_parser/worker/pipeline.py`

```python
async def process_invoice_segment(
    file_id: str,
    pages: list[int],
    invoice_index: int,
) -> InvoiceResult:
    """Process one invoice (which may span multiple pages of a PDF)."""

    # Stage 3: OCR pass — raw tokens + bboxes + confidence
    ocr_result = await ocr.detect_document_text(file_id, pages)

    # Stage 4: Vision LLM pass — semantic read of the image
    vision_result = await vision_llm.extract_invoice(file_id, pages)

    # Stage 5: Semantic pick — LLM picks token IDs from OCR output
    ocr_pick = await semantic_pick.assign_fields(ocr_result)

    # Stage 6: Cross-validate
    merged = cross_validate.compare(ocr_pick, vision_result)

    # Stage 7: Escalate disagreements
    for field_name, field in merged.fields.items():
        if field.decision in ("disagree", "low_confidence"):
            field = await escalate.resolve(field, file_id, pages)
            merged.fields[field_name] = field

    # Validators (arithmetic, date sanity, currency, format)
    validators.run_all(merged)

    # Build canonical Invoice + audit trail
    invoice = build_invoice(merged, file_id, pages, invoice_index)
    audit = build_audit(merged)

    return InvoiceResult(invoice=invoice, audit=audit)
```

---

## 10. Module specs

### 10.1 `ingest.py` — source adapters

Two source types: local path and Google Drive. Same interface.

```python
class IngestSource(ABC):
    async def list_pdfs(self) -> list[FileRef]: ...
    async def fetch(self, file_ref: FileRef) -> bytes: ...

class LocalPathSource(IngestSource):
    def __init__(self, path: str, recursive: bool = True): ...

class GoogleDriveSource(IngestSource):
    def __init__(self, folder_id: str, recursive: bool = True): ...
```

**Google Drive specifics:**
- Authenticate via service account JSON in `GDRIVE_SERVICE_ACCOUNT_JSON`
- Scope: `https://www.googleapis.com/auth/drive.readonly`
- Query for PDFs: `'{folder_id}' in parents and mimeType='application/pdf' and trashed=false`
- If `recursive=True`, walk subfolders via additional queries
- Stream file content with `MediaIoBaseDownload`
- Surface a clear error if the folder isn't shared with the service account

### 10.2 `render.py` — PDF to images

```python
def render_pages(pdf_bytes: bytes) -> list[RenderedPage]:
    """
    Returns one RenderedPage per page with:
      - hi_res: PNG bytes at 200 DPI (for OCR + Vision LLM)
      - lo_res: PNG bytes at 72 DPI (for segmentation)
      - page_number: 1-indexed
    """
```

Use `pypdfium2`. Both resolutions are generated upfront and stashed in storage; subsequent stages pull them by key.

### 10.3 `segment.py` — multi-invoice detection

One LLM call per file with all low-res thumbnails. Returns:

```python
class Segmentation(BaseModel):
    document_type: Literal["single_invoice", "multi_invoice", "statement_bundle", "mixed", "non_invoice"]
    invoices: list[InvoiceSegment]
    skipped_pages: list[SkippedPage]
    confidence: int

class InvoiceSegment(BaseModel):
    pages: list[int]
    appears_to_be: str  # "invoice", "delivery_receipt", "statement", ...

class SkippedPage(BaseModel):
    page: int
    reason: str
```

**Prompt (paste verbatim):**

```
You are looking at thumbnails of every page in a PDF document, in order.

Your task: identify how many distinct INVOICES are in this document, and which pages each one spans. An invoice is a document a vendor sends requesting payment for goods/services, with a vendor name, an invoice number or identifier, a date, line items or service description, and an amount due.

The PDF may contain:
- A single invoice (possibly spanning multiple pages)
- Multiple separate invoices bundled together
- A statement with multiple invoices attached
- Non-invoice pages (cover letters, delivery receipts, terms & conditions, photos, blank pages)

For each invoice, return the page numbers (1-indexed) it spans. For non-invoice pages, return them in skipped_pages with a brief reason.

Return JSON matching this schema:
{
  "document_type": "single_invoice" | "multi_invoice" | "statement_bundle" | "mixed" | "non_invoice",
  "invoices": [
    { "pages": [1, 2], "appears_to_be": "invoice" }
  ],
  "skipped_pages": [
    { "page": 3, "reason": "delivery receipt" }
  ],
  "confidence": 1-5
}

Be conservative: if you're unsure whether something is an invoice, include it as an invoice (we'd rather flag for human review than silently drop billable data).
```

### 10.4 `ocr.py` — Textract wrapper

Calls AWS Textract `DetectDocumentText` (NOT `AnalyzeExpense`). Returns:

```python
class OCRResult(BaseModel):
    page: int
    tokens: list[OCRToken]

class OCRToken(BaseModel):
    id: str                       # generated: t_001, t_002, ...
    text: str
    bbox: tuple[float, float, float, float]  # x, y, w, h (normalized 0-1)
    confidence: float             # 0-1
    block_type: Literal["WORD", "LINE"]
```

For multi-page invoices, call Textract's async API (`StartDocumentTextDetection`) and poll `GetDocumentTextDetection`. For single-page, sync API is fine.

### 10.5 `vision_llm.py` — Gemini vision extraction

Sends hi-res page images to Gemini 2.5 Flash-Lite with the canonical Invoice schema. Returns a partial Invoice with `confidence` populated per field.

**Prompt (paste verbatim):**

```
You are extracting structured data from an invoice. You will receive one or more page images of a single invoice. Extract the following fields and return strict JSON.

For each field, also rate your confidence on a scale of 1 to 5:
- 5: I can see this exactly in the document, no ambiguity
- 4: Very likely correct, minor uncertainty
- 3: Best guess based on context
- 2: Significant uncertainty
- 1: Guessing — flag for review

If a field is not present in the document, return null. DO NOT GUESS values that aren't there. Returning null is correct and expected for missing fields.

Fields to extract:
- vendor_name: the company sending the invoice
- vendor_address: their address
- vendor_tax_id: their tax ID / EIN / VAT number if shown
- vendor_email, vendor_phone: contact info
- bill_to_name, bill_to_address: who the invoice is addressed to
- invoice_number: the unique identifier for this invoice. Common labels: "Invoice #", "Invoice No", "INV", "Inv #", "Bill #", "Document #". NOT a PO number, NOT a customer number, NOT a quote number.
- invoice_date: when the invoice was issued
- due_date: when payment is due
- po_number: the purchase order number, if referenced
- reference_numbers: any other reference numbers (account #, job #, etc.) as a list
- currency: ISO 4217 code (USD, EUR, etc.)
- subtotal: pre-tax total
- tax_amount: total tax
- tax_rate: tax rate as a decimal (0.0875 for 8.75%)
- discount: discount amount if applied
- shipping: shipping/freight charge
- total: final amount on the invoice
- amount_due: amount remaining to be paid (often equals total, but may differ if partial payments shown)
- line_items: list of {description, quantity, unit_price, line_total}

Dates must be in ISO format YYYY-MM-DD. Amounts must be decimal numbers (no currency symbols, no commas).

Return JSON only, matching this exact shape:
{
  "vendor_name": "...",
  ...
  "line_items": [...],
  "confidence": {
    "vendor_name": 5,
    "invoice_number": 5,
    ...
  }
}
```

Use Gemini's structured output mode (`response_mime_type: "application/json"` + `response_schema`) so the model is constrained to return valid JSON.

### 10.6 `semantic_pick.py` — LLM picks fields from OCR tokens

This is the critical "grounding" layer. The LLM receives the OCR token list and is asked to pick which token IDs correspond to which fields. Output is constrained to existing token IDs — no hallucination possible.

**Prompt (paste verbatim):**

```
You are identifying invoice fields from a list of OCR tokens extracted from a page. Each token has an id, the text content, and a bounding box position on the page.

Your task: for each canonical invoice field, identify which token id(s) contain that field's value. You may return null if the field is not present.

CRITICAL: Return only token ids from the list provided. DO NOT invent text. DO NOT modify or correct the OCR text. If the OCR misread a character, you must still return the token id that corresponds to where that field appears — the cross-validation step will handle OCR errors.

For multi-token fields (e.g., a full address spanning multiple tokens, or "INV - 4421" split into 3 tokens), return a list of token ids in reading order.

OCR tokens:
{tokens_json}

Return JSON:
{
  "vendor_name": ["t_005", "t_006"] | null,
  "invoice_number": ["t_012"] | null,
  "invoice_date": ["t_018"] | null,
  ... etc for every field in the canonical schema
}
```

After the model returns, the code resolves token IDs to text by concatenation (with single spaces).

### 10.7 `cross_validate.py` — the linchpin

For each field, compare the OCR-grounded value (from semantic pick) against the Vision LLM value. Returns a merged result with decision per field.

```python
class FieldResult(BaseModel):
    field_name: str
    final_value: Optional[str]
    decision: Literal[
        "agree",
        "ocr_only",
        "vision_only",
        "disagree",
        "low_confidence",
        "both_null",
    ]
    ocr_value: Optional[str]
    ocr_confidence: Optional[float]
    ocr_tokens: list[OCRToken]
    vision_value: Optional[str]
    vision_confidence: Optional[int]
```

**Comparison rules per field type:**

- **Strings** (vendor_name, address): normalize whitespace and case, then fuzzy match using Levenshtein distance with threshold 0.9.
- **Numbers** (amounts): parse both, compare with absolute tolerance of 0.01.
- **Dates**: parse both to ISO, compare exact.
- **Currency**: exact match.
- **Lists** (reference_numbers, line_items): compare element-wise; partial agreement is allowed but downgrades to REVIEW.

**Decision logic:**

```python
def decide(ocr_val, vision_val, ocr_conf, vision_conf, field_type) -> Decision:
    if ocr_val is None and vision_val is None:
        return "both_null"
    if ocr_val is None:
        return "vision_only"
    if vision_val is None:
        return "ocr_only"
    if values_match(ocr_val, vision_val, field_type):
        if ocr_conf < OCR_CONFIDENCE_THRESHOLD:  # default 0.85
            return "low_confidence"
        return "agree"
    return "disagree"
```

The OCR value is preferred as `final_value` on agreement (it's pixel-grounded with a bbox).

### 10.8 `escalate.py` — strong-model resolution

For fields with `decision == "disagree"` or `"low_confidence"`, call Gemini 2.5 Pro with both candidate values and the page region cropped tight to the OCR bbox.

```python
async def resolve(
    field: FieldResult,
    file_id: str,
    pages: list[int],
) -> FieldResult:
    # Crop the page to the OCR bbox + padding
    # Send to Gemini Pro with both candidates + the cropped image
    # Pro returns: agrees_with="ocr"|"vision"|"neither", value=<final>
```

If Pro agrees with one of the two candidates → that becomes final, decision = `escalated_resolved`.
If Pro returns a third answer or won't commit → decision = `escalated_review`, status downgrades to REVIEW.

### 10.9 `validators.py` — arithmetic + sanity

Independent checks that run regardless of confidence:

- **Arithmetic:**
  - `sum(line_items.line_total) ≈ subtotal` (tolerance 0.02)
  - `subtotal + tax_amount + shipping − discount ≈ total` (tolerance 0.02)
  - If math doesn't reconcile → downgrade to REVIEW, add reason to `notes`.

- **Date sanity:**
  - `invoice_date` not in the future by more than 1 day
  - `invoice_date` not older than 5 years
  - `due_date >= invoice_date` if both present

- **Currency consistency:**
  - All amounts in a single invoice use the same currency
  - Currency is a valid ISO 4217 code

- **Format:**
  - `vendor_tax_id` matches a known format (EIN, VAT, etc.) — soft warning only

### 10.10 `emit.py` — output generation

**XLSX output (4 sheets):**

1. **Invoices** — one row per extracted invoice with all canonical fields flat. Status column color-coded (green=ok, yellow=review, red=failed). Freeze first row, autosize columns.

2. **Line Items** — one row per line item with `invoice_number` and `line_number` as join keys.

3. **Review** — only rows where `status != "ok"`, plus a `reason` column explaining why.

4. **Audit** — per-field provenance: invoice_id, field_name, final_value, decision, ocr_value, ocr_confidence, vision_value, vision_confidence, bbox.

5. **Skipped** — pages that segmentation skipped, with reasons.

**JSON output:**

```json
{
  "job_id": "job_abc123",
  "generated_at": "2026-05-12T00:00:00Z",
  "summary": { ... },
  "invoices": [
    {
      "id": "inv_xxx",
      "source_file": "...",
      "source_pages": [1, 2],
      "status": "ok",
      ...all canonical fields...,
      "line_items": [ ... ],
      "audit": { ...per-field provenance... }
    }
  ],
  "skipped_pages": [ ... ]
}
```

---

## 11. Worker queue & concurrency

### Queue (Postgres-backed, no Redis)

Worker loop, simplified:

```python
async def worker_loop():
    while True:
        async with db.transaction() as tx:
            # Atomic claim
            job = await tx.execute("""
                UPDATE jobs
                SET status = 'running', started_at = now()
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """)
        if not job:
            await asyncio.sleep(POLL_INTERVAL)
            continue
        try:
            await process_job(job)
        except Exception as e:
            await mark_job_failed(job, e)
```

### In-worker parallelism

Inside `process_job`, use `asyncio.Semaphore(WORKER_CONCURRENCY)` to cap how many invoices process simultaneously. Default 15.

Rate limiting for Gemini: token bucket at 1000 RPM (Gemini paid tier default), shared across the semaphore. Library: `aiolimiter`.

### Retry policy

Per-stage retries with exponential backoff:
- Network errors (Gemini, Textract, R2): 3 retries, 1s/2s/4s
- Rate limit (429): exponential backoff up to 60s, infinite retries
- Malformed JSON from LLM: 1 retry with stricter prompt, then escalate to stronger model
- PDF read failure: no retry, mark file FAILED

---

## 12. Cost tracking

Every LLM call and Textract call records token/page usage to a per-job running total. Cost calculation:

```python
TEXTRACT_PER_PAGE = 0.0015
GEMINI_FLASH_LITE_INPUT = 0.10 / 1_000_000      # per token
GEMINI_FLASH_LITE_OUTPUT = 0.40 / 1_000_000
GEMINI_PRO_INPUT = 1.25 / 1_000_000
GEMINI_PRO_OUTPUT = 5.00 / 1_000_000
```

Update `jobs.cost_usd` after each stage. Surface in `GET /jobs/{id}` response.

Hard stop: if `api_keys.monthly_cost_cap_usd` is set and current month spend exceeds it, reject new jobs with 402.

---

## 13. Auth

API keys are 32-character random strings prefixed `aug_` (or your preferred prefix), stored as sha256 hash.

Middleware:
```python
@app.middleware("http")
async def auth(request, call_next):
    key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not key:
        return Response(401)
    hashed = sha256(key.encode()).hexdigest()
    api_key = await db.fetch_one(
        "SELECT * FROM api_keys WHERE hashed_key = $1 AND revoked_at IS NULL",
        hashed,
    )
    if not api_key:
        return Response(401)
    request.state.api_key = api_key
    return await call_next(request)
```

Rate limiting: in-process token bucket per `api_key_id`, limit from `api_keys.rate_limit_per_minute`. For multi-worker deployments later, move this to Postgres or Redis.

`scripts/create_api_key.py` prints a fresh key once at creation:
```
Created key key_abc123 ('design partner 1').
Raw key (save this — won't be shown again): aug_xK3p9Q...
```

---

## 14. Storage abstraction

```python
class Storage(ABC):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def signed_url(self, key: str, expires_in: int = 3600) -> str: ...
    async def delete(self, key: str) -> None: ...
```

Two implementations:
- `LocalStorage` — writes to `STORAGE_LOCAL_PATH`. `signed_url` returns `/jobs/{job_id}/download?...` (served by FastAPI).
- `R2Storage` — boto3 client pointed at R2 endpoint. `signed_url` uses S3-style presigned URLs.

Key schema:
```
jobs/{job_id}/inputs/{file_id}.pdf
jobs/{job_id}/renders/{file_id}/page_{n}_hires.png
jobs/{job_id}/renders/{file_id}/page_{n}_thumb.png
jobs/{job_id}/output.xlsx
jobs/{job_id}/output.json
```

---

## 15. Retention

A daily cron job (Railway cron or in-worker scheduled task) deletes:
- Jobs older than 30 days (delete row + all associated storage)
- Orphaned storage objects with no matching job row

Surface `expires_at` in API responses so callers know.

---

## 16. Logging & observability

- Structured JSON logs with `structlog`
- Every log line carries `job_id` and `api_key_id` (no raw key) for grep-ability
- Per-stage timings logged: `segment_ms`, `ocr_ms`, `vision_ms`, `pick_ms`, `validate_ms`, `escalate_ms`
- **Never log raw invoice content** (PII / financial data). Log token counts, costs, and decisions only.

---

## 17. Tests

Required before considering this "done":

- **Unit tests** for `cross_validate.compare`, `validators.*`, `semantic_pick.resolve_tokens`
- **Integration test** with 3 sample PDFs in `tests/fixtures/`:
  1. Clean single-page invoice
  2. Multi-page invoice (one invoice across 3 pages)
  3. Statement bundle (3 invoices in one PDF)
- **End-to-end test** against the live API using a test API key, mocking Textract/Gemini responses with `respx`
- **Local dev script** `scripts/run_local.py` that processes one folder without the API/queue layer (for fast iteration on the pipeline)

---

## 18. Deployment to Railway

```
railway.json
```
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "DOCKERFILE" },
  "deploy": {
    "numReplicas": 1,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

Create two services in Railway from the same repo:

| Service | Start command | Public |
|---|---|---|
| `api` | `uvicorn invoice_parser.api.main:app --host 0.0.0.0 --port $PORT` | Yes |
| `worker` | `python -m invoice_parser.worker.main` | No |

Attach the same volume (`/storage`) to both. Both share `DATABASE_URL` and other env vars.

---

## 19. Build order

Build in this sequence so you have a working thing at every step:

1. **Skeleton:** repo layout, `pyproject.toml`, `pydantic-settings` config, FastAPI hello world, SQLAlchemy models, Alembic migration for `api_keys`, `jobs`, `invoices`.
2. **Pipeline with hardcoded inputs:** `render.py` + `ocr.py` + `vision_llm.py` + `cross_validate.py` running on one local PDF. No queue, no API. Print results to stdout. **This is where 80% of the engineering goes.**
3. **Add `semantic_pick.py` + `validators.py` + `escalate.py`.** Same local run, now with full pipeline.
4. **Add `segment.py`.** Now handles multi-invoice PDFs.
5. **State store + worker loop.** Process jobs from `jobs` table. Still no API.
6. **API surface.** POST/GET/download endpoints. Auth middleware. Upload-source flow first.
7. **`ingest.py` adapters.** Add local-path and Google Drive sources.
8. **`emit.py`.** XLSX and JSON output generation.
9. **Dockerfile + Railway config.** Deploy both services.
10. **Tests + retention cron.**

---

## 20. Open decisions (resolve before phase 7+)

These are deferred but will need answers:

- [ ] Webhook callbacks instead of polling — defer to v2
- [ ] Cancellation endpoint — defer to v2
- [ ] Multi-region deployment — single region (US) for v1
- [ ] PII redaction in stored PDFs — encrypt at rest with R2 SSE, defer additional redaction
- [ ] Web UI for reviewing flagged invoices — out of scope for v1
- [ ] Resume of partially-failed jobs — yes, by design; resumes from `files_completed`

---

## 21. What "done" looks like for v1

A solo founder can:
1. `curl -X POST https://invoice-parser-production.up.railway.app/jobs -H "Authorization: Bearer aug_..." -F "files=@inv1.pdf" -F "files=@inv2.pdf" -F "output_format=xlsx"`
2. Get back `job_id`, poll until `done`
3. Download the xlsx
4. Open it and see 2 rows with vendor, invoice number, total, status=ok, confidence 5/5 across the board
5. Process a 100-PDF Google Drive folder in under 2 minutes
6. See a REVIEW row for an intentionally-ambiguous test invoice
7. Click the bbox in the Audit sheet → matches the PDF pixel where the value appears

That's the bar. Hit it and ship.
