"""Beancount rendering and staging-file parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import __version__

SOURCE = f"roadbean {__version__}"  # stamped on every entry so you can tell what wrote it


def fmt_num(d: Decimal | int) -> str:
    s = format(Decimal(d), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def money(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.01")), "f")


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Entry:
    date: date
    payee: str
    narration: str
    meta: list[tuple[str, object]] = field(default_factory=list)
    reviews: list[str] = field(default_factory=list)
    postings: list[tuple[str, str, str]] = field(default_factory=list)  # account, amount, commodity
    vehicle: str | None = None
    assertion: tuple[date, str, int] | None = None  # date, account, reading
    assertion_ok: bool = True
    origin: str | None = None  # sha of the memo that started this entry's trip (to replace its open-trip block)

    def render(self) -> str:
        head = f"{self.date.isoformat()} ! {quote(self.payee)} {quote(self.narration)}"
        lines = [head, f"  source: {quote(SOURCE)}"]
        for k, v in self.meta:
            lines.append(f"  {k}: {quote(v) if isinstance(v, str) else v}")
        lines += [f"  ; REVIEW: {r}" for r in self.reviews]
        w = max((len(a) for a, _, _ in self.postings), default=0)
        for acct, amt, com in self.postings:
            lines.append(f"  {acct.ljust(w)}  {amt} {com}".rstrip())
        if self.assertion:
            d, acct, reading = self.assertion
            line = f"{d.isoformat()} balance {acct}  {reading} KM"
            lines.append(line if self.assertion_ok else f"; {line}  ; not asserted: odometer needs review")
        return "\n".join(lines)


HEADER = "; roadbean staging file: pending (!) entries. Review, then move into your ledger.\n"
ENTRY_RE = re.compile(r"^(\d{4}-\d\d-\d\d) [!*] ", re.M)
META_RE = re.compile(r'^\s+([a-z][a-z0-9_-]*): (.*)$')
POSTING_RE = re.compile(r"^\s+([A-Z][A-Za-z0-9:-]+)\s+(-?[\d.]+)\s+([A-Z][A-Z0-9]*)\s*$")
ASSERT_RE = re.compile(r"^(\d{4}-\d\d-\d\d) balance (\S+)\s+(\d+) KM[ \t]*$", re.M)


def parse_staging(text: str) -> list[dict]:
    """Parse staged entries into {date, meta, postings}. Tolerates hand edits; ignores what it can't read."""
    out = []
    blocks = re.split(r"\n\s*\n", text)
    for b in blocks:
        lines = [l for l in b.splitlines() if not l.startswith(";")]
        if not lines:
            continue
        m = ENTRY_RE.match(lines[0] + " ")
        if not m:
            continue
        meta, postings = {}, []
        for l in lines[1:]:
            mm = META_RE.match(l)
            if mm and not POSTING_RE.match(l):
                v = mm.group(2).strip()
                meta[mm.group(1)] = v[1:-1] if v.startswith('"') and v.endswith('"') else v
                continue
            pm = POSTING_RE.match(l)
            if pm:
                postings.append((pm.group(1), Decimal(pm.group(2)), pm.group(3)))
        out.append({"date": date.fromisoformat(m.group(1)), "meta": meta, "postings": postings})
    return out


def staged_shas(entries: list[dict]) -> set[str]:
    shas: set[str] = set()
    for e in entries:
        for k in ("memo-sha", "memo-sha-end", "receipt-sha"):
            if k in e["meta"]:
                shas.add(e["meta"][k])
    return shas


def filter_assertions(entries: list[Entry]) -> None:
    """Balance assertions are checked at the start of their date (the day after the trip), so a later
    entry for the same vehicle dated before that would break them. Drop such assertions."""
    for i, e in enumerate(entries):
        if e.assertion and any(o.vehicle == e.vehicle and o.date < e.assertion[0] for o in entries[i + 1:]):
            e.assertion = None


def supersede_staged(text: str, new_entries: list[Entry], accounts: dict[str, str]) -> str:
    """Comment out already-staged assertions that new entries (same vehicle) would invalidate."""
    earliest: dict[str, date] = {}
    for e in new_entries:
        if e.vehicle:
            earliest[accounts[e.vehicle]] = min(earliest.get(accounts[e.vehicle], e.date), e.date)

    def repl(m: re.Match) -> str:
        d, acct = date.fromisoformat(m.group(1)), m.group(2)
        if acct in earliest and earliest[acct] < d:
            return f"; {m.group(0)}  ; superseded by later activity"
        return m.group(0)

    return ASSERT_RE.sub(repl, text)


OPEN_MARK = "; OPEN TRIP:"
OPEN_RE = re.compile(r"^; OPEN TRIP:[^\n]*(?:\n;[^\n]*)*", re.M)
OPEN_SHA_RE = re.compile(r'^;\s+memo-sha: "([0-9a-f]+)"', re.M)


def render_open_trip(entry: Entry) -> str:
    """A trip with no end memo yet, as a commented-out block. Beancount ignores it; roadbean replaces it later."""
    body = "\n".join(("; " + l).rstrip() for l in entry.render().splitlines())
    return f"{OPEN_MARK} waiting for an end memo; not in the ledger yet, replaced when the trip is completed.\n{body}"


def find_open_blocks(text: str) -> dict[str, re.Match]:
    """Commented open-trip blocks in a staging file, by the sha of the memo that started the trip."""
    out = {}
    for m in OPEN_RE.finditer(text):
        sha = OPEN_SHA_RE.search(m.group(0))
        if sha:
            out[sha.group(1)] = m
    return out


def render_all(entries: list[Entry]) -> str:
    return "\n\n".join(e.render() for e in entries) + ("\n" if entries else "")
