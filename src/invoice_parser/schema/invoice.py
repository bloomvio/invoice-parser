from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


# §7 — Canonical invoice schema. All extraction outputs conform to this shape.


class LineItem(BaseModel):
    line_number: int
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    confidence: int = Field(ge=1, le=5)


class Invoice(BaseModel):
    # Identity
    source_file: str
    source_pages: list[int]
    invoice_index_in_file: int = 1

    # Vendor
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    vendor_email: Optional[str] = None
    vendor_phone: Optional[str] = None

    # Bill-to
    bill_to_name: Optional[str] = None
    bill_to_address: Optional[str] = None

    # Document identifiers
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    po_number: Optional[str] = None
    reference_numbers: list[str] = []

    # Money
    currency: Optional[str] = None  # ISO 4217
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    shipping: Optional[Decimal] = None
    total: Optional[Decimal] = None
    amount_due: Optional[Decimal] = None

    # Line items
    line_items: list[LineItem] = []

    # Self-reported confidence per field (1-5)
    confidence: dict[str, int] = {}

    # Status set by the validation layer, never by the LLM
    status: Literal["ok", "review", "failed"]
    notes: Optional[str] = None
