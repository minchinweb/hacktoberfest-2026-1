"""Ollama backend (laptop). Extraction is schema-constrained via `format`."""

from __future__ import annotations

import base64
from pathlib import Path

from ..extract import SCHEMA
from . import BackendError, get_json, parse_model_json, post_json

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {"amount": {"type": ["string", "null"]}, "payee": {"type": ["string", "null"]}},
    "required": ["amount"],
}


class OllamaBackend:
    name = "ollama"

    def __init__(self, cfg: dict):
        self.url = cfg["models"]["ollama_url"].rstrip("/")
        self.model = cfg["models"]["extract"]
        self.vision = cfg["models"]["vision"]

    def _chat(self, model: str, content: str, schema: dict, images: list[str] | None = None) -> dict:
        msg = {"role": "user", "content": content}
        if images:
            msg["images"] = images
        r = post_json(f"{self.url}/api/chat", {
            "model": model, "messages": [msg], "format": schema, "stream": False,
            "options": {"temperature": 0},
        })
        return parse_model_json(r["message"]["content"])

    def extract(self, prompt: str) -> dict:
        return self._chat(self.model, prompt, SCHEMA)

    def describe_receipt(self, image: Path) -> dict:
        b64 = base64.b64encode(image.read_bytes()).decode()
        return self._chat(
            self.vision,
            "Read this receipt. Return the final total paid as a decimal string (no currency symbol) and the merchant name.",
            RECEIPT_SCHEMA, [b64],
        )

    def transcribe_native(self, audio: Path) -> str:
        """Experimental: OpenAI-compatible input_audio part. Whether a given Ollama build accepts it is probed by `doctor`."""
        b64 = base64.b64encode(audio.read_bytes()).decode()
        r = post_json(f"{self.url}/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Transcribe this audio exactly. Output only the transcript."},
                {"type": "input_audio", "input_audio": {"data": b64, "format": audio.suffix.lstrip(".") or "wav"}},
            ]}],
            "temperature": 0,
        })
        return r["choices"][0]["message"]["content"].strip()

    def probe(self) -> dict:
        out = {"reachable": False, "models": [], "extract_model": self.model, "extract_present": False, "native_audio": False}
        try:
            tags = get_json(f"{self.url}/api/tags")
        except BackendError as e:
            out["error"] = str(e)
            return out
        out["reachable"] = True
        out["models"] = [m["name"] for m in tags.get("models", [])]
        out["extract_present"] = any(n == self.model or n.split(":")[0] == self.model for n in out["models"])
        if out["extract_present"]:
            try:
                info = post_json(f"{self.url}/api/show", {"model": self.model}, timeout=10)
                out["native_audio"] = "audio" in (info.get("capabilities") or [])
            except BackendError:
                pass
        return out
