"""Backends against a fake local server: checks request shape and response handling, not model quality."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import ROOT
from roadbean.backends import BackendError, get_backend, parse_model_json
from roadbean.config import load_config
from roadbean.extract import SCHEMA, build_prompt

REPLY = {"type": "trip_end", "odometer": 48252, "confidence": "high"}
seen: list = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"models": [{"name": "gemma4:e4b"}]} if self.path == "/api/tags" else {"status": "ok"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, req))
        if self.path == "/api/chat":
            self._send({"message": {"content": json.dumps(REPLY)}})
        elif self.path == "/api/show":
            self._send({"capabilities": ["completion", "audio"]})
        else:
            self._send({"content": json.dumps(REPLY)})


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    seen.clear()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_ollama_extract_sends_schema_and_probe_sees_audio(server):
    cfg = load_config(ROOT / "roadbean.example.toml")
    cfg["models"]["ollama_url"] = server
    b = get_backend(cfg, "ollama")
    assert b.extract(build_prompt(cfg, "End trip, forty-eight two fifty-two.")) == REPLY
    path, req = seen[0]
    assert path == "/api/chat" and req["format"] == SCHEMA and req["model"] == "gemma4:e4b" and req["think"] is False
    assert "forty-eight two fifty-two" in req["messages"][0]["content"] and "{transcript}" not in req["messages"][0]["content"]
    p = b.probe()
    assert p["reachable"] and p["extract_present"] and p["native_audio"]


def test_llamacpp_extract_uses_json_schema_grammar(server):
    cfg = load_config(ROOT / "roadbean.example.toml")
    cfg["models"]["llamacpp_url"] = server
    b = get_backend(cfg, "llamacpp")
    assert b.extract("x") == REPLY
    assert seen[0][0] == "/completion" and seen[0][1]["json_schema"] == SCHEMA
    assert b.probe()["reachable"]


def test_unreachable_backend_raises_cleanly():
    cfg = load_config(None)
    cfg["models"]["ollama_url"] = "http://127.0.0.1:9"
    with pytest.raises(BackendError):
        get_backend(cfg, "ollama").extract("x")
    assert get_backend(cfg, "ollama").probe()["reachable"] is False


def test_parse_model_json_handles_fences_and_garbage():
    assert parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(BackendError):
        parse_model_json("sorry, I can't")
