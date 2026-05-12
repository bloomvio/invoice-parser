"""§10.9 — Arithmetic, date, and sanity validators.

These run after cross-validation regardless of confidence. A failed check
downgrades the invoice to REVIEW and adds a reason to notes.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from invoice_parser.worker.cross_validate import MergedResult

_ISO_4217 = {
    "AED","AFN","ALL","AMD","ANG","AOA","ARS","AUD","AWG","AZN","BAM","BBD","BDT",
    "BGN","BHD","BIF","BMD","BND","BOB","BRL","BSD","BTN","BWP","BYR","BZD","CAD",
    "CDF","CHF","CLP","CNY","COP","CRC","CUP","CVE","CZK","DJF","DKK","DOP","DZD",
    "EGP","ERN","ETB","EUR","FJD","FKP","GBP","GEL","GHS","GIP","GMD","GNF","GTQ",
    "GYD","HKD","HNL","HRK","HTG","HUF","IDR","ILS","INR","IQD","IRR","ISK","JMD",
    "JOD","JPY","KES","KGS","KHR","KMF","KRW","KWD","KYD","KZT","LAK","LBP","LKR",
    "LRD","LSL","LYD","MAD","MDL","MGA","MKD","MMK","MNT","MOP","MRO","MUR","MVR",
    "MWK","MXN","MYR","MZN","NAD","NGN","NIO","NOK","NPR","NZD","OMR","PAB","PEN",
    "PGK","PHP","PKR","PLN","PYG","QAR","RON","RSD","RUB","RWF","SAR","SBD","SCR",
    "SDG","SEK","SGD","SHP","SLL","SOS","SRD","STD","SVC","SYP","SZL","THB","TJS",
    "TMT","TND","TOP","TRY","TTD","TWD","TZS","UAH","UGX","USD","UYU","UZS","VEF",
    "VND","VUV","WST","XAF","XCD","XOF","XPF","YER","ZAR","ZMW","ZWL",
}


def _get(merged: MergedResult, field: str) -> Decimal | None:
    f = merged.fields.get(field)
    if not f or f.final_value is None:
        return None
    try:
        return Decimal(str(f.final_value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def _get_date(merged: MergedResult, field: str) -> date | None:
    f = merged.fields.get(field)
    if not f or f.final_value is None:
        return None
    try:
        return date.fromisoformat(str(f.final_value))
    except ValueError:
        return None


def run_all(merged: MergedResult) -> list[str]:
    """Run all validators. Returns list of failure reasons (empty = pass)."""
    reasons: list[str] = []

    # ── Arithmetic ──────────────────────────────────────────────────────────
    line_items = [
        f for k, f in merged.fields.items()
        if k == "line_items" and f.final_value is not None
    ]
    # line_items are stored as JSON in final_value; skip arithmetic if missing
    subtotal = _get(merged, "subtotal")
    tax = _get(merged, "tax_amount")
    shipping = _get(merged, "shipping")
    discount = _get(merged, "discount")
    total = _get(merged, "total")

    if subtotal is not None and total is not None:
        components = subtotal
        if tax is not None:
            components += tax
        if shipping is not None:
            components += shipping
        if discount is not None:
            components -= discount
        if abs(components - total) > Decimal("0.02"):
            reasons.append(
                f"Arithmetic mismatch: subtotal({subtotal}) + tax({tax}) + "
                f"shipping({shipping}) - discount({discount}) = {components} "
                f"≠ total({total})"
            )

    # ── Date sanity ──────────────────────────────────────────────────────────
    inv_date = _get_date(merged, "invoice_date")
    due = _get_date(merged, "due_date")
    today = date.today()

    if inv_date is not None:
        if inv_date > today + timedelta(days=1):
            reasons.append(f"invoice_date {inv_date} is in the future")
        if inv_date < today - timedelta(days=365 * 5):
            reasons.append(f"invoice_date {inv_date} is more than 5 years old")

    if inv_date is not None and due is not None:
        if due < inv_date:
            reasons.append(f"due_date {due} is before invoice_date {inv_date}")

    # ── Currency ─────────────────────────────────────────────────────────────
    currency_field = merged.fields.get("currency")
    if currency_field and currency_field.final_value:
        code = str(currency_field.final_value).upper().strip()
        if code not in _ISO_4217:
            reasons.append(f"Currency '{code}' is not a valid ISO 4217 code (soft warning)")

    # Attach reasons to the merged result
    if reasons:
        merged.review_reasons.extend(reasons)

    return reasons
