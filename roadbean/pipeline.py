"""process: inbox -> transcripts/extracts (model) -> entries (pure Python) -> staging file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import stt
from .backends import BackendError
from .config import resolve_vehicle
from .emit import HEADER, filter_assertions, parse_staging, render_all, staged_shas, supersede_staged
from .extract import build_prompt, normalize
from .memo import Memo, discover
from .pair import Builder, Event, State


@dataclass
class Result:
    new_text: str = ""            # rendered new entries only
    staging_text: str = ""        # full staging file after this run
    entries: int = 0
    skipped: int = 0              # memos already in staging
    warnings: list[str] = field(default_factory=list)
    open_trips: list[str] = field(default_factory=list)  # trip starts with no end memo yet


def _load_cached(m: Memo) -> dict | None:
    if not m.extract_path.exists():
        return None
    raw = json.loads(m.extract_path.read_text(encoding="utf-8"))
    m.transcript = raw.get("transcript") or (
        m.transcript_path.read_text(encoding="utf-8").strip() if m.transcript_path.exists() else "")
    return normalize(raw)


def _extract_one(m: Memo, cfg, rules, backend, dry_run: bool) -> dict:
    if m.transcript_path.exists():
        m.transcript = m.transcript_path.read_text(encoding="utf-8").strip()
    else:
        m.transcript = stt.transcribe(m.audio, cfg, rules, backend)
        if not dry_run:
            m.transcript_path.write_text(m.transcript + "\n", encoding="utf-8")
    raw = backend.extract(build_prompt(cfg, m.transcript))
    raw["transcript"] = m.transcript  # filled in by code, never by the model
    if not dry_run:
        m.extract_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return normalize(raw)


def _receipt_images(photos, receipt_events, cfg, backend, from_json: bool, dry_run: bool) -> dict:
    """Photo totals: from a `<photo>.extract.json` sidecar, or the vision model when enabled."""
    win = timedelta(minutes=cfg["receipts"]["photo_link_window_min"])
    out = {}
    for p in photos:
        if not any(abs(p.ts - e.ts) <= win for e in receipt_events):
            continue
        side = p.path.with_suffix(".extract.json")
        if side.exists():
            out[p.path] = json.loads(side.read_text(encoding="utf-8"))
        elif cfg["models"]["vision_enabled"] and not from_json and backend is not None:
            try:
                out[p.path] = backend.describe_receipt(p.path)
                if not dry_run:
                    side.write_text(json.dumps(out[p.path], indent=2) + "\n", encoding="utf-8")
            except (BackendError, NotImplementedError) as e:
                out.setdefault("_warnings", []).append(f"{p.path.name}: vision failed: {e}")
    return out


def process(inbox: Path, cfg: dict, rules: list[dict], staging: Path | None, backend=None, *,
            from_json: bool = False, dry_run: bool = False, reextract: bool = False,
            since: datetime | None = None, now: datetime | None = None) -> Result:
    now = now or datetime.now()
    res = Result()
    existing = staging.read_text(encoding="utf-8") if staging and staging.exists() else ""
    staged = parse_staging(existing)
    seen = staged_shas(staged)

    memos, photos = discover(inbox, since)
    events: list[Event] = []
    for m in memos:
        if m.sha in seen:
            res.skipped += 1
            continue
        x = None if reextract else _load_cached(m)
        if x is None:
            if from_json or backend is None or m.audio is None:
                res.warnings.append(f"{m.name}: no .extract.json and --from-json given; skipped")
                continue
            try:
                x = _extract_one(m, cfg, rules, backend, dry_run)
            except (BackendError, stt.SttError) as e:
                res.warnings.append(f"{m.name}: {e}; skipped (will retry next run)")
                continue
        events.append(Event(m, x))

    photos = [p for p in photos if p.sha not in seen]
    images = _receipt_images(photos, [e for e in events if e.x["type"] == "receipt"], cfg, backend, from_json, dry_run)
    res.warnings += images.pop("_warnings", [])
    b = Builder(cfg, rules, State.from_staging(existing, cfg), photos, now, images)
    b.run(events)
    res.warnings += b.warnings
    stale_days = cfg["mileage"]["stale_after_days"]
    for ev in b.open_trips:
        x = ev.x
        what = ", ".join(p for p in (f"odometer {x['odometer']}" if x["odometer"] is not None else "",
                                     f"to {x['destination']}" if x["destination"] else "") if p)
        res.open_trips.append(
            f"started {ev.ts:%Y-%m-%d %H:%M}{' (' + what + ')' if what else ''}, no end memo yet; "
            f"flagged as unmatched after {(ev.ts + timedelta(days=stale_days)):%Y-%m-%d %H:%M}")

    entries = sorted(b.entries, key=lambda e: e.date)  # stable: opening, gap, trip, allowance keep order
    filter_assertions(entries)
    res.entries = len(entries)
    res.new_text = render_all(entries)
    accounts = {k: v["odometer_account"] for k, v in cfg["vehicles"].items()}
    base = supersede_staged(existing, entries, accounts) if entries else existing
    if entries:
        base = base if base.strip() else HEADER
        res.staging_text = base.rstrip("\n") + "\n\n" + res.new_text
    else:
        res.staging_text = existing
    if staging and not dry_run and entries:
        staging.write_text(res.staging_text, encoding="utf-8")
    return res
