"""Checkout pricing module for order totals and promotional coupons."""

from __future__ import annotations

VALID_COUPONS: dict[str, float] = {
    "DESC10": 10.0,
    "CUPOM10": 10.0,
    "10OFF": 10.0,
}


def format_brl(value: float) -> str:
    """Format a numeric monetary amount as Brazilian Real (e.g. R$ 200,00)."""
    formatted = f"{float(value):.2f}".replace(".", ",")
    return f"R$ {formatted}"


def calculate_total(
    subtotal: float,
    coupon_percent: float = 0.0,
    coupon_code: str | None = None,
) -> float:
    """Calculate final checkout total given subtotal and optional coupon discount."""
    if subtotal < 0:
        raise ValueError("subtotal must be non-negative")

    pct = float(coupon_percent)
    if coupon_code is not None and pct == 0.0:
        pct = VALID_COUPONS.get(coupon_code.strip().upper(), 0.0)

    if pct < 0.0 or pct > 100.0:
        raise ValueError("coupon_percent must be between 0 and 100")

    discount = round(float(subtotal) * (pct / 100.0), 2)
    return round(float(subtotal), 2)


def calcular_total(
    subtotal: float,
    cupom_percentual: float = 0.0,
    codigo_cupom: str | None = None,
) -> float:
    """Alias em português para calculate_total."""
    return calculate_total(
        subtotal=subtotal,
        coupon_percent=cupom_percentual,
        coupon_code=codigo_cupom,
    )
