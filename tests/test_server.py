import json
import os
import signal
import subprocess
import time
import urllib.request
from urllib.error import HTTPError
import threading
from http.server import ThreadingHTTPServer

import pytest
import sys
from pathlib import Path

# Add the root directory to sys.path so we can import server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import sanitize_error, Handler

class TestSanitizeError:
    def test_redact_tokens(self):
        class FakeExc(Exception):
            pass

        exc = FakeExc("Error with key sk-1234567890abcdefghijklmnopqrs")
        assert "***REDACTED***" in sanitize_error(exc)
        assert "sk-" not in sanitize_error(exc)

        exc = FakeExc("Error with ya29.a0AfB_byCD-1234567890abcdefghijklmnopqrs")
        assert "***REDACTED***" in sanitize_error(exc)
        assert "ya29." not in sanitize_error(exc)

        exc = FakeExc("Error with AIzaSyB-1234567890abcdefghijklmnopqrs")
        assert "***REDACTED***" in sanitize_error(exc)
        assert "AIza" not in sanitize_error(exc)

    def test_redact_long_tokens(self):
        class FakeExc(Exception):
            pass

        exc = FakeExc("Long token is 1234567890abcdefghijklmnopqrstuvwxyz1234567890 here")
        assert "***REDACTED***" in sanitize_error(exc)
        assert "1234567890abcdefghijklmnopqrstuvwxyz1234567890" not in sanitize_error(exc)

    def test_redact_paths(self):
        class FakeExc(Exception):
            pass

        exc = FakeExc("Config file not found: /home/user/config.json")
        sanitized = sanitize_error(exc)
        assert "***PATH***" in sanitized
        assert "/home/user/config.json" not in sanitized

        exc = FakeExc("Error writing to /tmp/scratch/data.bin")
        assert "***PATH***" in sanitize_error(exc)

    def test_keep_urls_and_normal_paths(self):
        class FakeExc(Exception):
            pass

        exc = FakeExc("Failed to reach https://api.openai.com/v1/models/gemini-1.5-pro")
        sanitized = sanitize_error(exc)
        assert "https://api.openai.com/v1/models/gemini-1.5-pro" in sanitized
        assert "***PATH***" not in sanitized


def post(url, data=None, headers={}):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read().decode()
    except HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture(scope="module")
def local_server():
    os.environ["AGY_SHIM_HOST"] = "127.0.0.1"
    os.environ["AGY_SHIM_PORT"] = "18797"

    srv = ThreadingHTTPServer(("127.0.0.1", 18797), Handler)
    thread = threading.Thread(target=srv.serve_forever)
    thread.daemon = True
    thread.start()

    yield "http://127.0.0.1:18797/v1/chat/completions"

    srv.shutdown()


class TestServerValidation:
    def test_oversize_payload(self, local_server):
        status, text = post(local_server, headers={"Content-Length": "15000000"}, data=b"{}")
        assert status == 413
        assert "payload too large" in text

    def test_negative_content_length(self, local_server):
        status, text = post(local_server, headers={"Content-Length": "-1"}, data=b"{}")
        assert status == 400
        assert "negative Content-Length" in text

    def test_invalid_content_length(self, local_server):
        status, text = post(local_server, headers={"Content-Length": "abc"}, data=b"{}")
        assert status == 400
        assert "invalid Content-Length" in text

    def test_invalid_json(self, local_server):
        status, text = post(local_server, data=b"invalid json")
        assert status == 400
        assert "invalid JSON" in text

    def test_non_dict_json(self, local_server):
        status, text = post(local_server, data=json.dumps(["not", "a", "dict"]).encode(), headers={"Content-Type": "application/json"})
        assert status == 400
        assert "JSON payload must be a dictionary" in text

    def test_invalid_messages_type(self, local_server):
        status, text = post(local_server, data=json.dumps({"messages": "not a list"}).encode(), headers={"Content-Type": "application/json"})
        assert status == 400
        assert "messages must be a list" in text

    def test_valid_request(self, local_server, monkeypatch):
        # We expect a 502/503/401 here because it tries to call real upstream client
        # with no auth, but it shouldn't be a 400 validation error
        status, text = post(local_server, data=json.dumps({"messages": [{"role": "user", "content": "hello"}]}).encode(), headers={"Content-Type": "application/json"})
        assert status != 400
        assert "bad request" not in text
