"""Extraction contract: JSON schema, prompt loading, and normalisation of model output."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

TYPES = ["trip_start", "trip_end", "trip", "receipt", "note"]

SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": TYPES},
        "odometer": {"type": ["integer", "null"]},
        "distance_km": {"type": ["number", "null"]},
        "destination": {"type": ["string", "null"]},
        "purpose": {"type": ["string", "null"]},
        "business": {"type": ["boolean", "null"]},
        "vehicle": {"type": ["string", "null"]},
        "payee": {"type": ["string", "null"]},
        "amount": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "payment": {"type": ["string", "null"], "enum": ["visa", "cash", "debit", None]},
        "category_hint": {"type": ["string", "null"]},
        "gst": {"type": ["string", "null"], "enum": ["g", "z", "e", None]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["type", "confidence"],
}

PROMPT_VERSION = "extract_v1"


def prompt_path(cfg: dict) -> Path:
    custom = cfg.get("models", {}).get("prompt")
    if custom:
        return Path(custom)
    return Path(__file__).resolve().parent.parent / "prompts" / f"{PROMPT_VERSION}.md"


def build_prompt(cfg: dict, transcript: str) -> str:
    return prompt_path(cfg).read_text(encoding="utf-8").replace("{transcript}", transcript.strip())


def _int(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[,\s]", "", str(v))
    return int(digits) if digits.isdigit() else None


def _dec(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        return None


def _str(v):
    v = None if v is None else str(v).strip()
    return v or None


def normalize(raw: dict) -> dict:
    """Coerce loosely-typed model output into the contract. Unusable values become None, never guesses."""
    t = raw.get("type")
    gst = _str(raw.get("gst"))
    pay = _str(raw.get("payment"))
    amount = raw.get("amount")
    return {
        "type": t if t in TYPES else "note",
        "odometer": _int(raw.get("odometer")),
        "distance_km": _dec(raw.get("distance_km")),
        "destination": _str(raw.get("destination")),
        "purpose": _str(raw.get("purpose")),
        "business": raw.get("business") if isinstance(raw.get("business"), bool) else None,
        "vehicle": _str(raw.get("vehicle")),
        "payee": _str(raw.get("payee")),
        "amount": None if amount is None else str(amount).replace("$", "").replace(",", "").strip(),
        "currency": (_str(raw.get("currency")) or "").upper() or None,
        "payment": pay.lower() if pay and pay.lower() in ("visa", "cash", "debit") else None,
        "category_hint": _str(raw.get("category_hint")),
        "gst": gst.lower() if gst and gst.lower() in ("g", "z", "e") else None,
        "confidence": raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "low",
        "transcript": _str(raw.get("transcript")) or "",
    }
