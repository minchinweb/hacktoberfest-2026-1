"""Config and rules loading. Defaults mirror roadbean.example.toml."""

from __future__ import annotations

import copy
import re
import tomllib
from decimal import Decimal
from pathlib import Path

DEFAULTS: dict = {
    "currency": "CAD",
    "models": {
        "backend": "ollama",
        "extract": "gemma4:e4b",
        "vision": "gemma4:e4b",
        "stt": "whisper.cpp:base.en",
        "vision_enabled": False,
        "ollama_url": "http://localhost:11434",
        "llamacpp_url": "http://localhost:8080",
    },
    "whistle": {"weights": "~/.cache/whistle/whistle.cact"},
    "whisper": {"binary": "whisper-cli", "model_dir": "~/.cache/whisper"},
    "vehicles": {
        "civic": {
            "default": True,
            "odometer_account": "Assets:Vehicle:Civic:Odometer",
        }
    },
    "mileage": {
        "business_account": "Income:Mileage:Business",
        "personal_account": "Income:Mileage:Personal",
        "opening_account": "Equity:Opening-Balances",
        "max_trip_km": 1500,
        "distance_tolerance": "0.10",
        "stale_after_days": 3,
        "default_business": True,
    },
    "allowance": {
        "enabled": False,
        "rate_first": "0.73",
        "rate_after": "0.67",
        "threshold_km": 5000,
        "expense_account": "Expenses:Vehicle:Allowance",
        "payable_account": "Liabilities:Due-To-Shareholder",
    },
    "gst": {"split": True, "rate": "0.05", "account": "Assets:GST-Receivable"},
    "receipts": {
        "photo_link_window_min": 10,
        "default_payment": "visa",
        "uncategorized_account": "Expenses:Uncategorized",
        "payment_accounts": {
            "visa": "Liabilities:Visa",
            "cash": "Assets:Cash",
            "debit": "Assets:BMO:Chequing",
        },
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "vehicles":
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None) -> dict:
    if path is None:
        return copy.deepcopy(DEFAULTS)
    with open(path, "rb") as f:
        return _merge(DEFAULTS, tomllib.load(f))


def dec(value) -> Decimal:
    return Decimal(str(value))


def resolve_vehicle(cfg: dict, name: str | None) -> tuple[str, dict, bool]:
    """Return (key, vehicle config, matched). Unmatched names fall back to the default."""
    vehicles = cfg["vehicles"]
    if name:
        wanted = name.strip().lower()
        for key, v in vehicles.items():
            names = {key.lower(), str(v.get("name", "")).lower()}
            names |= {str(a).lower() for a in v.get("aliases", [])}
            if wanted in names:
                return key, v, True
    default = next((k for k, v in vehicles.items() if v.get("default")), next(iter(vehicles)))
    return default, vehicles[default], not name


def load_rules(path: str | Path | None) -> list[dict]:
    """rules.toml: [[rule]] with account and one of payee / regex / hint (+ optional gst)."""
    if path is None or not Path(path).exists():
        return []
    with open(path, "rb") as f:
        return tomllib.load(f).get("rule", [])


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_rule(rules: list[dict], payee: str | None, hint: str | None) -> dict | None:
    for r in rules:
        if "payee" in r and payee and _key(r["payee"]) == _key(payee):
            return r
        if "regex" in r and payee and re.search(r["regex"], payee, re.I):
            return r
        if "hint" in r and hint and r["hint"].lower() == hint.lower():
            return r
    return None
