"""Decimal euros <-> integer cents. Money is never a float."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_cents(amount) -> int:
    """'18950.00' / Decimal / int -> 1895000. Raises ValueError on garbage, floats, or >2 decimals."""
    if isinstance(amount, float) or isinstance(amount, bool):
        raise ValueError("float amounts are not accepted")
    try:
        d = Decimal(str(amount).strip())
    except InvalidOperation as e:
        raise ValueError(f"not a decimal: {amount!r}") from e
    if not d.is_finite() or d != d.quantize(Decimal("0.01")):
        raise ValueError(f"not a 2-decimal amount: {amount!r}")
    return int((d * 100).to_integral_value(ROUND_HALF_UP))


def eur(cents: int) -> str:
    """1895000 -> '18950.00'"""
    return f"{Decimal(cents) / 100:.2f}"


def eur_display(cents: int) -> str:
    """1895000 -> '€18,950.00'"""
    return f"€{Decimal(cents) / 100:,.2f}"
