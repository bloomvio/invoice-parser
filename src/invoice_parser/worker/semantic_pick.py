"""§10.6 — LLM picks which OCR token IDs correspond to each invoice field.

Output is constrained to existing token IDs — hallucination is impossible
at this layer. The cross-validation step handles OCR read errors.
"""

import asyncio
import json

from google import genai
from google.genai import types

from invoice_parser.config import settings
from invoice_parser.worker.ocr import OCRResult, OCRToken

_PROMPT_TEMPLATE = """\
You are identifying invoice fields from a list of OCR tokens extracted from a page. Each token has an id, the text content, and a bounding box position on the page.

Your task: for each canonical invoice field, identify which token id(s) contain that field's value. You may return null if the field is not present.

CRITICAL: Return only token ids from the list provided. DO NOT invent text. DO NOT modify or correct the OCR text. If the OCR misread a character, you must still return the token id that corresponds to where that field appears — the cross-validation step will handle OCR errors.

For multi-token fields (e.g., a full address spanning multiple tokens, or "INV - 4421" split into 3 tokens), return a list of token ids in reading order.

OCR tokens:
{tokens_json}

Return JSON:
{{
  "vendor_name": ["t_005", "t_006"] | null,
  "vendor_address": null,
  "vendor_tax_id": null,
  "vendor_email": null,
  "vendor_phone": null,
  "bill_to_name": null,
  "bill_to_address": null,
  "invoice_number": ["t_012"] | null,
  "invoice_date": ["t_018"] | null,
  "due_date": null,
  "po_number": null,
  "reference_numbers": null,
  "currency": null,
  "subtotal": null,
  "tax_amount": null,
  "tax_rate": null,
  "discount": null,
  "shipping": null,
  "total": null,
  "amount_due": null
}}
"""

# Fields whose tokens span multiple pages — we collect from all pages
_ALL_FIELDS = [
    "vendor_name", "vendor_address", "vendor_tax_id", "vendor_email", "vendor_phone",
    "bill_to_name", "bill_to_address", "invoice_number", "invoice_date", "due_date",
    "po_number", "reference_numbers", "currency", "subtotal", "tax_amount", "tax_rate",
    "discount", "shipping", "total", "amount_due",
]


def _build_token_index(ocr_results: list[OCRResult]) -> dict[str, OCRToken]:
    return {t.id: t for result in ocr_results for t in result.tokens}


def _resolve_tokens(token_ids: list[str] | None, index: dict[str, OCRToken]) -> str | None:
    if not token_ids:
        return None
    texts = [index[tid].text for tid in token_ids if tid in index]
    return " ".join(texts) if texts else None


def _call_gemini(tokens_json: str) -> dict:
    client = genai.Client(api_key=settings.google_api_key)
    prompt = _PROMPT_TEMPLATE.format(tokens_json=tokens_json)
    response = client.models.generate_content(
        model=settings.gemini_flash_lite_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


async def assign_fields(ocr_results: list[OCRResult]) -> dict:
    """Return dict of field_name -> {value, tokens, confidence} from OCR token grounding."""
    token_index = _build_token_index(ocr_results)
    all_tokens = [t for result in ocr_results for t in result.tokens]

    # Limit token list to avoid exceeding context window on dense documents
    tokens_payload = [
        {"id": t.id, "text": t.text, "page": result.page, "bbox": list(t.bbox)}
        for result in ocr_results
        for t in result.tokens
    ]
    tokens_json = json.dumps(tokens_payload, indent=None)

    raw = await asyncio.to_thread(_call_gemini, tokens_json)

    result = {}
    for field in _ALL_FIELDS:
        token_ids = raw.get(field)
        if isinstance(token_ids, list) and token_ids:
            resolved_tokens = [token_index[tid] for tid in token_ids if tid in token_index]
            value = " ".join(t.text for t in resolved_tokens) if resolved_tokens else None
            avg_conf = (
                sum(t.confidence for t in resolved_tokens) / len(resolved_tokens)
                if resolved_tokens else 0.0
            )
            result[field] = {
                "value": value,
                "tokens": resolved_tokens,
                "confidence": avg_conf,
            }
        else:
            result[field] = {"value": None, "tokens": [], "confidence": 0.0}

    return result
