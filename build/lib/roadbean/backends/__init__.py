"""Model backends. Each exposes extract(prompt) -> dict and probe() -> dict."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class BackendError(RuntimeError):
    pass


def post_json(url: str, payload: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise BackendError(f"{url}: {e}") from e


def get_json(url: str, timeout: float = 5) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise BackendError(f"{url}: {e}") from e


def parse_model_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        out = json.loads(text)
    except ValueError as e:
        raise BackendError(f"model returned non-JSON: {text[:200]!r}") from e
    if not isinstance(out, dict):
        raise BackendError("model JSON was not an object")
    return out


def get_backend(cfg: dict, name: str | None = None):
    name = name or cfg["models"]["backend"]
    if name == "ollama":
        from .ollama import OllamaBackend
        return OllamaBackend(cfg)
    if name == "llamacpp":
        from .llamacpp import LlamaCppBackend
        return LlamaCppBackend(cfg)
    raise BackendError(f"unknown backend {name!r}")
