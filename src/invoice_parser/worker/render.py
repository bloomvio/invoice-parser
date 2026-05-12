import io
from dataclasses import dataclass

import pypdfium2 as pdfium


@dataclass
class RenderedPage:
    page_number: int  # 1-indexed
    hi_res: bytes     # PNG at 200 DPI — for OCR + Vision LLM
    lo_res: bytes     # PNG at 72 DPI — for segmentation thumbnails


def render_pages(pdf_bytes: bytes) -> list[RenderedPage]:
    doc = pdfium.PdfDocument(pdf_bytes)
    pages = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            hi_res = _render_page(page, dpi=200)
            lo_res = _render_page(page, dpi=72)
            pages.append(RenderedPage(page_number=i + 1, hi_res=hi_res, lo_res=lo_res))
    finally:
        doc.close()
    return pages


def _render_page(page: pdfium.PdfPage, dpi: int) -> bytes:
    scale = dpi / 72.0
    bitmap = page.render(scale=scale, rotation=0)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
