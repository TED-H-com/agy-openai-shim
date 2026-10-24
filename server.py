#!/usr/bin/env python3
"""agy-openai-shim: OpenAI-compatible /v1/chat/completions on loopback, backed by
Google's official `agy` CLI with a multi-account pool.

Vendored from the Hermes plugin `antigravity-subscription-directsdk`
(soyelmismo/hermes-antigravity-subscription, MIT) + multi-account pool patch.
Stdlib only.

Env:
  AGY_SHIM_HOST / AGY_SHIM_PORT   (default 127.0.0.1:18795)
  ANTIGRAVITY_ACCOUNT_DIRS        colon list of agy config dirs, in pool order
  ANTIGRAVITY_POOL_STRATEGY       round_robin or fill_first
  ANTIGRAVITY_POOL_STATE_DIR      pool state/events log dir
  AGY_SHIM_TIMEOUT                per-request seconds (default 900)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / "agy"))

import accounts as agy_pool  # noqa: E402
from client import AntigravityClient  # noqa: E402

logging.basicConfig(level=os.getenv("AGY_SHIM_LOGLEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agy-shim")

MODELS = ["gemini-3.8-flash", "gemini-3.8-flash-low", "gemini-3.8-flash-medium",
          "gemini-3.8-flash-high", "gemini-3.1-pro"]
TIMEOUT = float(os.getenv("AGY_SHIM_TIMEOUT", "900"))
_client_lock = threading.Lock()
_client: AntigravityClient | None = None
WORKDIR = Path(os.getenv("AGY_SHIM_WORKDIR", str(Path.home() / ".local/state/agy-openai-shim/work")))


def client() -> AntigravityClient:
    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            WORKDIR.mkdir(parents=True, exist_ok=True)
            _client = AntigravityClient(cwd=str(WORKDIR))
        return _client


def to_plain(obj):
    if isinstance(obj, SimpleNamespace):
        return {k: to_plain(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


def clean(d):
    """Drop None-valued keys recursively (OpenAI clients dislike null tool_calls etc.)."""
    if isinstance(d, dict):
        return {k: clean(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [clean(v) for v in d]
    return d


def error_status(exc: BaseException) -> tuple[int, str]:
    kind = agy_pool.classify_error(exc)
    if kind == "quota":
        return 429, "rate_limit_exceeded"
    if kind == "auth":
        return 401, "invalid_api_key"
    if kind == "transient":
        return 503, "upstream_transient"
    return 502, "upstream_error"


def sanitize_error(exc: BaseException) -> str:
    """Returns a redacted, length-limited string from an exception."""
    raw = str(exc)[:300]
    # Redact token-like strings (e.g., sk-, ya29., AIza, or long hex/base64 strings)
    raw = re.sub(r'(?:sk-|ya29\.|AIza)[A-Za-z0-9-_]{20,}', '***REDACTED***', raw)
    # Target 40+ char hex or base64ish looking tokens that aren't typical words
    raw = re.sub(r'\b[A-Za-z0-9-_]{40,}\b', '***REDACTED***', raw)
    # Redact real absolute filesystem paths only (starting with /home, /root, /tmp, /etc, /var, /Users)
    raw = re.sub(r'(/(?:home|root|tmp|etc|var|Users)/[a-zA-Z0-9_.-/]+)', '***PATH***', raw)
    return f"upstream error: {raw}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agy-openai-shim/1"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            now = int(time.time())
            self._json(200, {"object": "list", "data": [
                {"id": m, "object": "model", "created": now, "owned_by": "google-antigravity"} for m in MODELS]})
        elif self.path.rstrip("/") in ("/health", "/healthz", ""):
            accts = [a.name for a in agy_pool.discover_accounts()]
            self._json(200 if accts else 503, {"ok": bool(accts), "accounts": accts})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        try:
            length_str = self.headers.get("Content-Length")
            length = 0
            if length_str is not None:
                length = int(length_str)
                if length < 0:
                    return self._json(400, {"error": {"message": "bad request: negative Content-Length"}})
            if length > 10 * 1024 * 1024:  # 10 MB limit
                return self._json(413, {"error": {"message": "payload too large"}})

            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": {"message": "bad request: invalid JSON"}})

            if not isinstance(req, dict):
                return self._json(400, {"error": {"message": "bad request: JSON payload must be a dictionary"}})
            if req.get("messages") is not None and not isinstance(req.get("messages"), list):
                return self._json(400, {"error": {"message": "bad request: messages must be a list"}})
            if req.get("model") is not None and not isinstance(req.get("model"), str):
                return self._json(400, {"error": {"message": "bad request: model must be a string"}})
            if req.get("reasoning") is not None and not isinstance(req.get("reasoning"), dict):
                return self._json(400, {"error": {"message": "bad request: reasoning must be a dictionary"}})
        except ValueError:
            return self._json(400, {"error": {"message": "bad request: invalid Content-Length"}})
        except Exception as exc:  # noqa: BLE001
            log.warning("bad request: %s", str(exc)[:300])
            return self._json(400, {"error": {"message": "bad request: invalid input"}})

        messages = []
        for m in req.get("messages") or []:
            if isinstance(m, dict) and m.get("role") == "developer":
                m = {**m, "role": "system"}
            messages.append(m)
        model = req.get("model") or "gemini-3.8-flash"
        stream = bool(req.get("stream"))
        effort = req.get("reasoning_effort") or (req.get("reasoning") or {}).get("effort")
        kwargs = dict(model=model, messages=messages, tools=req.get("tools") or None,
                      tool_choice=req.get("tool_choice"), stream=stream,
                      reasoning_effort=effort, timeout=TIMEOUT)
        created = int(time.time())
        rid = "chatcmpl-" + uuid.uuid4().hex[:24]
        t0 = time.monotonic()
        try:
            result = client().chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            status, code = error_status(exc)
            log.warning("completion failed (%s): %s", status, str(exc)[:300])
            return self._json(status, {"error": {"message": sanitize_error(exc), "type": code, "code": code}})

        if not stream:
            out = clean(to_plain(result))
            out.update({"id": rid, "object": "chat.completion", "created": created, "model": model})
            log.info("served non-stream model=%s in %.1fs", model, time.monotonic() - t0)
            return self._json(200, out)

        it = iter(result)
        try:
            first = next(it, None)
        except Exception as exc:  # noqa: BLE001
            status, code = error_status(exc)
            log.warning("stream failed before first chunk (%s): %s", status, str(exc)[:300])
            return self._json(status, {"error": {"message": sanitize_error(exc), "type": code, "code": code}})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(chunk):
            d = clean(to_plain(chunk))
            d.update({"id": rid, "object": "chat.completion.chunk", "created": created, "model": model})
            usage = d.get("usage")
            if usage and "choices" not in d:
                d["choices"] = []
            self.wfile.write(b"data: " + json.dumps(d).encode() + b"\n\n")
            self.wfile.flush()

        try:
            if first is not None:
                emit(first)
            for chunk in it:
                emit(chunk)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            log.info("served stream model=%s in %.1fs", model, time.monotonic() - t0)
        except (BrokenPipeError, ConnectionResetError):
            log.info("client disconnected")
            close = getattr(result, "close", None)
            if close:
                close()
        except Exception as exc:  # noqa: BLE001
            log.warning("stream failed mid-way: %s", str(exc)[:300])
            try:
                err = {"error": {"message": sanitize_error(exc), "type": error_status(exc)[1]}}
                self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\n")
                self.wfile.flush()
            except OSError:
                pass


def main():
    host = os.getenv("AGY_SHIM_HOST", "127.0.0.1")
    port = int(os.getenv("AGY_SHIM_PORT", "18795"))
    accts = agy_pool.discover_accounts()
    log.info("agy-openai-shim on %s:%d accounts=%s strategy=%s", host, port,
             [a.name for a in accts], agy_pool.strategy())
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
