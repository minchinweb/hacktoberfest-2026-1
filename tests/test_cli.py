"""The CLI takes one folder holding roadbean.toml, rules.toml and inbox/."""
import shutil

from conftest import ROOT, bean_errors
from roadbean.cli import main


def make_home(tmp_path):
    home = tmp_path / "rb"
    assert main(["init", str(home)]) == 0
    for p in (ROOT / "samples" / "expected").glob("*.extract.json"):
        shutil.copy(p, home / "inbox" / p.name)
    return home


def test_init_creates_folder_and_never_overwrites(tmp_path, capsys):
    home = make_home(tmp_path)
    assert {p.name for p in home.iterdir()} >= {"roadbean.toml", "rules.toml", "inbox"}
    (home / "rules.toml").write_text("# mine\n", encoding="utf-8")
    assert main(["init", str(home)]) == 0
    assert (home / "rules.toml").read_text(encoding="utf-8") == "# mine\n"
    assert "[INFO] Kept" in capsys.readouterr().out


def test_process_uses_folder_config_rules_inbox_and_writes_staging_there(tmp_path):
    home = make_home(tmp_path)
    assert main(["process", str(home), "--from-json"]) == 0
    staging = (home / "staging.bean").read_text(encoding="utf-8")
    assert "Expenses:Vehicle:Fuel" in staging  # rules.toml from the folder was used
    assert bean_errors(staging) == []
    assert main(["process", str(home), "--from-json"]) == 0  # idempotent
    assert (home / "staging.bean").read_text(encoding="utf-8") == staging


def test_folder_comes_from_rb_home_env(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    monkeypatch.setenv("RB_HOME", str(home))
    assert main(["process", "--from-json", "--dry-run"]) == 0
    assert not (home / "staging.bean").exists()


def test_folder_config_is_honoured(tmp_path):
    home = make_home(tmp_path)
    cfg = (home / "roadbean.toml").read_text(encoding="utf-8").replace("enabled = true", "enabled = false")
    (home / "roadbean.toml").write_text(cfg, encoding="utf-8")
    main(["process", str(home), "--from-json"])
    assert "allowance" not in (home / "staging.bean").read_text(encoding="utf-8").lower()


def test_bare_folder_of_memos_still_works(tmp_path):
    bare = tmp_path / "memos"
    bare.mkdir()
    for p in (ROOT / "samples" / "expected").glob("*.extract.json"):
        shutil.copy(p, bare / p.name)
    assert main(["process", str(bare), "--from-json"]) == 0
    assert (bare / "staging.bean").exists()


def test_logbook_defaults_to_folder_ledger_and_csv(tmp_path):
    home = make_home(tmp_path)
    main(["process", str(home), "--from-json"])
    assert main(["logbook", str(home), "--year", "2026"]) == 2  # no main.bean yet: clear error
    text = (home / "staging.bean").read_text(encoding="utf-8")
    import re
    accts = sorted(set(re.findall(r"^\s+([A-Z][A-Za-z0-9-]*(?::[A-Za-z0-9-]+)+)\s+-?[\d.]+ ", text, re.M)) | set(re.findall(r"balance (\S+)", text)))
    (home / "main.bean").write_text("2026-01-01 commodity KM\n2026-01-01 commodity CAD\n"
        + "".join(f"2026-01-01 open {a}\n" for a in accts) + 'include "staging.bean"\n', encoding="utf-8")
    assert main(["logbook", str(home), "--year", "2026"]) == 0
    assert (home / "logbook-2026.csv").read_text(encoding="utf-8").count("\n") == 3
