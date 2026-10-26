import pytest
import time
from types import SimpleNamespace
import json
import sys
import os
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server
from http.server import BaseHTTPRequestHandler

def test_benchmark_to_plain():
    chunk = SimpleNamespace(
        id="chatcmpl-123",
        object="chat.completion.chunk",
        created=1677652288,
        model="gpt-3.5-turbo-0301",
        choices=[
            SimpleNamespace(
                index=0,
                delta=SimpleNamespace(role="assistant", content="Hello", tool_calls=None),
                logprobs=None,
                finish_reason=None
            )
        ] * 10
    )

    t0 = time.time()
    for _ in range(1000):
        res = server.to_plain(chunk)
    dt = time.time() - t0

    assert res["id"] == "chatcmpl-123"
    assert "tool_calls" not in res["choices"][0]["delta"]
    print(f"\nto_plain serialization: dt={dt:.4f}s")


class DummyHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.request = request
        self.client_address = client_address
        self.server = server
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO()
        self.close_connection = True
        self.requestline = "GET / HTTP/1.1"
    def log_message(self, format, *args):
        pass
    def log_request(self, code='-', size='-'):
        pass

def test_benchmark_header_serialization():
    class DummyServer:
        pass

    handler = DummyHandler(None, ("127.0.0.1", 12345), DummyServer())
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"

    t0 = time.time()
    for _ in range(10000):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.seek(0)
        handler.wfile.truncate()
    dt_std = time.time() - t0

    t1 = time.time()
    for _ in range(10000):
        handler.wfile.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: close\r\n\r\n"
        )
        handler.wfile.seek(0)
        handler.wfile.truncate()
    dt_opt = time.time() - t1

    print(f"\nHeader serialization: std={dt_std:.4f}s opt={dt_opt:.4f}s")
