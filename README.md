# roadbean

> Say it in the car, get it in the ledger.

roadbean turns short voice memos recorded on a phone into [Beancount](https://beancount.github.io/) entries. A memo can mark the **start or end of a business drive** (with the odometer reading) or describe a **receipt** (fuel, parking, a coffee with a client). Local open-weight models turn each memo into structured JSON. Plain Python pairs trips, checks the numbers, and writes pending (`!`) entries to a staging file that your main ledger includes.

The phone is barely touched: one tap to record, one tap to stop, a vibration to confirm. All interpretation happens later, offline, on hardware you own. Nothing is sent to a hosted API.

Built for Hacktoberfest 2026 (Open-Source AI Challenge, week 1). Design: [SPEC.md](SPEC.md).

```
PHONE (Termux)                                  PHONE or LAPTOP
Termux:Widget "rb-memo" -> inbox/*.m4a          1. transcribe   Whistle | whisper.cpp | Gemma audio
  (+ optional location, receipt photo)          2. extract      Gemma 4 (Ollama or llama.cpp), JSON-schema constrained
        git sync (rb-sync) ------------------>  3. validate + pair trips + link photos   (pure Python)
                                                4. emit staging.bean (! entries)         (pure Python)
                                                5. logbook.csv + yearly totals
```

Steps 1–2 are the only parts that use a model. Everything after is deterministic, tested, and never silently corrects a number: every problem becomes a `; REVIEW:` comment and the entry stays pending.

## Output

A paired business trip, with the odometer tracked as its own `KM` commodity so Fava can query it and balance assertions can check your readings:

```beancount
2026-10-09 ! "Mileage" "Sherwood Park site — meter install"
  memo-sha: "3021b88daa2d"
  memo-sha-end: "0a5790c88d6c"
  vehicle: "civic"
  odometer-start: 48210
  odometer-end: 48252
  destination: "Sherwood Park site"
  purpose: "meter install"
  Assets:Vehicle:Civic:Odometer  42 KM
  Income:Mileage:Business        -42 KM

2026-10-10 balance Assets:Vehicle:Civic:Odometer  48252 KM
```

Driving between trips is derived automatically: when the next start reading is higher than the last end reading, the difference becomes a personal-km entry. See [`samples/expected/staging.bean`](samples/expected/staging.bean) for a full run (receipts with GST split, an optional per-km allowance entry, a single-memo round trip).

## Setup

```
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
cp roadbean.example.toml roadbean.toml              # vehicles, accounts, models
cp rules.example.toml rules.toml                    # payee/category -> account
roadbean doctor --config roadbean.toml              # what works on this machine, and the plan
```

You need **ffmpeg** (phone audio is converted to 16 kHz mono) and one speech-to-text engine:

| `[models].stt` | Install | Notes |
|---|---|---|
| `whistle` | `pip install cactus-needle`, then `needle download whistle` and move `whistle.cact` to `~/.cache/whistle/` | [Cactus Whistle](https://cactuscompute.com/blog/whistle): 16.9 MB, CPU-only, prebuilt for Android. roadbean passes your vehicle names and payees as recognition keywords, and sets `NEEDLE_TELEMETRY=0`. |
| `whisper.cpp:base.en` | whisper.cpp's `whisper-cli` plus `ggml-base.en.bin` in `[whisper].model_dir` | The established fallback. |
| `native` | An Ollama build where `doctor` reports native audio on your Gemma model | Experimental; uses the OpenAI-compatible `input_audio` part. |

And one extraction backend:

- **`ollama`** (laptop, default): `ollama pull gemma4:e4b`. Extraction uses Ollama's `format=<json schema>`.
- **`llamacpp`** (phone, Termux, stretch): run `llama-server -m <gemma-4-E2B GGUF> --port 8080`; roadbean sends the schema as a grammar. Set `extract` to your E2B model name.

Model names are pinned in config, never hard-coded.

## Use

```
roadbean process inbox/ --config roadbean.toml --rules rules.toml --out staging.bean
roadbean process inbox/ --dry-run                # print what would be added, write nothing
roadbean process inbox/ --from-json              # no model: use existing .extract.json files
roadbean process inbox/ --vision                 # also read receipt photos (laptop; ollama)
roadbean logbook --year 2026 --ledger main.bean --csv logbook.csv
```

Add `include "staging.bean"` to your ledger. Each memo leaves `<name>.transcript.txt` and `<name>.extract.json` beside it as an audit trail; these are also the `--from-json` input, and an existing extract is reused rather than re-run (`--reextract` to redo).

`logbook` reads the ledger and prints a CRA-style log (date, odometer start/end, km, destination, purpose, status) plus business km, personal km, and business-use % for the year.

### Behaviour worth knowing

- The **filename timestamp is the event time**; the model never supplies a date.
- A `trip_start` with no end is **held back** (warning) and flagged after `stale_after_days`. An end with no start is flagged.
- Odometer checks: end > start, trip ≤ `max_trip_km`, start ≥ previous end (if lower, the reading is probably misheard: flagged, not "fixed", and its balance assertion is left commented out). Spoken vs odometer distance is compared within `distance_tolerance`.
- Balance assertions are dated the day after a trip. If another trip lands the same day, the earlier assertion is dropped (or commented out in the staging file on a later run) so `bean-check` keeps passing.
- Re-running adds nothing: each entry records the SHA of its audio (`memo-sha`) and photo (`receipt-sha`).
- GST is backed out of the total only when `gst = "g"` (from the memo or the matching rule) and `[gst].split = true`.
- The first trip ever logged for a vehicle emits an `Odometer opening` entry against `Equity:Opening-Balances`; delete it if your ledger already has one.
- The allowance (`[allowance]`, for a shareholder-employee using a personal vehicle) tracks cumulative business km per calendar year across runs and splits the rate at the threshold. Rates in the example config are the spec's 2026 values: verify them. roadbean records facts; it is not tax advice.

## Phone capture (Termux)

```
pkg install termux-api git ffmpeg      # plus the Termux:API and Termux:Widget apps
bash termux/install.sh                  # copies rb-memo, rb-sync, rb-photo to ~/.shortcuts
```

Add the `rb-memo` widget to your home screen. First tap starts recording (short buzz), second tap stops (longer buzz); memos are capped at 60 s. Location is best-effort (`RB_LOCATION=0` to disable). `rb-sync` commits and pushes `inbox/`; `rb-photo` snaps a receipt photo named by time so it links to the nearest memo (within `photo_link_window_min`). Record while parked or hands-free.

## Tests

```
pytest
```

24 tests, no model required: pairing, misheard odometer, missing ends, personal-km gaps, allowance tier crossing, GST split, photo linking, idempotency, incremental runs, snapshot against `samples/expected/`, `bean-check`-equivalent loading of the output (including balance assertions), the logbook totals, and the backends against a fake local server.

## Status and honest limitations

Verified here: the whole deterministic core and its tests; Whistle transcribing synthetic memos on a laptop CPU (0.2–1.3 s each); the backends' request/response handling against a fake server.

**Not yet verified**, because no Ollama, Gemma weights or Pixel were available when this was built:
- Live Gemma extraction through Ollama (acceptance criterion 2) and the quality of `prompts/extract_v1.md` on real transcripts.
- Whether any given Ollama or llama.cpp build accepts native audio (`doctor` probes the model's capabilities; the `native` path is best-effort).
- The `llamacpp` backend in Termux on the Pixel 7, and per-memo timings there.
- The Termux shortcuts on a real device, and a real drive with real memos. Accuracy on real memos is to be added here after that drive.

Early observation: with a robotic Windows SAPI voice, Whistle misheard digits and words ("48210" became "4A210", "Leduc" became "Laduk"). That is what the odometer and pairing checks are for, and it argues for speaking odometer readings clearly. The synthetic samples in `samples/audio/` come from `samples/make_audio.py` (Piper or Windows SAPI); `samples/memos.json` holds what each one says.

## Layout

```
roadbean/        cli, config, memo discovery, stt, extract (schema + normalise), pair, validate, emit, logbook, pipeline, backends/
prompts/         extract_v1.md   (versioned prompt, 7 few-shot examples)
termux/          shortcuts/{rb-memo,rb-sync,rb-photo}, install.sh
samples/         memos.json, make_audio.py, expected/ (extracts + staging.bean)
tests/
```

MIT licensed.
