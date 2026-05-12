"""§10.3 — Multi-invoice detection via Gemini 2.5 Flash-Lite.

Sends all low-res thumbnails for a PDF and returns a segmentation: which pages
belong to which invoice, and which pages to skip.
"""

import asyncio
import json
from io import BytesIO
from typing import Literal

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel

from invoice_parser.config import settings

_PROMPT = """\
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
"""


class InvoiceSegment(BaseModel):
    pages: list[int]
    appears_to_be: str


class SkippedPage(BaseModel):
    page: int
    reason: str


class Segmentation(BaseModel):
    document_type: Literal[
        "single_invoice", "multi_invoice", "statement_bundle", "mixed", "non_invoice"
    ]
    invoices: list[InvoiceSegment]
    skipped_pages: list[SkippedPage]
    confidence: int


def _call_gemini(thumb_bytes_list: list[bytes]) -> dict:
    client = genai.Client(api_key=settings.google_api_key)
    images = [Image.open(BytesIO(b)) for b in thumb_bytes_list]
    contents = [_PROMPT] + images
    response = client.models.generate_content(
        model=settings.gemini_flash_lite_model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


async def segment_pdf(thumb_bytes_list: list[bytes]) -> Segmentation:
    """Identify distinct invoice segments from a list of page thumbnails."""
    raw = await asyncio.to_thread(_call_gemini, thumb_bytes_list)
    return Segmentation(**raw)
