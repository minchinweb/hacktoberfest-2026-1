---
title: "roadbean: say it in the car, get it in the ledger"
published: false
description: "Voice memos from my phone become pending Beancount entries. A local model reads; plain Python checks."
tags: hf26challenge, gemma, python, opensource
cover_image:
---

*This is my submission for the [Hacktoberfest Open-Source AI Challenge: Week 1](https://dev.to/challenges/hacktoberfest-week1-2026-10-05) (Touch Grass). It is also entered for **Best Use of Gemma**.*

## What I built

**roadbean** turns voice memos recorded on my phone, while I'm in the car, into entries in my [Beancount](https://beancount.github.io/) ledger. I say "trip start, odometer 1234, heading to the library", and later "trip end, 1254", and say "Safeway, 42 dollars 28, GST 7 cents" when I buy groceries. I get a mileage log I can hand to the CRA (the Canada Revenue Agency, i.e. the "tax man") and receipts waiting for review.

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

Look at what the demo does *not* do. My first real memo was transcribed as "uh memo". The model couldn't make a trip or receipt of it, so the entry says `not a trip or receipt; file by hand` instead of inventing something. The receipt memo came out as "purchase staple safeway for 42 28 and gst of 7 7", and the entry was written with `no rule matched payee; left uncategorized` and a review flag. (It also got the GST wrong; more on that below.) The run also flagged a 305,023 km "trip" as exceeding `max_trip_km`, because a stale open trip from my earlier testing got paired with the new start. It was caught by a validation rule, not by me. Real input is messy; the point is that every miss lands as a visible review line rather than a wrong number in the books.

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
  gst: "g"
  transcript: "purchase staple safeway for 42 28 and gst of 7 7"
  ; REVIEW: no rule matched payee; left uncategorized
  Expenses:Uncategorized      40.27 CAD
  Assets:GST-Receivable        2.01 CAD
  Liabilities:Visa           -42.28 CAD
```

Look closely at the GST line: **2.01 is wrong.** I said "7 cents". The extractor only records a GST *code* (`g` = taxable, `z` = zero-rated, `e` = exempt), not an amount, so it heard "GST applies" and the Python code split the total at a flat 5%. That is a bad assumption for groceries, where a basket usually mixes zero-rated items (milk, vegetables) with taxable ones (snacks, paper goods). It is exactly the kind of error the review step exists for, and it is still a limitation: roadbean can't yet take a spoken GST amount. I'm leaving the real output here instead of a tidy example. (The odd `"Null"` narration is also real output, and also still a bug.)

## Why Gemma

I wanted everything to run on hardware I own. The same family covers both ends:

- **On the laptop:** `gemma4:e4b` via Ollama does speech-to-text *and* extraction. One model, no separate STT stack.
- **On the phone:** the plan was a smaller Gemma (E2B) through llama.cpp in Termux, so a memo could be processed without the laptop. I didn't get speech recognition working on the phone in time, so the phone only records, photographs and syncs; all the model work happens on the laptop.

### Native audio vs. a dedicated STT model

I tried Whistle (Cactus's tiny STT model) against Gemma's native audio on five synthetic memos (clean but robotic Windows SAPI voices, so an easy case for both):

| STT | Odometer read correctly (3 trips) | Failure mode |
|---|---|---|
| Gemma native audio | 3 / 3 | none on odometer readings (one free-text word misheard) |
| Whistle | 0 / 3 | produced a plausible but wrong 642 km trip |

Whistle's wrong trip was only caught by the low-confidence flag. That result is why native audio is the default. Five synthetic recordings is a small, friendly sample, not a benchmark. Real voice samples proved harder to process, but I don't have enough of them to give meaningful numbers like the table above.

I also considered EmbeddingGemma 2 for matching payees to rules. I decided against it: payees are a few dozen strings, normalized matching plus explicit rules is predictable, and an embedding match would add a non-deterministic step exactly where I want determinism.

## Taking it outside (Touch Grass)

The idea is to keep phone time to a minimum while still keeping the records the CRA requires.

- Set up the phone side at home: install the Termux shortcuts and add them to the home screen.
- Get in the car at the start of the trip, tap the "memo" shortcut and say "Trip start. Odometer xxx km."
- Drive around town and run errands. Not a lot of grass, as it's snowing, but we still get fresh air.
- After the purchase, tap the "memo" shortcut again and say "Safeway purchase. 42.28 total, 7 cents GST."
- Tap the "photo" shortcut to photograph the receipt. There is no photo preview, so it's a best guess, but the idea is to keep phone time as low as possible.
- Back home, tap the "memo" shortcut and say "Trip end. Odometer xxx km."
- Tap the "sync" shortcut.
- The laptop processes the data later, at home.

The voice memos landed in the inbox as they were supposed to, and git made sure they ended up on my laptop for review; so that part worked.

Gemma's transcription of the car audio was a coin flip. It's hard to know whether the cause is the low-bandwidth recording from the phone, the phone's microphone placement, or the model itself. More investigation is needed. But in a pinch, the original recordings are available for human review.

For changes, I would provide more feedback when using the shortcuts; it's hard to be confident that everything is working as expected. Also, installing a bunch of scripts in Termux is cool, but not really user friendly; a full Android app would be a (much more involved) option. Finally, I would love to figure out how to do the audio processing on my phone; the model seems small enough to support this, in theory.

## Honest limitations

- Tested end to end on the laptop with synthetic and a few real memos. The Termux shortcuts work on the phone, but I didn't get on-phone voice recognition working.
- Speech recognition errors become review lines, not wrong data, but they still need a human. Numbers read aloud ("1 2 3 4") are the weak spot.
- GST is a flat 5% split when the receipt is marked taxable. Mixed baskets, such as groceries, come out wrong, and a spoken GST amount is ignored.
- Single user, single currency (CAD default), personal vehicle with the CRA allowance enabled; the account names are the Beancount ones from my own setup.
- There is almost no feedback on the phone. That was a feature of the design brief, but it makes it hard to feel confident the process hasn't silently broken.
- It still requires a laptop to process.
- It syncs through git. GitHub private repos are private to other users, but GitHub still holds the data, and trip and financial data are sensitive. Self-hosting is an option, but it's a lot of setup for one project.

## Why open matters here

Trip logs and receipts say where I go, when I'm away and what I spend. I didn't want a cloud API in the middle of that.

- **Privacy.** Audio, photos and transcripts are processed on my laptop with Gemma through Ollama. Nothing is uploaded except to my own git remote, which I can control.
- **Swappable models.** The speech engine and the extractor are config settings (`native`, Whistle, whisper.cpp; Ollama or llama.cpp). That is how I found that Gemma's native audio read odometers better than Whistle, with a one-line change. Hopefully better models keep coming out.
- **No meter running.** A year of memos and receipts costs nothing per call. Re-runs are also "free".
- **Where it was worse.** A closed cloud speech API would probably have handled my noisy car audio better. On the phone, the open pieces didn't get there in time.

## Try it

On the laptop (needs Python 3.11+, [Ollama](https://ollama.com) with a Gemma model, and ffmpeg):

```bash
git clone https://github.com/minchinweb/hacktoberfest-2026-1
cd hacktoberfest-2026-1
pip install -e .[ledger]
ollama pull gemma4:e4b
roadbean init ~/roadbean        # creates config, rules, inbox
roadbean doctor ~/roadbean      # checks Ollama, ffmpeg, the model
roadbean process ~/roadbean     # inbox -> staging.bean
roadbean logbook ~/roadbean     # CRA-style CSV
```

You can try it without a phone: drop `.m4a` or `.wav` memos named by time (`2026-10-10T102541.m4a`) into `~/roadbean/inbox/`, or use the synthetic samples in `samples/`.

### Setting up the phone (Android + Termux)

The phone only records, photographs and syncs. Memos reach the laptop through a **private** git repo, because they contain your voice and optionally your location.

1. **Make a private inbox repo**, e.g. `gh repo create roadbean-inbox --private`.
2. **Install Termux, Termux:API and Termux:Widget from F-Droid** (all three from the same source), then in Termux:
   ```bash
   pkg install git termux-api ffmpeg openssh
   git clone https://github.com/minchinweb/hacktoberfest-2026-1 ~/roadbean-src
   cd ~/roadbean-src && bash termux/install.sh
   ```
   This puts `rb-memo`, `rb-sync` and `rb-photo` in `~/.shortcuts/tasks/`, so a widget tap runs in the background instead of opening a terminal. Run `termux-microphone-record -d` once by hand and allow the microphone prompt.
3. **Let the phone push.** Make an SSH key (`ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`), add the public key as a deploy key with write access on the inbox repo, then run `bash termux/init-repo.sh git@github.com:YOU/roadbean-inbox.git`.
4. **Add the widgets.** Long-press the home screen, add a Termux:Widget, and pick `rb-memo`, `rb-photo` and `rb-sync`. Tap `rb-memo` to start recording and again to stop (60 second cap).
5. **On the laptop,** clone the inbox repo as your roadbean folder: `git clone git@github.com:YOU/roadbean-inbox.git ~/roadbean`, then `roadbean init ~/roadbean`. After each trip, `git -C ~/roadbean pull && roadbean process ~/roadbean`.

The full instructions, including removing everything with `termux/uninstall.sh`, are in the repo README.

## Code

{% embed https://github.com/minchinweb/hacktoberfest-2026-1 %}

MIT licensed, and built this week for the challenge.

## How it was built

The whole thing was built in a Claude Code session, with me steering from the terminal. The curated transcript:

{% agent_session building-roadbean-voice-memos-to-beancount-entries-9fp3fv %}

## Author's Notes

*N.B. Yes, this is very heavily written (code and documentation and the first draft of this post) using AI, and this required a fair bit of tinkering, so no "one shotting" here. As an experiment, I'm going to continue.*
