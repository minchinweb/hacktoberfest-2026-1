---
title: "roadbean: say it in the car, get it in the ledger"
published: false
description: "Voice memos from my phone become pending Beancount entries. A local model reads; plain Python checks."
tags: hf26challenge, gemma, python, opensource
cover_image:
---

<!-- Edit freely. TODO markers (search "TODO") are the bits only you can fill in. -->

*This is my submission for the [Hacktoberfest 2026 Open-Source AI Challenge](https://dev.to/challenges), Week 1: Touch Grass. It is also entered for **Best Use of Gemma**.*

## What I built

**roadbean** turns voice memos recorded on my phone, while I'm in the car, into entries in my [Beancount](https://beancount.github.io/) ledger. I say "trip start, odometer 1234, heading to the library", and later "trip end, 1254", and say "Safeway, 42 dollars 28, GST 7 cents" when I buy groceries. I get a mileage log I can hand to the CRA (i.e the tax man) and receipts waiting for review.

```
phone: voice memo / receipt photo
  -> git inbox (private repo, synced to the laptop)
  -> local model: speech to text, then text to JSON
  -> plain Python: pairs trips, checks the arithmetic, writes entries
  -> staging.bean: pending (!) entries you review and promote
```

The design rule is **the model reads, the code checks**. The model is the only non-deterministic step. Everything after it (pairing a start with an end, comparing odometer difference to the stated distance, splitting GST, applying the allowance tiers) is ordinary Python with tests. Nothing is silently corrected: if something doesn't add up, the entry is written with a `; REVIEW:` line and stays pending (`!`) until a human looks.

## Demo

This is the laptop side. On the phone, three Termux:Widget buttons run a script that records a memo, takes a photo (e.g. a receipt) or pushes the inbox to a private git repo that syncs to the laptop. The recording below is `roadbean process` run against real memos from my phone.

![roadbean processing real phone memos](https://raw.githubusercontent.com/minchinweb/hacktoberfest-2026-1/main/docs/roadbean-demo.gif)

<!-- TODO: the GIF is ~3.7 minutes and 2.5 MB. Consider trimming to the `roadbean process` run and the staging.bean result. It must be committed and pushed for the URL above to work. -->

Look at what the demo does *not* do. My first real memo was transcribed as "uh memo". The model couldn't make a trip or receipt of it, so the entry says `not a trip or receipt; file by hand` instead of inventing something. The receipt memo came out as "purchase staple safeway for 42 28 and gst of 7 7", and the entry was written with the amounts it could trust, `no rule matched payee; left uncategorized`, and a review flag. The run also flagged a 305,023 km "trip" as exceeding `max_trip_km`, because a stale open trip from my earlier testing got paired with the new start. It was caught by a validation rule, not by me. Real input is messy; the point is that every miss lands as a visible review line rather than a wrong number in the books.

## How it works

- **Speech to text.** Gemma's native audio input through Ollama (`gemma4:e4b`), after ffmpeg converts the phone's `.m4a` to 16 kHz mono WAV. Whisper.cpp and Cactus's Whistle are drop-in alternatives (`[models].stt`).
- **Extraction.** The transcript goes to Gemma with a JSON schema (`format=<schema>`, `think: false`). Every field is required, so the output is either complete or rejected. Seven few-shot examples live in `prompts/extract_v1.md`.
- **Pairing and validation** (pure Python, no model):
  - start and end memos for the same vehicle become one trip; odometer difference vs. stated distance is checked;
  - a balance assertion on the odometer is dated the day after the trip, and is dropped (with a review note) if the model's confidence was low;
  - GST is split from the total, and the CRA allowance tiers are applied to business km;
  - a start with no end memo is written as a commented-out `; OPEN TRIP:` block and replaced in place when the end memo arrives. If I close it by hand, roadbean notices and doesn't recreate it.
- **Idempotent.** Each memo's SHA is stored in its entry, so re-running `process` never duplicates anything.
- **Logbook.** `roadbean logbook` reads the real ledger through the Beancount loader and writes a CRA-style CSV with totals.

Every entry carries `source: "roadbean 0.1.0"`, so I can tell later which version wrote it.

### What a pending entry looks like

```beancount
2026-10-10 ! "Safeway" "Null"
  source: "roadbean 0.1.0"
  memo-sha: "cc60a49a8f7b"
  receipt: "2026-10-10T121405.jpg"
  transcript: "purchase staple safeway for 42 28 and gst of 7 7"
  ; REVIEW: no rule matched payee; left uncategorized
  Expenses:Uncategorized      40.27 CAD
  Assets:GST-Receivable        2.01 CAD
  Liabilities:Visa           -42.28 CAD
```

## Why Gemma

I wanted everything to run on hardware I own. The same family covers both ends:

- **On the laptop:** `gemma4:e4b` via Ollama does speech-to-text *and* extraction. One model, no separate STT stack.
- **On the phone:** the plan was a smaller Gemma (E2B) through llama.cpp in Termux, so a memo could be processed without the laptop. I didn't get speech recognition working on the phone in time, so the phone only records, photographs and syncs; all the model work happens on the laptop.

### Native audio vs. a dedicated STT model

I tried Whistle (Cactus's tiny STT model) against Gemma's native audio on five synthetic memos (Windows SAPI voices, so a best case for both):

| STT | Odometer read correctly (3 trips) | Failure mode |
|---|---|---|
| Gemma native audio | 3 / 3 | none on this set |
| Whistle | 0 / 3 | produced a plausible but wrong 642 km trip |

Whistle's wrong trip was only caught by the low-confidence flag. That result is why native audio is the default. Five synthetic recordings is a small, friendly sample, not a benchmark; real car noise is the next test. Real voice samples proved even harder to process (although I don't have a large enough body to provide useful confidence numbers like the above table).

I also considered EmbeddingGemma 2 for matching payees to rules. I decided against it: payees are a few dozen strings, normalized matching plus explicit rules is predictable, and an embedding match would add a non-deterministic step exactly where I want determinism.

## Taking it outside (Touch Grass)

- load the phone side up at home. Add Termux shortcuts to the home screen.
- step into the car ad the begining of the trip. Tap the "memo" shortcut and read off "trip start. Odometer xxx km"
- drive around town. Errands need doing. Not a lot of grass as it's snowing, but we still get fresh air.
- after completing the purchase, tap the "memo" shortcut again and record "Safeway purchase. 42.28 total, 7 cents GST".
- tap on the "photo" shortcut to take a picture of the receipt. There is no photo preview, so we're going for best guess, but the idea was to keep phone time as low as possible.
- get home, tap the "memo" shortcut and read off "trip end. Odometer xxx km".
- tap the "sync" shortcut
- the data is then processed on the laptop at home, at later time

## Honest limitations

- Tested end to end on the laptop with synthetic and a few real memos. The Termux shortcuts are confirmed to work on-phone, but I didnt' get on-phone voice recognition working
- Speech recognition errors become review lines, not wrong data, but they still need a human. Numbers read aloud ("1 2 3 4") are the weak spot.
- Single user, single currency (CAD default), personal vehicle with the CRA allowance enabled; the account names are the Beancount ones from my own setup.
- almost no feedback on the phone. This was a "Feature" from the design breif, but it's hard as a user to feel confident that the process hasn't silently broken.
- still requires a laptop to process
- is set up to require syncing through git. Github allows private repos, but they still have access to your data (and trip and financial data are fairly dear), and self-hosting is an option, but involved to set up for only this project

## Try it

```bash
pip install -e .[ledger]
roadbean init ~/roadbean        # creates config, rules, inbox
roadbean doctor ~/roadbean      # checks Ollama, ffmpeg, the model
roadbean process ~/roadbean     # inbox -> staging.bean
roadbean logbook ~/roadbean     # CRA-style CSV
```

Code (MIT): https://github.com/minchinweb/hacktoberfest-2026-1

## How it was built

The whole thing was built in a Claude Code session, with me steering from the phone and the terminal. The curated transcript:

{% agent_session building-roadbean-voice-memos-to-beancount-entries-9fp3fv %}

## Author's Notes

*N.B. Yes, this is very heavily written (code and documentation and the first draft of this post) using AI, and this required a fair bit of tinkering, so no "one shotting" here. As an experiment, I'm going to continue.*
