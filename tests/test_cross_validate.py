"""§17 — Unit tests for cross_validate.compare."""

import pytest
from invoice_parser.worker.cross_validate import compare


def _pick(value: str | None, confidence: float = 0.95) -> dict:
    return {"value": value, "tokens": [], "confidence": confidence}


def test_agree():
    pick = {"invoice_number": _pick("INV-001"), "total": _pick("1000.00")}
    vision = {"invoice_number": "INV-001", "total": "1000.00", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["invoice_number"].decision == "agree"
    assert result.fields["total"].decision == "agree"


def test_disagree():
    pick = {"total": _pick("1000.00")}
    vision = {"total": "999.00", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["total"].decision == "disagree"


def test_both_null():
    pick = {"total": _pick(None)}
    vision = {"total": None, "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["total"].decision == "both_null"


def test_ocr_only():
    pick = {"invoice_number": _pick("INV-001")}
    vision = {"invoice_number": None, "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["invoice_number"].decision == "ocr_only"


def test_vision_only():
    pick = {"invoice_number": _pick(None)}
    vision = {"invoice_number": "INV-001", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["invoice_number"].decision == "vision_only"


def test_low_confidence():
    pick = {"invoice_number": _pick("INV-001", confidence=0.70)}
    vision = {"invoice_number": "INV-001", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["invoice_number"].decision == "low_confidence"


def test_numeric_tolerance():
    pick = {"total": _pick("1000.00")}
    vision = {"total": "1000.005", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["total"].decision == "agree"


def test_string_fuzzy_match():
    pick = {"vendor_name": _pick("Acme Corp.")}
    vision = {"vendor_name": "acme corp", "confidence": {}}
    result = compare(pick, vision)
    assert result.fields["vendor_name"].decision == "agree"
