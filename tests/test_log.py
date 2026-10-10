"""Status lines look like Battlestation's: [GOOD] green, [WARN] yellow, [ERRO] red; only the code is coloured."""
import io
import shutil

from conftest import ROOT
from roadbean import log
from roadbean.cli import main


def test_plain_when_not_a_terminal(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    buf = io.StringIO()
    log.good("done", file=buf)
    log.warn("look", indent=1, file=buf)
    log.error("broke", file=buf)
    log.info("fyi", file=buf)
    assert buf.getvalue() == "[GOOD] done\n    [WARN] look\n[ERRO] broke\n[INFO] fyi\n"


def test_codes_are_coloured_green_yellow_red(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    buf = io.StringIO()
    log.good("a", file=buf)
    log.warn("b", file=buf)
    log.error("c", file=buf)
    assert buf.getvalue() == "[\x1b[32mGOOD\x1b[0m] a\n[\x1b[33mWARN\x1b[0m] b\n[\x1b[31mERRO\x1b[0m] c\n"


def test_no_color_wins(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    buf = io.StringIO()
    log.good("a", file=buf)
    assert buf.getvalue() == "[GOOD] a\n"


def test_cli_reports_with_codes_and_keeps_stdout_clean(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    home = tmp_path / "rb"
    main(["init", str(home)])
    assert "[GOOD] Wrote" in capsys.readouterr().out
    for p in (ROOT / "samples" / "expected").glob("*.extract.json"):
        shutil.copy(p, home / "inbox" / p.name)
    main(["process", str(home), "--from-json", "--dry-run"])
    cap = capsys.readouterr()
    assert cap.out.startswith("2026-10-09 ! ")  # Beancount only on stdout
    assert "[GOOD] 8 new entries" in cap.err
    assert main(["process", str(tmp_path / "nope")]) == 2
    assert "[ERRO] " in capsys.readouterr().err
