"""§17 — Unit tests for validators."""

import pytest
from invoice_parser.worker.cross_validate import FieldResult, MergedResult
from invoice_parser.worker.validators import run_all


def _merged(**field_values) -> MergedResult:
    fields = {}
    for name, value in field_values.items():
        fields[name] = FieldResult(
            field_name=name,
            final_value=str(value) if value is not None else None,
            decision="agree",
            ocr_value=None,
            ocr_confidence=None,
            vision_value=None,
            vision_confidence=None,
        )
    return MergedResult(fields=fields)


def test_arithmetic_pass():
    m = _merged(subtotal="100.00", tax_amount="8.75", shipping="5.00", discount=None, total="113.75")
    reasons = run_all(m)
    assert reasons == []


def test_arithmetic_fail():
    m = _merged(subtotal="100.00", tax_amount="8.75", shipping="5.00", discount=None, total="200.00")
    reasons = run_all(m)
    assert any("Arithmetic" in r for r in reasons)


def test_date_due_before_invoice():
    m = _merged(invoice_date="2025-06-01", due_date="2025-05-01")
    reasons = run_all(m)
    assert any("due_date" in r for r in reasons)


def test_date_future_invoice():
    m = _merged(invoice_date="2035-01-01")
    reasons = run_all(m)
    assert any("future" in r for r in reasons)


def test_invalid_currency():
    m = _merged(currency="XYZ")
    reasons = run_all(m)
    assert any("ISO 4217" in r for r in reasons)


def test_valid_currency():
    m = _merged(currency="USD")
    reasons = run_all(m)
    assert not any("ISO 4217" in r for r in reasons)
