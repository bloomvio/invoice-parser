"""§10.5 — Gemini 2.5 Flash-Lite vision extraction.

Reads the invoice image directly. Returns a partial Invoice dict with
per-field confidence. Can hallucinate — that's why cross-validation exists.
"""

import asyncio
import json
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image

from invoice_parser.config import settings

_PROMPT = """\
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
  "vendor_address": null,
  "vendor_tax_id": null,
  "vendor_email": null,
  "vendor_phone": null,
  "bill_to_name": null,
  "bill_to_address": null,
  "invoice_number": null,
  "invoice_date": null,
  "due_date": null,
  "po_number": null,
  "reference_numbers": [],
  "currency": null,
  "subtotal": null,
  "tax_amount": null,
  "tax_rate": null,
  "discount": null,
  "shipping": null,
  "total": null,
  "amount_due": null,
  "line_items": [],
  "confidence": {
    "vendor_name": 5,
    "invoice_number": 5
  }
}
"""


def _call_gemini(image_bytes_list: list[bytes]) -> dict:
    client = genai.Client(api_key=settings.google_api_key)
    images = [Image.open(BytesIO(b)) for b in image_bytes_list]
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


async def extract_invoice(image_bytes_list: list[bytes]) -> dict:
    """Return raw extraction dict from Vision LLM. Keys match Invoice schema fields."""
    return await asyncio.to_thread(_call_gemini, image_bytes_list)
