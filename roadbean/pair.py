"""Turn extracted events into Entry objects: trip pairing, odometer checks, receipts, allowance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .config import dec, match_rule, resolve_vehicle
from .emit import Entry, fmt_num, money, parse_staging
from .memo import Memo, Photo
from .validate import allowance, distance_mismatch, gst_split, parse_amount


@dataclass
class State:
    """What earlier runs already staged: last odometer per vehicle and business km per year."""
    last_end: dict[str, int] = field(default_factory=dict)
    business_ytd: dict[int, Decimal] = field(default_factory=dict)

    @classmethod
    def from_staging(cls, text: str, cfg: dict) -> "State":
        st = cls()
        biz = cfg["mileage"]["business_account"]
        for e in sorted(parse_staging(text), key=lambda e: e["date"]):
            v, end = e["meta"].get("vehicle"), e["meta"].get("odometer-end")
            if v and end and end.isdigit():
                st.last_end[v] = int(end)
            for acct, amt, com in e["postings"]:
                if acct == biz and com == "KM":
                    st.business_ytd[e["date"].year] = st.business_ytd.get(e["date"].year, Decimal(0)) - amt
        return st


@dataclass
class Event:
    memo: Memo
    x: dict

    @property
    def ts(self) -> datetime:
        return self.memo.ts


class Builder:
    def __init__(self, cfg: dict, rules: list[dict], state: State, photos: list[Photo], now: datetime,
                 receipt_images: dict | None = None):
        self.cfg, self.rules, self.state, self.photos, self.now = cfg, rules, state, photos, now
        self.entries: list[Entry] = []
        self.warnings: list[str] = []
        self.pending: dict[str, Event] = {}
        self.open_trips: list[Event] = []  # starts still waiting for an end memo after this run
        self.used_photos: set[Path] = set()
        self.receipt_images = receipt_images or {}  # photo path -> {"amount", "payee"}
        self.cur = cfg["currency"]

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @staticmethod
    def _doubts(events: list[Event]) -> list[str]:
        return [f"model confidence {e.x['confidence']} for {e.memo.name}; check the transcript"
                for e in events if e.x["confidence"] != "high"]

    # ---- mileage ---------------------------------------------------------------------------------
    def vehicle(self, ev: Event):
        key, v, matched = resolve_vehicle(self.cfg, ev.x["vehicle"])
        return key, v, ([] if matched else [f"vehicle {ev.x['vehicle']!r} not in config; used default {key!r}"])

    def _flagged(self, ev: Event, title: str, reviews: list[str], extra_meta=()) -> None:
        self.entries.append(Entry(ev.ts.date(), "Mileage", title,
                                  [("memo-sha", ev.memo.sha), *extra_meta, ("transcript", ev.memo.transcript)], reviews,
                                  origin=ev.memo.sha))
        self.warn(f"{ev.memo.name}: {title}: {'; '.join(reviews)}")

    def _loc(self, ev: Event):
        loc = ev.memo.location
        return [("location", f"{loc[0]},{loc[1]}")] if loc else []

    def _book(self, key: str, v: dict, events: list[Event], start: int | None, end: int | None, km: Decimal,
              reviews: list[str], business: bool | None) -> None:
        """Emit opening / personal-gap / trip / allowance entries for one resolved trip."""
        n_before = len(self.entries)
        self._book_entries(key, v, events, start, end, km, reviews, business)
        for e in self.entries[n_before:]:
            e.origin = events[0].memo.sha

    def _book_entries(self, key, v, events, start, end, km, reviews, business) -> None:
        cfg, m = self.cfg, self.cfg["mileage"]
        first = events[0]
        reviews = reviews + self._doubts(events)
        dest = next((e.x["destination"] for e in events if e.x["destination"]), None)
        purpose = next((e.x["purpose"] for e in events if e.x["purpose"]), None)
        acct = v["odometer_account"]
        is_biz = m["default_business"] if business is None else business
        km_acct = m["business_account"] if is_biz else m["personal_account"]
        prev = self.state.last_end.get(key)
        d = first.ts.date()

        if start is not None and prev is None:
            self.entries.append(Entry(
                d, "Odometer opening", f"{key} at first logged trip",
                [("vehicle", key), ("odometer-end", start)],
                ["first logged trip for this vehicle; remove if your ledger already has an opening odometer"],
                [(acct, str(start), "KM"), (m["opening_account"], f"-{start}", "KM")], vehicle=key))
        elif start is not None and prev is not None:
            if start > prev:
                gap = start - prev
                self.entries.append(Entry(
                    d, "Mileage", f"Personal driving ({gap} km)",
                    [("memo-sha", first.memo.sha), ("vehicle", key), ("odometer-start", prev), ("odometer-end", start)],
                    [f"gap of {gap} km exceeds max_trip_km; check for missed memos"] if gap > m["max_trip_km"] else [],
                    [(acct, str(gap), "KM"), (m["personal_account"], f"-{gap}", "KM")], vehicle=key))
            elif start < prev:
                reviews = reviews + [f"start odometer {start} is below previous end {prev}; probably misheard (not corrected)"]

        title = " — ".join(x for x in (dest, purpose) if x) or "Trip"
        meta: list[tuple[str, object]] = [("memo-sha", first.memo.sha)]
        if len(events) > 1:
            meta.append(("memo-sha-end", events[-1].memo.sha))
        meta.append(("vehicle", key))
        if start is not None:
            meta.append(("odometer-start", start))
        if end is not None:
            meta.append(("odometer-end", end))
        if dest:
            meta.append(("destination", dest))
        if purpose:
            meta.append(("purpose", purpose))
        meta += self._loc(first)
        meta.append(("transcript", " / ".join(e.memo.transcript for e in events if e.memo.transcript)))
        entry = Entry(d, "Mileage" if is_biz else "Mileage (personal)", title, meta, reviews,
                      [(acct, fmt_num(km), "KM"), (km_acct, "-" + fmt_num(km), "KM")], vehicle=key)
        if end is not None:
            entry.assertion = (events[-1].ts.date() + timedelta(days=1), acct, end)
            entry.assertion_ok = not reviews
        self.entries.append(entry)
        if end is not None:
            self.state.last_end[key] = end

        if is_biz:
            ytd = self.state.business_ytd.get(d.year, Decimal(0))
            self.state.business_ytd[d.year] = ytd + km
            a = cfg["allowance"]
            if a["enabled"]:
                amt, k1, k2 = allowance(km, ytd, dec(a["threshold_km"]), dec(a["rate_first"]), dec(a["rate_after"]))
                parts = [f"{fmt_num(k)} km @ {r}" for k, r in ((k1, a["rate_first"]), (k2, a["rate_after"])) if k]
                self.entries.append(Entry(
                    d, "Mileage allowance", " + ".join(parts),
                    [("memo-sha", first.memo.sha), ("vehicle", key)], [],
                    [(a["expense_account"], money(amt), self.cur), (a["payable_account"], "-" + money(amt), self.cur)]))

    def pair(self, start: Event, end: Event) -> None:
        key, v, rv = self.vehicle(start)
        m = self.cfg["mileage"]
        s, e = start.x["odometer"], end.x["odometer"]
        spoken = end.x["distance_km"] or start.x["distance_km"]
        reviews = list(rv)
        biz = start.x["business"] if start.x["business"] is not None else end.x["business"]
        end_meta = [("memo-sha-end", end.memo.sha)]
        if s is None or e is None:
            if spoken is None or (s is None and e is None):
                return self._flagged(start, "Trip needs review",
                                     reviews + ["odometer reading missing; trip not computed"], end_meta)
            s, e = (s, s + int(spoken)) if s is not None else (e - int(spoken), e)
            reviews.append("one odometer reading was missing; derived from spoken distance")
        if e <= s:
            return self._flagged(start, "Trip needs review", reviews + [f"end odometer {e} is not above start {s}"],
                                 end_meta + [("odometer-start", s), ("odometer-end", e)])
        km = Decimal(e - s)
        if km > m["max_trip_km"]:
            return self._flagged(start, "Trip needs review",
                                 reviews + [f"{km} km exceeds max_trip_km {m['max_trip_km']}"],
                                 end_meta + [("odometer-start", s), ("odometer-end", e)])
        if spoken is not None and distance_mismatch(spoken, km, dec(m["distance_tolerance"])):
            reviews.append(f"spoken distance {fmt_num(spoken)} km differs from odometer distance {km} km")
        self._book(key, v, [start, end], s, e, km, reviews, biz)

    def single(self, ev: Event) -> None:
        """One memo covering a whole trip; the spoken odometer is the reading at the end."""
        key, v, rv = self.vehicle(ev)
        reviews = list(rv)
        e, spoken = ev.x["odometer"], ev.x["distance_km"]
        prev = self.state.last_end.get(key)
        if spoken is not None and e is not None:
            km, s = spoken, e - int(spoken)
        elif e is not None and prev is not None:
            s, km = prev, Decimal(e - prev)
            if km <= 0:
                return self._flagged(ev, "Trip needs review", [f"odometer {e} is not above previous end {prev}"])
        elif spoken is not None:
            km = spoken
            if prev is not None:
                s, e = prev, prev + int(spoken)
                reviews.append("no odometer spoken; end reading estimated from previous end plus distance")
            else:
                s = None
                reviews.append("no odometer spoken and no previous reading; odometer not tracked")
        else:
            return self._flagged(ev, "Trip needs review", reviews + ["no distance and no usable odometer"])
        if km > self.cfg["mileage"]["max_trip_km"]:
            return self._flagged(ev, "Trip needs review", reviews + [f"{fmt_num(km)} km exceeds max_trip_km"])
        self._book(key, v, [ev], s, e, km, reviews, ev.x["business"])

    def open_trip_entry(self, ev: Event) -> Entry:
        """The (commented-out) placeholder for a trip start that has no end memo yet."""
        x = ev.x
        key = resolve_vehicle(self.cfg, x["vehicle"])[0]
        title = " — ".join(p for p in ("Open trip", x["destination"], x["purpose"]) if p)
        meta: list[tuple[str, object]] = [("memo-sha", ev.memo.sha), ("vehicle", key)]
        if x["odometer"] is not None:
            meta.append(("odometer-start", x["odometer"]))
        for k in ("destination", "purpose"):
            if x[k]:
                meta.append((k, x[k]))
        meta += self._loc(ev)
        meta.append(("transcript", ev.memo.transcript))
        days = self.cfg["mileage"]["stale_after_days"]
        return Entry(ev.ts.date(), "Mileage", title, meta,
                     [f"no end memo yet; flagged as unmatched after {ev.ts + timedelta(days=days):%Y-%m-%d %H:%M}"],
                     origin=ev.memo.sha)

    def orphan_end(self, ev: Event) -> None:
        meta = [("odometer-end", ev.x["odometer"])] if ev.x["odometer"] is not None else []
        self._flagged(ev, "Trip end without start", ["no matching trip start memo"], meta)

    # ---- receipts --------------------------------------------------------------------------------
    def _photo_for(self, ev: Event) -> Photo | None:
        win = timedelta(minutes=self.cfg["receipts"]["photo_link_window_min"])
        best = None
        for p in self.photos:
            if p.path in self.used_photos or abs(p.ts - ev.ts) > win:
                continue
            if best is None or abs(p.ts - ev.ts) < abs(best.ts - ev.ts):
                best = p
        if best:
            self.used_photos.add(best.path)
        return best

    def receipt(self, ev: Event) -> None:
        x, r, g = ev.x, self.cfg["receipts"], self.cfg["gst"]
        reviews: list[str] = self._doubts([ev])
        photo = self._photo_for(ev)
        amount = parse_amount(x["amount"])
        payee = x["payee"]
        extra: list[tuple[str, object]] = []
        if photo:
            extra += [("receipt", photo.path.name), ("receipt-sha", photo.sha)]
            seen = self.receipt_images.get(photo.path)
            if seen is not None:
                pa = parse_amount(seen.get("amount"))
                if pa is not None:
                    if amount is not None and pa != amount:
                        reviews.append(f"memo amount {amount} differs from receipt photo total {pa}; photo total used")
                    amount = pa
                payee = payee or seen.get("payee")
        else:
            reviews.append("no receipt image")
        rule = match_rule(self.rules, payee, x["category_hint"])
        account = rule["account"] if rule else r["uncategorized_account"]
        if not rule:
            reviews.append("no rule matched payee; left uncategorized")
        gst = x["gst"] or (rule or {}).get("gst")
        pay = x["payment"] or r["default_payment"]
        pay_acct = r["payment_accounts"].get(pay)
        if not pay_acct:
            reviews.append(f"unknown payment method {pay!r}")
            pay_acct = "Liabilities:Unknown-Payment"
        cur = x["currency"] or self.cur
        hint = (x["category_hint"] or "").title()
        if rule and "payee" in rule and payee:
            payee = rule["payee"]  # canonical spelling, whatever the speech engine produced
        title = payee or hint or "Receipt"
        narr = hint or "Receipt" if payee else (x["purpose"] or "Receipt")
        meta: list[tuple[str, object]] = [("memo-sha", ev.memo.sha), *extra]
        if gst:
            meta.append(("gst", gst))
        meta.append(("transcript", ev.memo.transcript))
        if x["business"] is False:
            reviews.append("marked personal")
        if amount is None:
            reviews.append(f"amount {x['amount']!r} is missing or not a positive number")
            self.entries.append(Entry(ev.ts.date(), title, narr, meta, reviews))
            self.warn(f"{ev.memo.name}: receipt without usable amount")
            return
        postings = []
        if gst == "g" and g["split"] and cur == self.cur:
            net, tax = gst_split(amount, dec(g["rate"]))
            postings += [(account, money(net), cur), (g["account"], money(tax), cur)]
        else:
            postings.append((account, money(amount), cur))
        postings.append((pay_acct, "-" + money(amount), cur))
        self.entries.append(Entry(ev.ts.date(), title, narr, meta, reviews, postings))

    # ---- driver ----------------------------------------------------------------------------------
    def run(self, events: list[Event]) -> None:
        stale = timedelta(days=self.cfg["mileage"]["stale_after_days"])
        for ev in sorted(events, key=lambda e: e.ts):
            t = ev.x["type"]
            vkey = resolve_vehicle(self.cfg, ev.x["vehicle"])[0]
            if t == "trip_start":
                old = self.pending.pop(vkey, None)
                if old:
                    self._flagged(old, "Trip start without end", ["followed by another start before any end"])
                self.pending[vkey] = ev
            elif t == "trip_end":
                st = self.pending.pop(vkey, None)
                if st:
                    self.pair(st, ev)
                else:
                    self.orphan_end(ev)
            elif t == "trip":
                self.single(ev)
            elif t == "receipt":
                self.receipt(ev)
            else:
                self.entries.append(Entry(
                    ev.ts.date(), "Note", ev.memo.transcript[:60] or "voice note",
                    [("memo-sha", ev.memo.sha), ("transcript", ev.memo.transcript)],
                    ["not a trip or receipt; file by hand"]))
        for vkey, st in list(self.pending.items()):
            if self.now - st.ts > stale:
                self._flagged(st, "Trip start without end",
                              [f"no end memo after {self.cfg['mileage']['stale_after_days']} days"])
                del self.pending[vkey]
            else:
                self.open_trips.append(st)
