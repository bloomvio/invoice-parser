"""§10.4 — Google Cloud Vision DOCUMENT_TEXT_DETECTION wrapper.

Replaces AWS Textract DetectDocumentText. Same contract: raw tokens + bboxes +
confidence. Cannot hallucinate — output is constrained to what the pixels say.
"""

import asyncio
import json
from typing import Literal

from google.cloud import vision
from google.oauth2 import service_account
from pydantic import BaseModel

from invoice_parser.config import settings


class OCRToken(BaseModel):
    id: str
    text: str
    bbox: tuple[float, float, float, float]  # x, y, w, h — normalized 0-1
    confidence: float                         # 0-1
    block_type: Literal["WORD", "LINE"]


class OCRResult(BaseModel):
    page: int
    tokens: list[OCRToken]


def _get_client() -> vision.ImageAnnotatorClient:
    if settings.google_cloud_credentials_json:
        info = json.loads(settings.google_cloud_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-vision"],
        )
        return vision.ImageAnnotatorClient(credentials=credentials)
    # Falls back to GOOGLE_APPLICATION_CREDENTIALS / ADC
    return vision.ImageAnnotatorClient()


def _parse_response(response: vision.AnnotateImageResponse, page_number: int) -> OCRResult:
    if response.error.message:
        raise RuntimeError(f"Vision API error on page {page_number}: {response.error.message}")

    doc = response.full_text_annotation
    if not doc.pages:
        return OCRResult(page=page_number, tokens=[])

    page = doc.pages[0]
    img_w = page.width or 1
    img_h = page.height or 1

    tokens: list[OCRToken] = []
    token_index = 0

    for block in page.blocks:
        for paragraph in block.paragraphs:
            for word in paragraph.words:
                text = "".join(s.text for s in word.symbols)
                if not text.strip():
                    continue

                verts = word.bounding_box.vertices
                xs = [v.x for v in verts]
                ys = [v.y for v in verts]
                x = min(xs) / img_w
                y = min(ys) / img_h
                w = (max(xs) - min(xs)) / img_w
                h = (max(ys) - min(ys)) / img_h

                token_index += 1
                tokens.append(
                    OCRToken(
                        id=f"t_{token_index:04d}",
                        text=text,
                        bbox=(x, y, w, h),
                        confidence=word.confidence,
                        block_type="WORD",
                    )
                )

    return OCRResult(page=page_number, tokens=tokens)


async def detect_document_text(image_bytes: bytes, page_number: int) -> OCRResult:
    def _call() -> vision.AnnotateImageResponse:
        client = _get_client()
        image = vision.Image(content=image_bytes)
        return client.document_text_detection(image=image)

    response = await asyncio.to_thread(_call)
    return _parse_response(response, page_number)
