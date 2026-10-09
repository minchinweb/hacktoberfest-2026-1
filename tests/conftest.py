import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from beancount import loader

from roadbean.config import load_config, load_rules
from roadbean.pipeline import process

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 12, 12, 0)

BLANK = {
    "type": "note", "odometer": None, "distance_km": None, "destination": None, "purpose": None,
    "business": None, "vehicle": None, "payee": None, "amount": None, "currency": None, "payment": None,
    "category_hint": None, "gst": None, "confidence": "high", "transcript": "",
}


def memo(ts: str, type: str, transcript: str = "memo", **kw) -> tuple[str, dict]:
    return ts, {**BLANK, "type": type, "transcript": transcript, **kw}


@pytest.fixture
def cfg():
    c = load_config(ROOT / "roadbean.example.toml")
    return c


@pytest.fixture
def rules():
    return load_rules(ROOT / "rules.example.toml")


@pytest.fixture
def run(tmp_path, cfg, rules):
    """run(memos, staging=<Path>, now=...) writes .extract.json files and processes them (no model)."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    staging = tmp_path / "staging.bean"

    def _run(memos, now=NOW, cfg_=None, photos=(), sidecars=None):
        for ts, x in memos:
            (inbox / f"{ts}.extract.json").write_text(json.dumps(x), encoding="utf-8")
        for name, content in photos:
            (inbox / name).write_bytes(content)
        for name, data in (sidecars or {}).items():
            (inbox / name).write_text(json.dumps(data), encoding="utf-8")
        return process(inbox, cfg_ or cfg, rules, staging, from_json=True, now=now)

    _run.staging = staging
    _run.inbox = inbox
    return _run


def bean_errors(staging_text: str) -> list:
    """Load staging as a ledger, opening every account it mentions."""
    accounts = sorted(set(re.findall(r"^\s+([A-Z][A-Za-z0-9-]*(?::[A-Za-z0-9-]+)+)\s+-?[\d.]+ ", staging_text, re.M))
                      | set(re.findall(r"balance (\S+)", staging_text)))
    head = ['option "operating_currency" "CAD"', "2026-01-01 commodity KM", "2026-01-01 commodity CAD"]
    for a in accounts:
        head.append(f"2026-01-01 open {a}")
    _, errors, _ = loader.load_string("\n".join(head) + "\n\n" + staging_text)
    return errors
