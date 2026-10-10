"""roadbean command line: doctor, process, logbook."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import log
from .backends import BackendError, get_backend
from .config import load_config, load_rules


def home_of(args) -> Path:
    """The roadbean folder: argument, else $RB_HOME, else the current directory."""
    return Path(args.folder or os.environ.get("RB_HOME") or ".").expanduser()


def load_home(args, home: Path) -> tuple[dict, list]:
    """Config and rules from the folder (roadbean.toml, rules.toml), unless overridden by flags."""
    cfg_path = Path(args.config) if getattr(args, "config", None) else home / "roadbean.toml"
    rules_path = Path(args.rules) if getattr(args, "rules", None) else home / "rules.toml"
    if not cfg_path.exists():
        log.warn(f"No {cfg_path}; using built-in defaults (run `roadbean init {home}` to create one).")
        cfg_path = None
    if not rules_path.exists():
        log.warn(f"No {rules_path}; every payee will be left uncategorized.")
    return load_config(cfg_path), load_rules(rules_path)


def cmd_init(args) -> int:
    home = home_of(args)
    src = Path(__file__).resolve().parent.parent
    (home / "inbox").mkdir(parents=True, exist_ok=True)
    for name, example in (("roadbean.toml", "roadbean.example.toml"), ("rules.toml", "rules.example.toml")):
        dest = home / name
        if dest.exists():
            log.info(f"Kept {dest}", file=sys.stdout)
        elif (src / example).exists():
            shutil.copy(src / example, dest)
            log.good(f"Wrote {dest}", file=sys.stdout)
        else:
            log.error(f"Cannot find {example}; reinstall roadbean from a source checkout.")
            return 1
    log.good(f"Ready: {home}", file=sys.stdout)
    log.info(f"Put memos in {home / 'inbox'}, edit the two .toml files, then `roadbean process {home}`.", file=sys.stdout)
    return 0


def cmd_doctor(args) -> int:
    out = sys.stdout
    cfg, _ = load_home(args, home_of(args))
    name = args.backend or cfg["models"]["backend"]
    log.info(f"Backend: {name}", file=out)
    ok = True
    try:
        backend = get_backend(cfg, name)
        p = backend.probe()
    except BackendError as e:
        log.error(str(e), file=out)
        return 1
    if not p.get("reachable"):
        log.error(f"Not reachable: {p.get('error', '')}", file=out)
        ok = False
    else:
        log.good("Reachable.", file=out)
        if "extract_present" in p:
            if p["extract_present"]:
                log.good(f"Extract model {p['extract_model']} is installed.", file=out)
            else:
                log.error(f"Extract model {p['extract_model']} is missing (try: ollama pull {p['extract_model']}).", file=out)
            ok &= p["extract_present"]
    native = bool(p.get("native_audio"))
    (log.good if native else log.info)(f"Native audio on {p['extract_model']}: {'yes' if native else 'no'}.", file=out)

    from . import stt
    spec = cfg["models"]["stt"]
    w = cfg["whisper"]
    whisper_ok = bool(shutil.which(w["binary"])) and any(Path(w["model_dir"]).expanduser().glob("ggml-*.bin"))
    whistle_ok = stt.whistle_available()
    (log.good if whistle_ok else log.info)(
        "Whistle is " + ("available." if whistle_ok else "not installed (pip install cactus-needle; needle download whistle)."),
        file=out)
    (log.good if whisper_ok else log.info)(
        "whisper.cpp is " + ("available." if whisper_ok else f"not installed ({w['binary']} + a model in {w['model_dir']})."),
        file=out)
    if shutil.which("ffmpeg"):
        log.good("ffmpeg found (converts phone audio to 16 kHz WAV).", file=out)
    else:
        log.error("ffmpeg not found (needed to convert phone audio to 16 kHz WAV).", file=out)
        ok = False
    plan = "native Gemma audio" if native and spec == "native" else spec
    usable = {"whistle": whistle_ok, "native": native}.get(spec, whisper_ok if spec.startswith("whisper.cpp") else False)
    if usable:
        log.good(f"Plan: transcribe with {plan}; extract with {p['extract_model']} via {name}.", file=out)
    else:
        alt = "whistle" if whistle_ok else ("whisper.cpp" if whisper_ok else None)
        log.error(f"{spec} is unavailable; " + (f"switch [models].stt to {alt!r}." if alt else "install Whistle or whisper.cpp."),
                  file=out)
        ok = False
    return 0 if ok else 1


def cmd_process(args) -> int:
    from .pipeline import process
    home = home_of(args)
    if not home.is_dir():
        log.error(f"{home} is not a folder.")
        return 2
    cfg, rules = load_home(args, home)
    inbox = home / "inbox" if (home / "inbox").is_dir() else home  # a bare folder of memos still works
    out = Path(args.out) if args.out else home / "staging.bean"
    if args.vision:
        cfg["models"]["vision_enabled"] = True
    backend = None
    if not args.from_json:
        try:
            backend = get_backend(cfg, args.backend)
        except BackendError as e:
            log.error(str(e))
            return 2
    since = datetime.fromisoformat(args.since) if args.since else None
    res = process(inbox, cfg, rules, out, backend, from_json=args.from_json,
                  dry_run=args.dry_run, reextract=args.reextract, since=since)
    for w in res.warnings:
        log.warn(w)
    for t in res.open_trips:
        log.warn(f"Open trip: {t}")
    if args.dry_run:
        sys.stdout.write(res.new_text)
    log.good(f"{res.entries} new entries, {res.skipped} memos already staged"
             f"{f', {len(res.open_trips)} open trip(s)' if res.open_trips else ''}"
             f"{' (dry run, nothing written)' if args.dry_run else f' -> {out}'}.")
    return 0


def cmd_logbook(args) -> int:
    try:
        from . import logbook
    except ImportError:
        log.error("`roadbean logbook` needs beancount: pip install 'roadbean[ledger]' (run it on the laptop, not Termux).")
        return 2
    home = home_of(args)
    cfg, _ = load_home(args, home)
    ledger = Path(args.ledger) if args.ledger else home / "main.bean"
    if not ledger.exists():
        log.error(f"Ledger not found: {ledger} (pass --ledger, or put your ledger at {home / 'main.bean'}).")
        return 2
    lb = logbook.build(ledger, cfg, args.year)
    csv_path = Path(args.csv) if args.csv else home / f"logbook-{args.year}.csv"
    csv_path.write_text(logbook.to_csv(lb), encoding="utf-8")
    for e in lb["ledger_errors"]:
        log.error(f"Ledger: {e}")
    log.good(f"Wrote {len(lb['rows'])} trips to {csv_path}.")
    log.info(logbook.summary(lb))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="roadbean", description="Voice memos to Beancount mileage and receipts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    folder = dict(nargs="?", help="roadbean folder holding roadbean.toml, rules.toml, inbox/ (default: $RB_HOME, else .)")

    i = sub.add_parser("init", help="create a roadbean folder with starter config, rules and an inbox")
    i.add_argument("folder", **folder)
    i.set_defaults(fn=cmd_init)

    d = sub.add_parser("doctor", help="check models, STT and audio support; print the backend plan")
    d.add_argument("folder", **folder)
    d.add_argument("--config", help="override <folder>/roadbean.toml")
    d.add_argument("--backend", choices=["ollama", "llamacpp"])
    d.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("process", help="turn the folder's inbox of memos into pending Beancount entries")
    p.add_argument("folder", **folder)
    p.add_argument("--config", help="override <folder>/roadbean.toml")
    p.add_argument("--rules", help="override <folder>/rules.toml")
    p.add_argument("--out", help="override <folder>/staging.bean")
    p.add_argument("--backend", choices=["ollama", "llamacpp"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--from-json", action="store_true", help="use existing .extract.json files; no model")
    p.add_argument("--reextract", action="store_true", help="ignore cached transcripts/extracts")
    p.add_argument("--vision", action="store_true", help="read receipt photos with the vision model")
    p.add_argument("--since", help="ISO date/time; ignore older memos")
    p.set_defaults(fn=cmd_process)

    lg = sub.add_parser("logbook", help="CRA-style kilometre log and yearly totals")
    lg.add_argument("folder", **folder)
    lg.add_argument("--year", type=int, default=datetime.now().year)
    lg.add_argument("--ledger", help="your ledger (default <folder>/main.bean; it should include staging.bean)")
    lg.add_argument("--csv", help="default <folder>/logbook-<year>.csv")
    lg.add_argument("--config", help="override <folder>/roadbean.toml")
    lg.set_defaults(fn=cmd_logbook)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
