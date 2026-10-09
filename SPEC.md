# roadbean — spec

> Say it in the car, get it in the ledger.
> Hacktoberfest 2026 Open-Source AI Challenge, Week 1 ("Touch Grass"). Deadline **Sun Oct 11, 11:59 PM PDT** (Mon 00:59 MDT).

## 1. Summary

roadbean turns short voice memos recorded on a phone into Beancount entries. A memo can mark the **start or end of a business drive** (with the odometer reading) or describe a **receipt** (fuel, parking, a coffee with a client). An open-weight model, running locally on the phone or on a laptop, turns each memo into structured JSON. Plain Python then pairs trips, checks the numbers, and writes pending (`!`) entries to a staging file that the main ledger includes.

The point is that the phone is barely touched: one tap (or a voice command) to record, then pocket it. All interpretation happens later, offline, on hardware the user owns.

Prior art: [receipt2bean](https://github.com/minchinweb/hacktoberfest-2026-0). Reuse its *ideas*: the model reads and code checks, entries are pending, runs are idempotent by file hash, and categories come from rules rather than the model. **Do not copy its code.** The challenge requires a new project built in the window, so write fresh code in a new repo (`hacktoberfest-2026-1`).

## 2. Goals / non-goals

**Goals**
- Capture with no screen time: a one-tap Termux:Widget shortcut to record, and the same again to stop.
- Local inference only. Nothing is sent to a hosted API.
- A CRA-style kilometre logbook: date, start/end odometer, km, destination, and purpose for every business trip.
- Business and personal km for the year, derived automatically (gaps between trips count as personal driving).
- Receipt memos become pending expense entries, linked to a photo when one exists.
- An optional per-km allowance entry, for when the corporation reimburses a shareholder-employee for using their personal vehicle.
- Deterministic and testable without a model (`--from-json`).

**Non-goals (this week)**
- No Android GUI app, no continuous GPS tracking, and no cloud sync. Use the existing git/Termux sync to move files.
- No bank-transaction matching.
- No tax advice. The tool records facts; the user and their accountant decide treatment.

## 3. Architecture

```
PHONE (Pixel 7, Termux)                         PHONE or LAPTOP
-----------------------                         ----------------------------------------------
Termux:Widget "rb-memo"  --> inbox/             roadbean process inbox/
  termux-microphone-record    2026-10-09T081502.m4a    1. transcribe   (whisper.cpp | Gemma audio)
  termux-location (opt.)      2026-10-09T081502.json   2. extract      (LLM -> JSON, schema-constrained)
camera (optional)             IMG_3012.jpg             3. validate     (Python)
                                                       4. pair trips / link photos (Python)
       git sync (existing)  ------------------->       5. emit         staging.bean  (! entries)
                                                       6. report       logbook.csv
```

Steps 1–2 are the only parts that use a model. Steps 3–6 are pure Python with no network access.

### 3.1 Can the model run on the phone?

Yes, with caveats, so support two backends behind one interface:

| Backend | Transcribe | Extract | Where | Status |
|---|---|---|---|---|
| `ollama` (default) | whisper.cpp, or Gemma 4 audio if this Ollama build supports it | `gemma4:e4b` via Ollama, `format=<json schema>` | laptop | **must have** |
| `llamacpp` | whisper.cpp (`base.en` or `small.en`) built in Termux | Gemma 4 **E2B** GGUF (Q4) via llama.cpp with a JSON-schema/GBNF grammar | phone (Termux) | **stretch**: benchmark and report latency on the Pixel 7 |

Notes for the implementer:
- Gemma 4 E2B and E4B are the edge-sized variants and take audio input natively. Audio input through Ollama and llama.cpp may still be incomplete, so **probe it at startup** (`roadbean doctor`) and fall back to whisper.cpp for speech-to-text. Either way, extraction runs on Gemma.
- Transcripts are short (under 30 s of audio, under 100 words), so a 2B model doing extraction is realistic on a phone. Receipt *photos* need a vision pass, which defaults to the laptop.
- Pin model names in config. Never hard-code them.

## 4. Capture (phone)

Termux:Widget scripts go in `~/.shortcuts/` (the same place as the existing obsidian-sync script).

- `rb-memo`: toggles recording. On the first tap, run `termux-microphone-record -f inbox/<ISO-timestamp>.m4a -l 60` and, if location is enabled, write `<timestamp>.json` with `termux-location -p network -r once` (best effort, with a timeout of a few seconds). On the second tap, stop. Give a short vibration on start and stop (`termux-vibrate`) so the user doesn't need to look at the screen.
- `rb-sync`: commits and pushes `inbox/` (or reuses the existing sync script).
- Photos are optional. Either save them to `inbox/` from the camera, or add an `rb-photo` shortcut using `termux-camera-photo`.
- The README says to record while parked or hands-free, and suggests an Assistant routine as the hands-free option.

The filename timestamp is the authoritative event time. The model never supplies the date.

### Example memos (these become test fixtures)
- "Start trip. Odometer four eight two one zero. Going to the Sherwood Park site for the meter install."
- "End trip, forty-eight two fifty-two."
- "Receipt, Petro-Canada, sixty-two fifty, fuel, business."
- "Parking, eight dollars, cash, client meeting downtown."
- "Round trip to the Leduc office and back, about eighty-five k, odometer now forty-nine one hundred." *(single-memo trip)*

## 5. Extraction contract

The model returns **one JSON object per memo**, constrained by schema. Normalizing numbers is the model's job (it turns "four eight two one zero" into `48210`). Checking them is the code's job.

```json
{
  "type": "trip_start | trip_end | trip | receipt | note",
  "odometer": 48210,            // int|null, km
  "distance_km": null,          // number|null, only if spoken
  "destination": "Sherwood Park site",
  "purpose": "meter install",
  "business": true,             // bool|null (null = not stated)
  "vehicle": null,              // string|null, matched against config
  "payee": "Petro-Canada",
  "amount": "62.50",            // string decimal|null
  "currency": "CAD",
  "payment": "visa | cash | debit | null",
  "category_hint": "fuel",
  "gst": "g | z | e | null",
  "confidence": "high | medium | low",
  "transcript": "..."           // filled in by code, not the model
}
```

The prompt is a versioned file (`prompts/extract_v1.md`) with 6–8 few-shot examples taken from §4.

## 6. Validation and pairing (pure Python)

- **Pairing.** Sort events by timestamp per vehicle. A `trip_start` pairs with the next `trip_end`. A start with no end is held back rather than emitted, with a warning; after `stale_after_days` it is emitted as a flagged note. An end with no start is flagged. A single-memo `trip` needs either `distance_km` or an odometer reading plus the previous reading.
- **Odometer sanity.** The end reading must be greater than the start. The trip length must be at most `max_trip_km`. The start reading must be at least the previous end reading. If the start is lower than the previous end, the reading is probably misheard: flag it and do not "fix" it.
- **Personal km.** When the next start is higher than the previous end, the difference is personal driving. Emit it as a personal-km entry dated at the next start.
- **Spoken vs odometer distance.** If both are given and differ by more than `distance_tolerance` (default 10%), flag it.
- **Receipts.** The amount must be a positive decimal. A receipt memo links to a photo within `photo_link_window_min` (default 10) of its timestamp. If a photo exists and the vision backend is enabled, the photo's total wins and a mismatch is flagged. If there is no photo, add `; REVIEW: no receipt image`. The payee maps to an account via `rules.toml`; unknown payees go to `Expenses:Uncategorized`.
- **Never silently correct anything.** Every problem becomes a `; REVIEW:` comment and the entry stays `!`.
- **Idempotency.** Each entry stores the `memo-sha` of its audio file (and `receipt-sha` for photos). Re-runs skip anything already in staging.

## 7. Beancount output

Kilometres are tracked as their own commodity so that Fava can query them and odometer readings can be checked with balance assertions.

```beancount
2026-01-01 commodity KM
2026-01-01 open Assets:Vehicle:Civic:Odometer   KM
2026-01-01 open Income:Mileage:Business          KM
2026-01-01 open Income:Mileage:Personal          KM
```

Business trip (paired start and end):
```beancount
2026-10-09 ! "Mileage" "Sherwood Park site — meter install"
  memo-sha: "a1b2c3d4e5f6"
  odometer-start: 48210
  odometer-end: 48252
  destination: "Sherwood Park site"
  transcript: "Start trip. Odometer four eight two one zero…"
  Assets:Vehicle:Civic:Odometer     42 KM
  Income:Mileage:Business          -42 KM
2026-10-10 balance Assets:Vehicle:Civic:Odometer  48252 KM
```
(The balance assertion is dated the day after the trip, because Beancount checks balances at the start of the day.)

Optional allowance (`[allowance] enabled = true`). This applies only to an employee or shareholder-employee driving a personal vehicle. The code tracks cumulative business km for the calendar year so it can apply the tier split correctly across the threshold:
```beancount
2026-10-09 ! "Mileage allowance" "42 km @ 0.73"
  Expenses:Vehicle:Allowance          30.66 CAD
  Liabilities:Due-To-Shareholder     -30.66 CAD
```

Receipt memo:
```beancount
2026-10-09 ! "Petro-Canada" "Fuel"
  memo-sha: "…"
  gst: "g"
  ; REVIEW: no receipt image
  Expenses:Vehicle:Fuel       59.52 CAD
  Assets:GST-Receivable        2.98 CAD
  Liabilities:Visa           -62.50 CAD
```
GST is backed out of the total only when `gst = "g"` and `[gst] split = true`. Otherwise the code emits the gross amount and the `gst:` metadata, so a future GST plugin can handle it.

## 8. CLI

```
roadbean doctor                         # check models, whisper.cpp, audio support; print backend plan
roadbean process inbox/ --config roadbean.toml --out staging.bean
         [--backend ollama|llamacpp] [--dry-run] [--from-json] [--since 2026-10-01]
roadbean logbook --year 2026 --ledger main.bean --csv logbook.csv
                                        # CRA-style log + totals: business km, personal km, business-use %
```
Each memo writes `<name>.transcript.txt` and `<name>.extract.json` next to it. These are the audit trail and the `--from-json` input.

## 9. Config (`roadbean.toml`)

```toml
[models]
backend = "ollama"
extract = "gemma4:e4b"
vision  = "gemma4:e4b"          # or qwen3-vl:8b
stt     = "whisper.cpp:base.en" # used when native audio is unavailable

[vehicles.civic]
default = true
odometer_account = "Assets:Vehicle:Civic:Odometer"

[mileage]
business_account = "Income:Mileage:Business"
personal_account = "Income:Mileage:Personal"
max_trip_km = 1500
distance_tolerance = 0.10
stale_after_days = 3

[allowance]
enabled = false
rate_first = "0.73"      # 2026 provincial rate, first 5,000 km — verify on canada.ca
rate_after = "0.67"
threshold_km = 5000
expense_account = "Expenses:Vehicle:Allowance"
payable_account = "Liabilities:Due-To-Shareholder"

[gst]
split = true
rate = "0.05"
account = "Assets:GST-Receivable"

[receipts]
photo_link_window_min = 10
payment_accounts = { visa = "Liabilities:Visa", cash = "Assets:Cash", debit = "Assets:BMO:Chequing" }
```
Payee → account rules live in `rules.toml` (exact or regex matches).

## 10. Repo layout

```
roadbean/            cli.py  backends/{ollama,llamacpp}.py  stt.py  extract.py
                     pair.py  validate.py  emit.py  logbook.py  config.py
prompts/extract_v1.md
termux/shortcuts/    rb-memo  rb-sync      (+ install.sh that copies to ~/.shortcuts)
samples/audio/       synthetic memos generated with Piper TTS (script included)
samples/expected/    *.extract.json and expected staging.bean
tests/               pytest — pairing, tiers, odometer gaps, GST split, idempotency, emit snapshots
README.md  pyproject.toml  roadbean.example.toml  rules.example.toml  LICENSE (MIT)
```
Python 3.11+, with `beancount` v3 for parsing the ledger in `logbook` and a `bean-check` run on the output in tests. Use `Decimal` for all money.

## 11. Acceptance criteria

1. `pytest` passes with no model installed. Fixtures cover every §4 memo, a misheard odometer, a start without an end, a personal-km gap, and crossing the 5,000 km tier.
2. `roadbean process samples/audio --dry-run` on a laptop with Ollama produces output equal to `samples/expected/staging.bean`, ignoring the transcript and confidence fields.
3. `bean-check` passes on a test ledger that includes the generated staging file, including the odometer balance assertions.
4. Re-running `process` adds nothing.
5. `roadbean doctor` correctly reports whether native audio works and which fallback it will use.
6. Stretch: the `llamacpp` backend runs the full pipeline in Termux on the Pixel 7. Record wall-clock time per memo in the README.

## 12. Milestones

| When | Deliverable |
|---|---|
| Thu night | Repo, config loader, extraction schema, Piper sample memos, `doctor` |
| Fri | Deterministic core (pair, validate, emit, logbook) with tests; `--from-json` working |
| Fri late | Ollama backend plus whisper.cpp fallback; acceptance criteria 1–5 |
| Sat | Termux shortcuts; **real drive with real memos**; fix what breaks; phone backend attempt |
| Sun | README (setup, honest limitations, accuracy on real memos), demo recording, DEV post with tag `#hf26challenge` |

## 13. Write-up hooks (for the DEV post)

- Theme: the screen-time goal is zero. Logging happens through your voice and a vibration, and the tool is useful precisely because you're out driving rather than sitting at a desk. Take it on a real drive this weekend (a trailhead counts) and report the results.
- Why open: it runs offline in the car or on the phone; location and client names never leave the device; models can be swapped and benchmarked against each other (Gemma 4 E2B on the phone vs E4B on the laptop vs Qwen3-VL); and it costs nothing to run.
- Partner category: **Best Use of Gemma** (Gemma on-device, audio).
- Show the process: save the Claude Code session with DevRelay and link it.

## 14. Open questions (owner to answer)

- Whose vehicle is it: a personal one driven for the corporation (so the allowance applies), or one owned by the corporation (actual costs, no allowance)? This decides the `[allowance]` default.
- What are the vehicle names and the real account names for the ledger?
- Does the laptop already have Ollama ≥ 0.22 and enough RAM for `gemma4:e4b`?
