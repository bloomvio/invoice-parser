"""§10.8 — Escalate disagreements to Gemini 2.5 Pro.

For fields where OCR and Vision LLM disagree, crop to the relevant page
region and ask the stronger model to break the tie.
"""

import asyncio
import json
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image

from invoice_parser.config import settings
from invoice_parser.worker.cross_validate import FieldResult

_PROMPT_TEMPLATE = """\
You are resolving a disagreement between two invoice extraction systems for the field "{field_name}".

OCR system says: {ocr_value}
Vision LLM says: {vision_value}

The cropped image shows the region of the invoice where this field appears.

Which value is correct? Return JSON:
{{
  "agrees_with": "ocr" | "vision" | "neither",
  "value": "<final value as it appears in the document>",
  "reasoning": "<one sentence>"
}}

If the value is not legible or you cannot determine the correct value, set agrees_with to "neither".
"""


def _crop_to_bbox(image_bytes: bytes, bbox: tuple[float, float, float, float]) -> bytes:
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    x, y, bw, bh = bbox
    pad = 0.02  # 2% padding
    left = max(0, int((x - pad) * w))
    top = max(0, int((y - pad) * h))
    right = min(w, int((x + bw + pad) * w))
    bottom = min(h, int((y + bh + pad) * h))
    cropped = img.crop((left, top, right, bottom))
    buf = BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _call_gemini_pro(field: FieldResult, crop_bytes: bytes) -> dict:
    client = genai.Client(api_key=settings.google_api_key)
    prompt = _PROMPT_TEMPLATE.format(
        field_name=field.field_name,
        ocr_value=field.ocr_value or "(not found)",
        vision_value=field.vision_value or "(not found)",
    )
    crop_image = Image.open(BytesIO(crop_bytes))
    response = client.models.generate_content(
        model=settings.gemini_pro_model,
        contents=[prompt, crop_image],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


async def resolve(field: FieldResult, hi_res_images: list[tuple[int, bytes]]) -> FieldResult:
    """Send the disputed field region to Gemini Pro and update decision."""
    # Find image for the page where the OCR token lives (use first token's page)
    crop_bytes: bytes | None = None
    if field.ocr_tokens and hi_res_images:
        token = field.ocr_tokens[0]
        # Use the first available page image as fallback
        image_bytes = hi_res_images[0][1]
        crop_bytes = _crop_to_bbox(image_bytes, token.bbox)
    elif hi_res_images:
        crop_bytes = hi_res_images[0][1]

    if not crop_bytes:
        field = field.model_copy(update={"decision": "escalated_review"})
        return field

    result = await asyncio.to_thread(_call_gemini_pro, field, crop_bytes)
    agrees_with = result.get("agrees_with", "neither")
    pro_value = result.get("value")

    if agrees_with == "ocr":
        return field.model_copy(update={
            "final_value": field.ocr_value,
            "decision": "escalated_resolved",
        })
    if agrees_with == "vision":
        return field.model_copy(update={
            "final_value": field.vision_value,
            "decision": "escalated_resolved",
        })
    # Neither — Pro returned a third answer or couldn't commit
    return field.model_copy(update={
        "final_value": pro_value or field.ocr_value,
        "decision": "escalated_review",
    })
