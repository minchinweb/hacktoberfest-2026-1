"""Pure checks. Nothing here corrects data; callers turn problems into `; REVIEW:` comments."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def parse_amount(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d.quantize(CENT, ROUND_HALF_UP) if d.is_finite() and d > 0 else None


def distance_mismatch(spoken: Decimal, odometer_km: Decimal, tolerance: Decimal) -> bool:
    if odometer_km == 0:
        return spoken != 0
    return abs(spoken - odometer_km) / odometer_km > tolerance


def gst_split(gross: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    net = (gross / (1 + rate)).quantize(CENT, ROUND_HALF_UP)
    return net, gross - net


def allowance(km: Decimal, ytd_before: Decimal, threshold: Decimal, r1: Decimal, r2: Decimal):
    """Split km across the yearly tier threshold. Returns (amount, km_first, km_after)."""
    first = max(Decimal(0), min(km, threshold - ytd_before))
    after = km - first
    return (first * r1 + after * r2).quantize(CENT, ROUND_HALF_UP), first, after
