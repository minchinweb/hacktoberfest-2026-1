"""Discover memos and photos in an inbox. The filename timestamp is the authoritative event time."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

AUDIO_EXT = {".m4a", ".wav", ".mp3", ".ogg", ".opus", ".aac", ".3gp", ".amr", ".flac"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d{6})")
TS_FMT = "%Y-%m-%dT%H%M%S"


def sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


@dataclass
class Memo:
    name: str
    ts: datetime
    sha: str
    audio: Path | None
    dir: Path
    transcript: str = ""
    extract: dict = field(default_factory=dict)
    location: tuple[float, float] | None = None

    @property
    def transcript_path(self) -> Path:
        return self.dir / f"{self.name}.transcript.txt"

    @property
    def extract_path(self) -> Path:
        return self.dir / f"{self.name}.extract.json"


@dataclass
class Photo:
    path: Path
    ts: datetime
    sha: str


def _stem_ts(stem: str) -> datetime | None:
    m = TS_RE.match(stem)
    return datetime.strptime(m.group(1), TS_FMT) if m else None


def _location(d: Path, name: str) -> tuple[float, float] | None:
    p = d / f"{name}.json"
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        return round(float(j["latitude"]), 3), round(float(j["longitude"]), 3)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def discover(inbox: Path, since: datetime | None = None) -> tuple[list[Memo], list[Photo]]:
    """Memos are audio files with a timestamped name, or orphan *.extract.json (for --from-json)."""
    memos: dict[str, Memo] = {}
    photos: list[Photo] = []
    for p in sorted(inbox.iterdir()):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf in AUDIO_EXT:
            ts = _stem_ts(p.stem)
            if ts is None:
                continue
            memos[p.stem] = Memo(p.stem, ts, sha12(p.read_bytes()), p, inbox, location=_location(inbox, p.stem))
        elif suf in IMAGE_EXT:
            ts = _stem_ts(p.stem) or datetime.fromtimestamp(p.stat().st_mtime)
            photos.append(Photo(p, ts, sha12(p.read_bytes())))
    for p in sorted(inbox.glob("*.extract.json")):
        name = p.name[: -len(".extract.json")]
        ts = _stem_ts(name)
        is_photo_sidecar = any((inbox / f"{name}{e}").exists() for e in IMAGE_EXT)
        if name not in memos and ts is not None and not is_photo_sidecar:
            memos[name] = Memo(name, ts, sha12(name.encode() + p.read_bytes()), None, inbox, location=_location(inbox, name))
    out = sorted(memos.values(), key=lambda m: m.ts)
    if since:
        out = [m for m in out if m.ts >= since]
    return out, photos
