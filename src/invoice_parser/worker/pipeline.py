"""§9 — Per-invoice pipeline orchestration.

process_invoice_segment runs one invoice (possibly multi-page) through the
full OCR → Vision LLM → semantic pick → cross-validate → escalate → validate
chain and returns a canonical Invoice + audit trail.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from invoice_parser.schema.invoice import Invoice, LineItem
from invoice_parser.storage.base import Storage
from invoice_parser.worker import cross_validate, escalate, ocr, semantic_pick, validators
from invoice_parser.worker.cross_validate import MergedResult
from invoice_parser.worker.segment import SkippedPage
from invoice_parser.worker.vision_llm import extract_invoice

logger = structlog.get_logger()


@dataclass
class InvoiceResult:
    invoice: Invoice
    audit: dict
    cost_usd: float
    models_used: list[str]


@dataclass
class JobResult:
    invoice_results: list[InvoiceResult]
    skipped_pages: list[SkippedPage]


# ── Cost constants ────────────────────────────────────────────────────────────

GOOGLE_VISION_PER_PAGE = 0.0015
GEMINI_FLASH_LITE_INPUT = 0.10 / 1_000_000
GEMINI_FLASH_LITE_OUTPUT = 0.40 / 1_000_000
GEMINI_PRO_INPUT = 1.25 / 1_000_000
GEMINI_PRO_OUTPUT = 5.00 / 1_000_000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _coerce(value: str | None, field: str) -> Any:
    if value is None:
        return None
    numeric = {
        "subtotal", "tax_amount", "tax_rate", "discount",
        "shipping", "total", "amount_due",
    }
    date_fields = {"invoice_date", "due_date"}
    if field in numeric:
        try:
            return Decimal(value.replace(",", "").replace("$", "").strip())
        except (InvalidOperation, AttributeError):
            return None
    if field in date_fields:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return value


def _build_invoice(
    merged: MergedResult,
    source_file: str,
    pages: list[int],
    invoice_index: int,
    vision_result: dict,
) -> Invoice:
    def fv(name: str) -> Any:
        field = merged.fields.get(name)
        return _coerce(field.final_value if field else None, name)

    # Determine status
    decisions_needing_review = {"escalated_review", "low_confidence"}
    needs_review = any(
        f.decision in decisions_needing_review
        for f in merged.fields.values()
    ) or bool(merged.review_reasons)
    failed = all(
        f.decision == "both_null"
        for f in merged.fields.values()
        if f.field_name not in ("reference_numbers", "line_items")
    )
    status = "failed" if failed else ("review" if needs_review else "ok")

    # Line items from vision result (OCR can't reconstruct table structure)
    raw_items = vision_result.get("line_items") or []
    line_items = []
    for i, item in enumerate(raw_items):
        try:
            line_items.append(LineItem(
                line_number=i + 1,
                description=item.get("description"),
                quantity=Decimal(str(item["quantity"])) if item.get("quantity") else None,
                unit_price=Decimal(str(item["unit_price"])) if item.get("unit_price") else None,
                line_total=Decimal(str(item["line_total"])) if item.get("line_total") else None,
                confidence=item.get("confidence", 3),
            ))
        except Exception:
            pass

    notes = "; ".join(merged.review_reasons) if merged.review_reasons else None

    return Invoice(
        source_file=source_file,
        source_pages=pages,
        invoice_index_in_file=invoice_index,
        vendor_name=fv("vendor_name"),
        vendor_address=fv("vendor_address"),
        vendor_tax_id=fv("vendor_tax_id"),
        vendor_email=fv("vendor_email"),
        vendor_phone=fv("vendor_phone"),
        bill_to_name=fv("bill_to_name"),
        bill_to_address=fv("bill_to_address"),
        invoice_number=fv("invoice_number"),
        invoice_date=fv("invoice_date"),
        due_date=fv("due_date"),
        po_number=fv("po_number"),
        reference_numbers=vision_result.get("reference_numbers") or [],
        currency=fv("currency"),
        subtotal=fv("subtotal"),
        tax_amount=fv("tax_amount"),
        tax_rate=fv("tax_rate"),
        discount=fv("discount"),
        shipping=fv("shipping"),
        total=fv("total"),
        amount_due=fv("amount_due"),
        line_items=line_items,
        confidence=vision_result.get("confidence", {}),
        status=status,
        notes=notes,
    )


def _build_audit(merged: MergedResult, models_used: list[str]) -> dict:
    audit: dict = {}
    for fname, field in merged.fields.items():
        entry: dict = {
            "final_value": field.final_value,
            "decision": field.decision,
            "ocr": None,
            "vision_llm": None,
            "escalation": None,
        }
        if field.ocr_tokens:
            t = field.ocr_tokens[0]
            entry["ocr"] = {
                "value": field.ocr_value,
                "token_id": t.id,
                "bbox": list(t.bbox),
                "confidence": field.ocr_confidence,
            }
        if field.vision_value is not None:
            entry["vision_llm"] = {
                "value": field.vision_value,
                "self_confidence": field.vision_confidence,
                "model": models_used[1] if len(models_used) > 1 else "gemini-flash-lite",
            }
        if field.decision in ("escalated_resolved", "escalated_review"):
            entry["escalation"] = {
                "model": models_used[-1] if models_used else "gemini-pro",
                "value": field.final_value,
                "resolved_in_favor_of": (
                    "ocr" if field.final_value == field.ocr_value else "vision"
                ),
            }
        audit[fname] = entry
    return audit


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def process_invoice_segment(
    storage: Storage,
    job_id: str,
    file_id: str,
    pages: list[int],
    invoice_index: int,
) -> InvoiceResult:
    log = logger.bind(job_id=job_id, file_id=file_id, pages=pages)
    models_used = ["google-cloud-vision", "gemini-flash-lite"]
    cost = 0.0

    # Load hi-res page images from storage
    hi_res_images: list[tuple[int, bytes]] = []
    for page in pages:
        key = f"jobs/{job_id}/renders/{file_id}/page_{page}_hires.png"
        image_bytes = await storage.get(key)
        hi_res_images.append((page, image_bytes))
        cost += GOOGLE_VISION_PER_PAGE

    log.info("pipeline_ocr_start")
    # Stage 3: OCR pass
    ocr_results = []
    for page_num, image_bytes in hi_res_images:
        result = await ocr.detect_document_text(image_bytes, page_num)
        ocr_results.append(result)

    log.info("pipeline_vision_start")
    # Stage 4: Vision LLM pass
    vision_result = await extract_invoice([img for _, img in hi_res_images])
    cost += GEMINI_FLASH_LITE_INPUT * 5000 + GEMINI_FLASH_LITE_OUTPUT * 500  # rough estimate

    log.info("pipeline_semantic_pick_start")
    # Stage 5: Semantic pick — LLM picks token IDs
    ocr_pick = await semantic_pick.assign_fields(ocr_results)
    cost += GEMINI_FLASH_LITE_INPUT * 3000 + GEMINI_FLASH_LITE_OUTPUT * 300

    log.info("pipeline_cross_validate_start")
    # Stage 6: Cross-validate
    merged = cross_validate.compare(ocr_pick, vision_result)

    log.info("pipeline_escalate_start")
    # Stage 7: Escalate disagreements
    for field_name, field in list(merged.fields.items()):
        if field.decision in ("disagree", "low_confidence"):
            log.info("escalating_field", field=field_name)
            merged.fields[field_name] = await escalate.resolve(field, hi_res_images)
            models_used.append("gemini-pro")
            cost += GEMINI_PRO_INPUT * 2000 + GEMINI_PRO_OUTPUT * 200

    # Stage 8: Validators
    validators.run_all(merged)

    # Build outputs
    invoice = _build_invoice(merged, file_id, pages, invoice_index, vision_result)
    audit = _build_audit(merged, models_used)

    log.info("pipeline_complete", status=invoice.status, cost_usd=round(cost, 6))
    return InvoiceResult(invoice=invoice, audit=audit, cost_usd=cost, models_used=models_used)
