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

**roadbean** turns voice memos recorded on my phone, while I'm in the car, into entries in my [Beancount](https://beancount.github.io/) ledger. I say "trip start, odometer 1234, heading to the library", and later "trip end, 1254", and say "Safeway, 42 dollars 28, GST 2.01" when I buy groceries. I get a mileage log I can hand to the CRA and receipts waiting for review.

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

<!-- TODO: swap in a cleaner example from a real drive if you get one. -->

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

Whistle's wrong trip was only caught by the low-confidence flag. That result is why native audio is the default. Five synthetic recordings is a small, friendly sample, not a benchmark. On real phone recordings (low sample rate, car noise) the results were "so-so", and I didn't measure them. The raw recordings are in the inbox if anyone wants to review them by hand.

I also considered EmbeddingGemma 2 for matching payees to rules. I decided against it: payees are a few dozen strings, normalized matching plus explicit rules is predictable, and an embedding match would add a non-deterministic step exactly where I want determinism.

## Taking it outside (Touch Grass)

<!-- TODO: this is the section the challenge is about. Fill in after a real drive:
- where you went, what you said, what the phone buttons were like to use one-handed
- what Gemma got right and wrong on real car audio
- anything you changed because of it -->

## Honest limitations

- Tested end to end on the laptop with synthetic and a few real memos. On-phone transcription never worked for me, and I haven't verified the llama.cpp path on the Pixel. The Termux record/photo/sync shortcuts exist and were tested against stubs.
- Accuracy on real in-car audio was "so-so" and is unmeasured.
- Speech recognition errors become review lines, not wrong data, but they still need a human. Numbers read aloud ("1 2 3 4") are the weak spot.
- Single user, single currency (CAD default), personal vehicle with the CRA allowance enabled; the account names are the Beancount ones from my own setup.

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
