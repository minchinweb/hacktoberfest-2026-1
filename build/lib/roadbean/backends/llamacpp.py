"""llama.cpp backend (phone / Termux): talks to a local `llama-server` with a JSON-schema grammar.

Start it with e.g.  llama-server -m gemma-4-E2B-it-Q4_K_M.gguf --port 8080
"""

from __future__ import annotations

from ..extract import SCHEMA
from . import BackendError, get_json, parse_model_json, post_json


class LlamaCppBackend:
    name = "llamacpp"

    def __init__(self, cfg: dict):
        self.url = cfg["models"]["llamacpp_url"].rstrip("/")
        self.model = cfg["models"]["extract"]

    def extract(self, prompt: str) -> dict:
        r = post_json(f"{self.url}/completion", {
            "prompt": prompt, "json_schema": SCHEMA, "temperature": 0, "n_predict": 400,
        })
        return parse_model_json(r["content"])

    def describe_receipt(self, image):
        raise BackendError("receipt photo reading is not supported on the llamacpp backend; use ollama on the laptop")

    def probe(self) -> dict:
        out = {"reachable": False, "extract_model": self.model, "native_audio": False}
        try:
            get_json(f"{self.url}/health")
            out["reachable"] = True
        except BackendError as e:
            out["error"] = str(e)
        return out
