"""Speech-to-text. Pinned in config as [models].stt: "whistle", "whisper.cpp:<model>", or "native" (Gemma audio)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class SttError(RuntimeError):
    pass


def to_wav16k(src: Path, dst: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SttError("ffmpeg not found (needed to convert memos to 16 kHz mono WAV)")
    r = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
        capture_output=True, text=True,
    )
    if r.returncode:
        raise SttError(f"ffmpeg failed: {r.stderr.strip()}")
    return dst


def keywords(cfg: dict, rules: list[dict]) -> list[str]:
    """Bias words for engines that support it (Whistle): vehicle names and known payees."""
    words = ["odometer", "kilometres", "receipt"]
    for k, v in cfg["vehicles"].items():
        words += [k, *([v["name"]] if v.get("name") else []), *v.get("aliases", [])]
    words += [r["payee"] for r in rules if "payee" in r]
    return list(dict.fromkeys(words))


def whistle_available() -> bool:
    try:
        import needle  # noqa: F401
        return True
    except ImportError:
        return False


def _whistle(wav: Path, kw: list[str], weights: str) -> str:
    os.environ.setdefault("NEEDLE_TELEMETRY", "0")  # keep everything on-device
    try:
        import needle
    except ImportError as e:
        raise SttError("Whistle needs `pip install cactus-needle` and `needle download whistle`") from e
    weights = str(Path(weights).expanduser())
    res = needle.transcribe(str(wav), weights=weights, keywords=kw or None)
    return res["text"].strip()


def _whisper_cpp(wav: Path, cfg: dict, model: str) -> str:
    w = cfg["whisper"]
    binary = shutil.which(w["binary"])
    if not binary:
        raise SttError(f"{w['binary']} not found on PATH. Set [models].stt = \"native\" (Gemma audio via Ollama) or \"whistle\" in roadbean.toml, and pass --config; `roadbean doctor` shows what is available")
    model_file = Path(w["model_dir"]).expanduser() / f"ggml-{model}.bin"
    if not model_file.exists():
        raise SttError(f"whisper model missing: {model_file}")
    r = subprocess.run([binary, "-m", str(model_file), "-f", str(wav), "-nt", "-np"], capture_output=True, text=True)
    if r.returncode:
        raise SttError(f"whisper.cpp failed: {r.stderr.strip()[:300]}")
    return " ".join(r.stdout.split())


def transcribe(audio: Path, cfg: dict, rules: list[dict] | None = None, backend=None) -> str:
    spec = cfg["models"]["stt"]
    if spec == "native" and (backend is None or not hasattr(backend, "transcribe_native")):
        raise SttError("stt = native requires a backend with native audio support")
    with tempfile.TemporaryDirectory() as td:
        wav = to_wav16k(audio, Path(td) / "memo.wav")  # always: phone m4a/aac is not accepted by any engine as-is
        if spec == "native":
            return backend.transcribe_native(wav)
        if spec == "whistle":
            return _whistle(wav, keywords(cfg, rules or []), cfg["whistle"]["weights"])
        if spec.startswith("whisper.cpp:"):
            return _whisper_cpp(wav, cfg, spec.split(":", 1)[1])
    raise SttError(f"unknown stt spec: {spec!r}")
