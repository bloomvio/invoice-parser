"""§10.7 — Cross-validation: compare OCR-grounded values vs Vision LLM values.

Agreement → high confidence. Disagreement → flag for escalation/review.
This catches silent LLM hallucinations that pure-LLM systems miss.
"""

from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz

from invoice_parser.worker.ocr import OCRToken

OCR_CONFIDENCE_THRESHOLD = 0.85

Decision = Literal[
    "agree",
    "ocr_only",
    "vision_only",
    "disagree",
    "low_confidence",
    "both_null",
]

# Field type categories for comparison strategy
_STRING_FIELDS = {
    "vendor_name", "vendor_address", "vendor_tax_id", "vendor_email", "vendor_phone",
    "bill_to_name", "bill_to_address", "invoice_number", "po_number", "currency",
}
_NUMERIC_FIELDS = {
    "subtotal", "tax_amount", "tax_rate", "discount", "shipping", "total", "amount_due",
}
_DATE_FIELDS = {"invoice_date", "due_date"}
_LIST_FIELDS = {"reference_numbers", "line_items"}


class FieldResult(BaseModel):
    field_name: str
    final_value: Optional[str]
    decision: Decision
    ocr_value: Optional[str]
    ocr_confidence: Optional[float]
    ocr_tokens: list[OCRToken] = []
    vision_value: Optional[str]
    vision_confidence: Optional[int]


class MergedResult(BaseModel):
    fields: dict[str, FieldResult]
    review_reasons: list[str] = []


def _normalize(val: str | None) -> str | None:
    if val is None:
        return None
    return " ".join(val.lower().split())


def _parse_decimal(val: str | None) -> Decimal | None:
    if not val:
        return None
    try:
        cleaned = str(val).replace(",", "").replace("$", "").strip()
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _values_match(ocr_val: str, vision_val: str, field_name: str) -> bool:
    if field_name in _STRING_FIELDS:
        n1 = _normalize(ocr_val) or ""
        n2 = _normalize(vision_val) or ""
        if not n1 and not n2:
            return True
        similarity = fuzz.token_sort_ratio(n1, n2) / 100.0
        return similarity >= 0.9

    if field_name in _NUMERIC_FIELDS:
        d1 = _parse_decimal(ocr_val)
        d2 = _parse_decimal(vision_val)
        if d1 is None and d2 is None:
            return True
        if d1 is None or d2 is None:
            return False
        return abs(d1 - d2) <= Decimal("0.01")

    if field_name in _DATE_FIELDS:
        return _normalize(ocr_val) == _normalize(vision_val)

    # Default: normalized string equality
    return _normalize(ocr_val) == _normalize(vision_val)


def _decide(
    ocr_val: str | None,
    vision_val: str | None,
    ocr_conf: float,
    field_name: str,
) -> Decision:
    if ocr_val is None and vision_val is None:
        return "both_null"
    if ocr_val is None:
        return "vision_only"
    if vision_val is None:
        return "ocr_only"
    if _values_match(ocr_val, vision_val, field_name):
        if ocr_conf < OCR_CONFIDENCE_THRESHOLD:
            return "low_confidence"
        return "agree"
    return "disagree"


def compare(ocr_pick: dict, vision_result: dict) -> MergedResult:
    """Compare OCR-grounded values against Vision LLM extraction field-by-field."""
    confidence_map: dict[str, int] = vision_result.get("confidence", {})
    fields: dict[str, FieldResult] = {}

    all_field_names = set(ocr_pick.keys()) | {
        k for k in vision_result if k not in ("confidence", "line_items", "reference_numbers")
    }

    for fname in all_field_names:
        ocr_entry = ocr_pick.get(fname, {})
        ocr_val = ocr_entry.get("value")
        ocr_conf = ocr_entry.get("confidence", 0.0)
        ocr_tokens = ocr_entry.get("tokens", [])

        vision_raw = vision_result.get(fname)
        vision_val = str(vision_raw) if vision_raw is not None else None
        vision_conf = confidence_map.get(fname)

        decision = _decide(ocr_val, vision_val, ocr_conf, fname)

        # OCR value preferred as final on agreement (pixel-grounded with bbox)
        if decision in ("agree", "ocr_only", "low_confidence"):
            final = ocr_val
        elif decision == "vision_only":
            final = vision_val
        else:
            final = ocr_val  # tentative; escalation may override

        fields[fname] = FieldResult(
            field_name=fname,
            final_value=final,
            decision=decision,
            ocr_value=ocr_val,
            ocr_confidence=ocr_conf,
            ocr_tokens=ocr_tokens,
            vision_value=vision_val,
            vision_confidence=vision_conf,
        )

    return MergedResult(fields=fields)
