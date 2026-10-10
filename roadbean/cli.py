"""roadbean command line: doctor, process, logbook."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .backends import BackendError, get_backend
from .config import load_config, load_rules


def cmd_doctor(args) -> int:
    cfg = load_config(args.config)
    name = args.backend or cfg["models"]["backend"]
    print(f"backend: {name}")
    ok = True
    try:
        backend = get_backend(cfg, name)
        p = backend.probe()
    except BackendError as e:
        print(f"  ✗ {e}")
        return 1
    if not p.get("reachable"):
        print(f"  ✗ not reachable: {p.get('error', '')}")
        ok = False
    else:
        print("  ✓ reachable")
        if "extract_present" in p:
            mark = "✓" if p["extract_present"] else "✗ (try: ollama pull " + p["extract_model"] + ")"
            print(f"  {mark} extract model {p['extract_model']}")
            ok &= p["extract_present"]
    native = bool(p.get("native_audio"))
    print(f"  {'✓' if native else '–'} native audio on {p['extract_model']}: {'yes' if native else 'no'}")

    from . import stt
    spec = cfg["models"]["stt"]
    w = cfg["whisper"]
    whisper_ok = bool(shutil.which(w["binary"])) and any(Path(w["model_dir"]).expanduser().glob("ggml-*.bin"))
    whistle_ok = stt.whistle_available()
    print(f"  {'✓' if whistle_ok else '–'} Whistle (pip install cactus-needle; needle download whistle)")
    print(f"  {'✓' if whisper_ok else '–'} whisper.cpp ({w['binary']} + model in {w['model_dir']})")
    print(f"  {'✓' if shutil.which('ffmpeg') else '✗'} ffmpeg (converts phone audio to 16 kHz WAV)")
    plan = "native Gemma audio" if native and spec == "native" else spec
    usable = {"whistle": whistle_ok, "native": native}.get(spec, whisper_ok if spec.startswith("whisper.cpp") else False)
    if not usable:
        alt = "whistle" if whistle_ok else ("whisper.cpp" if whisper_ok else None)
        plan = f"{spec} is unavailable; " + (f"switch [models].stt to {alt!r}" if alt else "install Whistle or whisper.cpp")
        ok = False
    print(f"plan: transcribe with {plan}; extract with {p['extract_model']} via {name}")
    return 0 if ok else 1


def cmd_process(args) -> int:
    from .pipeline import process
    cfg = load_config(args.config)
    if args.vision:
        cfg["models"]["vision_enabled"] = True
    rules = load_rules(args.rules)
    backend = None
    if not args.from_json:
        try:
            backend = get_backend(cfg, args.backend)
        except BackendError as e:
            print(e, file=sys.stderr)
            return 2
    since = datetime.fromisoformat(args.since) if args.since else None
    res = process(Path(args.inbox), cfg, rules, Path(args.out), backend, from_json=args.from_json,
                  dry_run=args.dry_run, reextract=args.reextract, since=since)
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.dry_run:
        sys.stdout.write(res.new_text)
    print(f"{res.entries} new entries, {res.skipped} memos already staged"
          f"{' (dry run, nothing written)' if args.dry_run else f' -> {args.out}'}", file=sys.stderr)
    return 0


def cmd_logbook(args) -> int:
    try:
        from . import logbook
    except ImportError:
        print("`roadbean logbook` needs beancount: pip install 'roadbean[ledger]' (run it on the laptop, not Termux)",
              file=sys.stderr)
        return 2
    cfg = load_config(args.config)
    lb = logbook.build(Path(args.ledger), cfg, args.year)
    if args.csv:
        Path(args.csv).write_text(logbook.to_csv(lb), encoding="utf-8")
        print(f"wrote {len(lb['rows'])} trips to {args.csv}", file=sys.stderr)
    else:
        sys.stdout.write(logbook.to_csv(lb))
    print(logbook.summary(lb), file=sys.stderr)
    for e in lb["ledger_errors"]:
        print(f"ledger error: {e}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="roadbean", description="Voice memos to Beancount mileage and receipts.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="check models, STT and audio support; print the backend plan")
    d.add_argument("--config")
    d.add_argument("--backend", choices=["ollama", "llamacpp"])
    d.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("process", help="turn an inbox of memos into pending Beancount entries")
    p.add_argument("inbox")
    p.add_argument("--config")
    p.add_argument("--rules")
    p.add_argument("--out", default="staging.bean")
    p.add_argument("--backend", choices=["ollama", "llamacpp"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--from-json", action="store_true", help="use existing .extract.json files; no model")
    p.add_argument("--reextract", action="store_true", help="ignore cached transcripts/extracts")
    p.add_argument("--vision", action="store_true", help="read receipt photos with the vision model")
    p.add_argument("--since", help="ISO date/time; ignore older memos")
    p.set_defaults(fn=cmd_process)

    lg = sub.add_parser("logbook", help="CRA-style kilometre log and yearly totals")
    lg.add_argument("--year", type=int, default=datetime.now().year)
    lg.add_argument("--ledger", required=True)
    lg.add_argument("--csv")
    lg.add_argument("--config")
    lg.set_defaults(fn=cmd_logbook)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
