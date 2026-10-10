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
pip install -e ".[dev]"                             # laptop: also installs beancount (logbook) and pytest
cp roadbean.example.toml roadbean.toml              # vehicles, accounts, models
cp rules.example.toml rules.toml                    # payee/category -> account
roadbean doctor --config roadbean.toml              # what works on this machine, and the plan
```

You need **ffmpeg** (phone audio is converted to 16 kHz mono) and one speech-to-text engine:

| `[models].stt` | Install | Notes |
|---|---|---|
| `native` | An Ollama build whose model reports the `audio` capability (`doctor` checks); tested with `gemma4:e4b` | Best digits in testing; laptop-sized. Uses the OpenAI-compatible `input_audio` part. |
| `whistle` | `pip install cactus-needle`, then `needle download whistle` and move `whistle.cact` to `~/.cache/whistle/` | [Cactus Whistle](https://cactuscompute.com/blog/whistle): 16.9 MB, CPU-only, prebuilt for Android. roadbean passes your vehicle names and payees as recognition keywords, and sets `NEEDLE_TELEMETRY=0`. |
| `whisper.cpp:base.en` | whisper.cpp's `whisper-cli` plus `ggml-base.en.bin` in `[whisper].model_dir` | The established fallback. |

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

## Phone capture (Termux) and syncing to your laptop

Memos travel phone -> laptop through a **private** git repo (the inbox). The memos hold your voice, client names and optionally your location, so keep that repo private.

**1. Make the inbox repo (on the laptop or GitHub), private and empty.**

```
gh repo create roadbean-inbox --private          # or any private remote you can push to from the phone
```

**2. Set up Termux (on the phone).** Install Termux, Termux:API and Termux:Widget from F-Droid (use the same source for all three).

```
pkg install git termux-api ffmpeg openssh
termux-setup-storage                             # optional
git clone https://github.com/minchinweb/hacktoberfest-2026-1 ~/roadbean-src
cd ~/roadbean-src
bash termux/install.sh                           # puts rb-memo, rb-sync, rb-photo in ~/.shortcuts/tasks
```

The shortcuts go in `~/.shortcuts/tasks/` so a widget tap runs in the background. (Scripts directly in `~/.shortcuts/` open a Termux terminal that stays on screen.) Run `termux-microphone-record -d` once by hand and allow the microphone prompt; allow location too if you want it.

**3. Let the phone push to the inbox repo.** Use an SSH key, so `rb-sync` never prompts:

```
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub                        # GitHub: repo > Settings > Deploy keys > Add, tick "Allow write access"
bash termux/init-repo.sh git@github.com:YOU/roadbean-inbox.git
```

`init-repo.sh` turns `~/roadbean` into a git repo with that remote and a `.gitignore` that keeps the generated `.transcript.txt` / `.extract.json` files out of sync (they're made on the laptop, so pulls never conflict).

**4. Add the widgets.** Long-press the home screen, add a Termux:Widget, and pick `rb-memo` (and `rb-sync`, `rb-photo`). First tap starts recording (short buzz), second tap stops (longer buzz); memos are capped at 60 s. Location is best-effort (`RB_LOCATION=0` to disable). `rb-sync` commits and pushes `inbox/` and toasts the result; `rb-photo` snaps a receipt photo named by time so it links to the nearest memo (within `photo_link_window_min`). Record while parked or hands-free.

**5. On the laptop**, clone the inbox once and then, per batch:

```
git clone git@github.com:YOU/roadbean-inbox.git ~/roadbean-inbox      # once
git -C ~/roadbean-inbox pull
roadbean process ~/roadbean-inbox/inbox --config roadbean.toml --rules rules.toml --out staging.bean
```

To remove everything from the phone: `bash termux/uninstall.sh` (keeps your memos; `--purge` deletes `~/roadbean` after a prompt).

To run `roadbean` itself on the phone (the llama.cpp stretch goal), `pip install -e .` there installs the core only. Don't add `[dev]` or `[ledger]`: `beancount` has no Android wheel and its source build fails without bison. Run `roadbean logbook` on the laptop.

## Tests

```
pytest
```

26 tests, no model required: pairing, misheard odometer, missing ends, personal-km gaps, allowance tier crossing, GST split, photo linking, idempotency, incremental runs, snapshot against `samples/expected/`, `bean-check`-equivalent loading of the output (including balance assertions), the logbook totals, and the backends against a fake local server.

## Status and honest limitations

**Measured on the laptop** (Ollama, `gemma4:e4b` Q4_K_M, 7.5B reported size; five synthetic SAPI-voice memos from `samples/`):

| Speech engine | Digits right | Whole run (5 memos, incl. model load) | Result vs `samples/expected/staging.bean` |
|---|---|---|---|
| Gemma native audio (`stt = "native"`) | 3/3 odometer readings | ~26 s | identical except free text (`site` heard as `side`) |
| Whistle (`stt = "whistle"`) | 0/3 (`4A210`, `48–52`, ...) | ~20 s | wrong 642 km trip, flagged only by a low-model-confidence note |

- Whistle transcribed each memo in 0.2–1.3 s on CPU, but mangled digits on the robotic test voice. Gemma's native audio did not. This is five memos in one synthetic voice, not a benchmark; real voices in a real car will differ.
- Findings that shaped the code: Gemma 4 through Ollama must run with `think: false` (with thinking on, schema-constrained output came back empty or wrong, and was about 3x slower); and a garbled transcript can produce a *plausible* wrong trip that passes the range checks. So any entry built from a memo the model rated below `high` confidence gets a `; REVIEW:` comment and its balance assertion is commented out.
- `doctor` correctly reports native audio support and the STT plan.

**Still not verified:** the `llamacpp` backend with Gemma E2B on the Pixel 7 (and per-memo timings there), the Termux shortcuts on a real device, and a real drive with real memos. Accuracy on real memos is to be added here after that drive.

The synthetic samples in `samples/audio/` come from `samples/make_audio.py` (Piper or Windows SAPI); `samples/memos.json` holds what each one says.

## Layout

```
roadbean/        cli, config, memo discovery, stt, extract (schema + normalise), pair, validate, emit, logbook, pipeline, backends/
prompts/         extract_v1.md   (versioned prompt, 7 few-shot examples)
termux/          shortcuts/{rb-memo,rb-sync,rb-photo}, install.sh
samples/         memos.json, make_audio.py, expected/ (extracts + staging.bean)
tests/
```

MIT licensed.
