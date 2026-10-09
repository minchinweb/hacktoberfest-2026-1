import json
import re
from decimal import Decimal

from conftest import NOW, ROOT, bean_errors, memo

from roadbean import logbook
from roadbean.extract import normalize
from roadbean.validate import allowance, gst_split

START = lambda ts, odo, **kw: memo(ts, "trip_start", odometer=odo, destination=kw.pop("dest", "Site A"), **kw)
END = lambda ts, odo, **kw: memo(ts, "trip_end", odometer=odo, **kw)


def norm(text: str) -> str:
    """Drop fields that legitimately differ between runs (hashes of audio, transcripts)."""
    return "\n".join(l for l in text.splitlines() if not re.match(r"\s+(transcript|memo-sha(-end)?|receipt-sha):", l))


def sample_memos():
    return [(p.name[: -len(".extract.json")], json.loads(p.read_text(encoding="utf-8")))
            for p in sorted((ROOT / "samples" / "expected").glob("*.extract.json"))]


def test_samples_match_expected_staging(run):
    run(sample_memos())
    got = run.staging.read_text(encoding="utf-8")
    want = (ROOT / "samples" / "expected" / "staging.bean").read_text(encoding="utf-8")
    assert norm(got) == norm(want)


def test_samples_pass_bean_check(run):
    run(sample_memos())
    assert bean_errors(run.staging.read_text(encoding="utf-8")) == []


def test_rerun_adds_nothing(run):
    run(sample_memos())
    before = run.staging.read_text(encoding="utf-8")
    res = run([])
    assert res.entries == 0 and res.skipped == 5
    assert run.staging.read_text(encoding="utf-8") == before


def test_start_end_pair_and_personal_gap(run):
    res = run([START("2026-10-09T080000", 1000), END("2026-10-09T090000", 1040),
               START("2026-10-09T150000", 1100), END("2026-10-09T160000", 1130)])
    t = res.new_text
    assert "Personal driving (60 km)" in t
    assert "odometer-start: 1100" in t
    assert "2026-10-10 balance Assets:Vehicle:Civic:Odometer  1130 KM" in t
    # first trip's assertion is dropped: the second trip is the same day and would break it
    assert "1040 KM" not in t
    assert bean_errors(run.staging.read_text(encoding="utf-8")) == []


def test_misheard_start_is_flagged_not_fixed(run):
    run([START("2026-10-09T080000", 1000), END("2026-10-09T090000", 1040)])
    res = run([START("2026-10-10T080000", 900), END("2026-10-10T090000", 940)])
    assert "start odometer 900 is below previous end 1040" in res.new_text
    assert "odometer-start: 900" in res.new_text
    assert "; 2026-10-11 balance" in res.new_text  # kept as a comment, not asserted
    assert "Personal driving" not in res.new_text


def test_start_without_end_is_held_back_then_flagged_when_stale(run):
    res = run([START("2026-10-10T080000", 2000)], now=NOW.replace(day=11))
    assert res.entries == 0 and any("held back" in w for w in res.warnings)
    res = run([], now=NOW.replace(day=20))
    assert res.entries == 1 and "Trip start without end" in res.new_text
    assert run([], now=NOW.replace(day=21)).entries == 0  # idempotent


def test_held_start_pairs_with_later_end(run):
    run([START("2026-10-10T080000", 2000)], now=NOW.replace(day=11))
    res = run([END("2026-10-10T090000", 2030)], now=NOW.replace(day=11))
    assert "odometer-end: 2030" in res.new_text and "Trip start without end" not in res.new_text


def test_end_without_start_and_bad_ends(run):
    res = run([END("2026-10-09T090000", 1040)])
    assert "Trip end without start" in res.new_text
    res = run([START("2026-10-10T080000", 3000), END("2026-10-10T090000", 2990)])
    assert "is not above start" in res.new_text
    res = run([START("2026-10-11T080000", 3000), END("2026-10-11T090000", 5000)])
    assert "exceeds max_trip_km" in res.new_text


def test_spoken_distance_mismatch_flagged(run):
    res = run([START("2026-10-09T080000", 1000), END("2026-10-09T090000", 1040, distance_km=60)])
    assert "spoken distance 60 km differs from odometer distance 40 km" in res.new_text


def test_single_memo_trip_needs_distance_or_previous_odometer(run):
    res = run([memo("2026-10-09T080000", "trip", odometer=1500)])
    assert "Trip needs review" in res.new_text and "Income:Mileage" not in res.new_text
    res = run([memo("2026-10-09T100000", "trip", odometer=1530, distance_km=30)])
    assert "odometer-start: 1500" in res.new_text and "Odometer opening" in res.new_text
    res = run([memo("2026-10-09T120000", "trip", odometer=1560)])  # distance from the previous reading
    assert "odometer-start: 1530" in res.new_text and "Assets:Vehicle:Civic:Odometer  30 KM" in res.new_text


def test_allowance_crosses_tier(run, cfg):
    cfg["mileage"]["max_trip_km"] = 10000
    run([memo("2026-03-01T080000", "trip", odometer=10000, distance_km=4990)], cfg_=cfg)
    res = run([memo("2026-03-02T080000", "trip", odometer=10020, distance_km=20)], cfg_=cfg)
    assert '"10 km @ 0.73 + 10 km @ 0.67"' in res.new_text
    assert "14.00 CAD" in res.new_text


def test_allowance_math_and_disabled(run, cfg):
    amt, k1, k2 = allowance(Decimal(42), Decimal(0), Decimal(5000), Decimal("0.73"), Decimal("0.67"))
    assert (amt, k1, k2) == (Decimal("30.66"), 42, 0)
    cfg["allowance"]["enabled"] = False
    res = run([memo("2026-03-01T080000", "trip", odometer=10042, distance_km=42)], cfg_=cfg)
    assert "allowance" not in res.new_text.lower()


def test_personal_trip_uses_personal_account(run):
    res = run([START("2026-10-09T080000", 1000, business=False), END("2026-10-09T090000", 1040)])
    assert "Income:Mileage:Personal" in res.new_text and "Income:Mileage:Business" not in res.new_text
    assert "Mileage allowance" not in res.new_text


def test_gst_split_and_no_split(run, cfg):
    assert gst_split(Decimal("62.50"), Decimal("0.05")) == (Decimal("59.52"), Decimal("2.98"))
    rec = memo("2026-10-09T101530", "receipt", payee="Petro-Canada", amount="62.50", category_hint="fuel", gst="g")
    res = run([rec])
    assert "59.52 CAD" in res.new_text and "Assets:GST-Receivable  2.98 CAD" in res.new_text
    cfg["gst"]["split"] = False
    res = run([memo("2026-10-10T101530", "receipt", payee="Petro-Canada", amount="62.50", gst="g")], cfg_=cfg)
    assert "GST-Receivable" not in res.new_text and 'gst: "g"' in res.new_text and "62.50 CAD" in res.new_text


def test_receipt_edge_cases(run):
    res = run([memo("2026-10-09T101530", "receipt", payee="Mystery Shop", amount="12.00")])
    assert "Expenses:Uncategorized" in res.new_text and "no rule matched" in res.new_text
    res = run([memo("2026-10-10T101530", "receipt", payee="Shell", amount="-5")])
    assert "not a positive number" in res.new_text
    assert bean_errors(run.staging.read_text(encoding="utf-8")) == []


def test_photo_links_within_window_and_vision_total_wins(run):
    res = run(
        [memo("2026-10-09T101530", "receipt", payee="Petro-Canada", amount="62.50", category_hint="fuel")],
        photos=[("2026-10-09T102000.jpg", b"jpegbytes")],
        sidecars={"2026-10-09T102000.extract.json": {"amount": "63.50", "payee": "Petro-Canada"}},
    )
    assert "receipt: \"2026-10-09T102000.jpg\"" in res.new_text
    assert "no receipt image" not in res.new_text
    assert "differs from receipt photo total 63.50" in res.new_text
    assert "-63.50 CAD" in res.new_text
    assert res.entries == 1  # the photo's sidecar is not mistaken for a memo


def test_photo_outside_window_not_linked(run):
    res = run([memo("2026-10-09T101530", "receipt", payee="Petro-Canada", amount="62.50")],
              photos=[("2026-10-09T120000.jpg", b"x")])
    assert "no receipt image" in res.new_text


def test_incremental_run_supersedes_stale_assertion(run):
    run([START("2026-10-09T080000", 1000), END("2026-10-09T090000", 1040)])
    assert "\n2026-10-10 balance" in run.staging.read_text(encoding="utf-8")
    run([START("2026-10-09T150000", 1040), END("2026-10-09T160000", 1070)])
    text = run.staging.read_text(encoding="utf-8")
    assert "; 2026-10-10 balance Assets:Vehicle:Civic:Odometer  1040 KM" in text
    assert "\n2026-10-10 balance Assets:Vehicle:Civic:Odometer  1070 KM" in text
    assert bean_errors(text) == []


def test_normalize_is_forgiving_but_never_guesses():
    x = normalize({"type": "trip_start", "odometer": "48,210", "amount": "$62.50", "payment": "Amex", "gst": "G"})
    assert x["odometer"] == 48210 and x["amount"] == "62.50" and x["payment"] is None and x["gst"] == "g"
    assert normalize({"type": "bogus", "odometer": "lots"})["type"] == "note"
    assert normalize({"odometer": "lots"})["odometer"] is None


def test_logbook_totals(run, cfg, tmp_path):
    run(sample_memos())
    ledger = tmp_path / "main.bean"
    text = run.staging.read_text(encoding="utf-8")
    accounts = sorted(set(re.findall(r"^\s+([A-Z][A-Za-z0-9-]*(?::[A-Za-z0-9-]+)+)\s+-?[\d.]+ ", text, re.M))
                      | set(re.findall(r"balance (\S+)", text)))
    ledger.write_text("2026-01-01 commodity KM\n2026-01-01 commodity CAD\n"
                      + "".join(f"2026-01-01 open {a}\n" for a in accounts) + f"\ninclude \"staging.bean\"\n", encoding="utf-8")
    lb = logbook.build(ledger, cfg, 2026)
    assert lb["ledger_errors"] == []
    assert lb["business_km"] == 127 and lb["personal_km"] == 763
    assert [r["destination"] for r in lb["rows"]] == ["Sherwood Park site", "Leduc office"]
    assert lb["business_use_pct"] == Decimal("14.3")
    assert logbook.to_csv(lb).splitlines()[0].startswith("date,vehicle")
