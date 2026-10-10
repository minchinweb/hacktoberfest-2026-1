"""CRA-style kilometre logbook, read back from the ledger (which includes the staging file)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path

from beancount import loader
from beancount.core import data

COLUMNS = ["date", "vehicle", "start_odometer", "end_odometer", "km", "destination", "purpose", "status"]


def build(ledger: Path, cfg: dict, year: int) -> dict:
    entries, errors, _ = loader.load_file(str(ledger))
    biz_acct, per_acct = cfg["mileage"]["business_account"], cfg["mileage"]["personal_account"]
    rows, business, personal = [], Decimal(0), Decimal(0)
    for e in entries:
        if not isinstance(e, data.Transaction) or e.date.year != year:
            continue
        for p in e.postings:
            if p.units is None or p.units.currency != "KM":
                continue
            km = -p.units.number
            if p.account == per_acct:
                personal += km
            elif p.account == biz_acct:
                business += km
                m = e.meta
                rows.append({
                    "date": e.date.isoformat(), "vehicle": m.get("vehicle", ""),
                    "start_odometer": m.get("odometer-start", ""), "end_odometer": m.get("odometer-end", ""),
                    "km": km, "destination": m.get("destination", ""), "purpose": m.get("purpose", ""),
                    "status": "pending" if e.flag == "!" else "confirmed",
                })
    rows.sort(key=lambda r: r["date"])
    total = business + personal
    pct = (business / total * 100).quantize(Decimal("0.1")) if total else Decimal(0)
    return {"year": year, "rows": rows, "business_km": business, "personal_km": personal,
            "business_use_pct": pct, "ledger_errors": [str(x) for x in errors]}


def to_csv(lb: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(lb["rows"])
    return buf.getvalue()


def summary(lb: dict) -> str:
    return (f"{lb['year']}: business {lb['business_km']} km, personal {lb['personal_km']} km, "
            f"business use {lb['business_use_pct']}%")
