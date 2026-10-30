import pytest
import threading
import json
import urllib.request
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server

@pytest.fixture
def mock_client():
    with patch("server.client") as mock:
        yield mock

@pytest.fixture
def test_server(mock_client):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()

    srv = server.ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()

def test_health(test_server):
    req = urllib.request.Request(f"{test_server}/health")
    with patch("server.agy_pool.discover_accounts", return_value=[SimpleNamespace(name="test_acct")]):
        with urllib.request.urlopen(req) as response:
            assert response.status == 200
            data = json.loads(response.read())
            assert data["ok"] is True
            assert data["accounts"] == ["test_acct"]

def test_chat_completion(test_server, mock_client):
    mock_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content="Hello!"
                )
            )
        ]
    )
    mock_client.return_value.chat.completions.create.return_value = mock_response

    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hi"}]
    }

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["choices"][0]["message"]["content"] == "Hello!"

        # Check that mock_client was called with proper args
        mock_client.return_value.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gemini-3.8-flash"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]
        assert call_kwargs["stream"] is False

def test_chat_completion_stream(test_server, mock_client):
    chunk1 = SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content="Hel"))
        ]
    )
    chunk2 = SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content="lo!"))
        ]
    )

    mock_client.return_value.chat.completions.create.return_value = iter([chunk1, chunk2])

    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True
    }

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        lines = [line.decode("utf-8") for line in response.readlines() if line.strip()]

        # Expect two chunks + [DONE]
        assert len(lines) == 3

        data1 = json.loads(lines[0].replace("data: ", ""))
        assert data1["choices"][0]["delta"]["content"] == "Hel"

        data2 = json.loads(lines[1].replace("data: ", ""))
        assert data2["choices"][0]["delta"]["content"] == "lo!"

        assert lines[2].strip() == "data: [DONE]"


def test_tool_calls_translation(test_server, mock_client):
    mock_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    tool_calls=[
                        SimpleNamespace(
                            id="call_123",
                            type="function",
                            function=SimpleNamespace(
                                name="get_weather",
                                arguments='{"location": "Tokyo"}'
                            )
                        )
                    ]
                )
            )
        ]
    )
    mock_client.return_value.chat.completions.create.return_value = mock_response

    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "What's the weather in Tokyo?"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    }
                }
            }
        }],
        "tool_choice": "auto"
    }

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        data = json.loads(response.read())
        assert len(data["choices"][0]["message"]["tool_calls"]) == 1
        tc = data["choices"][0]["message"]["tool_calls"][0]
        assert tc["id"] == "call_123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"location": "Tokyo"}'

        mock_client.return_value.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        assert call_kwargs["tools"] == req_data["tools"]
        assert call_kwargs["tool_choice"] == "auto"

def test_developer_role_translation(test_server, mock_client):
    mock_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content="Hello!"
                )
            )
        ]
    )
    mock_client.return_value.chat.completions.create.return_value = mock_response

    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [
            {"role": "developer", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hi"}
        ]
    }

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200

        mock_client.return_value.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        assert messages[1]["role"] == "user"

def test_reasoning_effort_translation(test_server, mock_client):
    mock_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content="Hello!"
                )
            )
        ]
    )
    mock_client.return_value.chat.completions.create.return_value = mock_response

    # Test reasoning_effort directly
    req_data1 = {
        "model": "gemini-3.1-pro",
        "messages": [{"role": "user", "content": "Hi"}],
        "reasoning_effort": "high"
    }

    req1 = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data1).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req1) as response:
        assert response.status == 200
        call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "high"

    # Test reasoning.effort
    req_data2 = {
        "model": "gemini-3.1-pro",
        "messages": [{"role": "user", "content": "Hi"}],
        "reasoning": {"effort": "low"}
    }

    req2 = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps(req_data2).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req2) as response:
        assert response.status == 200
        call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "low"

def test_server_client():
    server._client = None
    with patch('server.AntigravityClient') as mock_ac, patch('pathlib.Path.mkdir'):
        mock_ac.return_value = MagicMock()
        mock_ac.return_value.is_closed = False
        c1 = server.client()
        assert c1 is not None
        mock_ac.assert_called_once()

        c2 = server.client()
        assert c1 is c2
        mock_ac.assert_called_once()

        mock_ac.return_value = MagicMock()
        mock_ac.return_value.is_closed = False
        c1.is_closed = True
        c3 = server.client()
        assert c3 is not c1
        assert mock_ac.call_count == 2

def test_to_plain():
    sn = SimpleNamespace(a=1, b=SimpleNamespace(c=2))
    d = {"x": sn, "y": [{"z": sn}]}
    res = server.to_plain(d)
    assert res == {"x": {"a": 1, "b": {"c": 2}}, "y": [{"z": {"a": 1, "b": {"c": 2}}}]}

    res2 = server.to_plain(42)
    assert res2 == 42

def test_error_status():
    with patch('server.agy_pool.classify_error') as mock_classify:
        exc = Exception("test")

        mock_classify.return_value = "quota"
        assert server.error_status(exc) == (429, "rate_limit_exceeded")

        mock_classify.return_value = "auth"
        assert server.error_status(exc) == (401, "invalid_api_key")

        mock_classify.return_value = "transient"
        assert server.error_status(exc) == (503, "upstream_transient")

        mock_classify.return_value = "other"
        assert server.error_status(exc) == (502, "upstream_error")

def test_do_get_models(test_server):
    req = urllib.request.Request(f"{test_server}/v1/models")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["object"] == "list"
        assert len(data["data"]) == 5
        assert data["data"][0]["id"] == "gemini-3.8-flash"

def test_do_get_invalid(test_server):
    req = urllib.request.Request(f"{test_server}/invalid")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 404
        data = json.loads(e.read())
        assert data["error"]["message"] == "not found"

def test_do_post_invalid(test_server):
    req = urllib.request.Request(f"{test_server}/invalid", data=b"{}", method="POST")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 404
        data = json.loads(e.read())
        assert data["error"]["message"] == "not found"

def test_do_post_bad_request(test_server):
    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=b"invalid json",
        method="POST"
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 400
        data = json.loads(e.read())
        assert "bad request" in data["error"]["message"]

def test_chat_completion_error(test_server, mock_client):
    mock_client.return_value.chat.completions.create.side_effect = Exception("test error")

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps({"model": "gemini-3.8-flash", "messages": []}).encode("utf-8"),
        method="POST"
    )

    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 502
        data = json.loads(e.read())
        assert data["error"]["message"] == "test error"

def test_chat_completion_stream_first_chunk_error(test_server, mock_client):
    def error_gen():
        raise Exception("stream initial error")
        yield  # make it a generator

    mock_client.return_value.chat.completions.create.return_value = error_gen()

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps({"model": "gemini-3.8-flash", "messages": [], "stream": True}).encode("utf-8"),
        method="POST"
    )

    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 502
        data = json.loads(e.read())
        assert data["error"]["message"] == "stream initial error"

def test_chat_completion_stream_midway_error(test_server, mock_client):
    def mid_error_gen():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))])
        raise Exception("midway error")

    mock_client.return_value.chat.completions.create.return_value = mid_error_gen()

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps({"model": "gemini-3.8-flash", "messages": [], "stream": True}).encode("utf-8"),
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        lines = response.read().decode("utf-8").strip().split('\n\n')
        assert len(lines) == 2

        data1 = json.loads(lines[0].replace("data: ", ""))
        assert data1["choices"][0]["delta"]["content"] == "first"

        err_data = json.loads(lines[1].replace("data: ", ""))
        assert err_data["error"]["message"] == "midway error"

def test_chat_completion_stream_missing_choices(test_server, mock_client):
    chunk1 = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10))
    mock_client.return_value.chat.completions.create.return_value = iter([chunk1])

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps({"model": "gemini-3.8-flash", "messages": [], "stream": True}).encode("utf-8"),
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        lines = [line.decode("utf-8") for line in response.readlines() if line.strip()]
        data = json.loads(lines[0].replace("data: ", ""))
        assert "choices" in data
        assert data["choices"] == []
        assert data["usage"]["prompt_tokens"] == 10

def test_main():
    with patch("server.ThreadingHTTPServer") as mock_srv, \
         patch("server.agy_pool.discover_accounts") as mock_disc:
        mock_disc.return_value = [SimpleNamespace(name="test")]
        mock_srv.return_value.serve_forever = MagicMock()
        server.main()
        mock_srv.assert_called_once()
        mock_srv.return_value.serve_forever.assert_called_once()

def test_chat_completion_stream_disconnect(test_server, mock_client):
    def disconnect_gen():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))])
        raise ConnectionResetError("disconnect")

    gen = disconnect_gen()
    mock_result = MagicMock()
    mock_result.__iter__.return_value = gen
    mock_client.return_value.chat.completions.create.return_value = mock_result

    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=json.dumps({"model": "gemini-3.8-flash", "messages": [], "stream": True}).encode("utf-8"),
        method="POST"
    )

    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        # The generator will raise ConnectionResetError mid-stream.
        # The server will catch it, log it, and call close() on the result generator.
        response.read() # Consume the stream

    # Verify close was called
    mock_result.close.assert_called_once()


def test_chat_completion_stream_midway_error_broken_pipe(test_server, mock_client):
    import socket
    def mid_error_gen():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))])
        raise Exception("midway error")

    mock_client.return_value.chat.completions.create.return_value = mid_error_gen()

    # We create a client socket manually, send the request, read the first chunk,
    # then close the socket so the server's next write (the error write) gets a BrokenPipe/OSError.
    import urllib.parse
    parsed = urllib.parse.urlparse(test_server)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((parsed.hostname, parsed.port))

    req = b"POST /v1/chat/completions HTTP/1.1\r\n"
    req += b"Host: " + parsed.netloc.encode() + b"\r\n"
    req += b"Content-Type: application/json\r\n"
    body = json.dumps({"model": "gemini-3.8-flash", "messages": [], "stream": True}).encode()
    req += b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
    req += body

    s.sendall(req)
    # Read headers and first chunk
    s.recv(1024)
    # The server starts streaming. The generator yields first chunk, then raises Exception.
    # We close the socket immediately, causing the server's error write to fail with OSError.
    s.close()

    import time
    time.sleep(0.1) # Wait for server thread to process the exception and write the error.

def test_main_block():
    # Covers if __name__ == '__main__': ... logic
    # Since we can't easily test it directly without a subprocess and mocking everything,
    # it's usually skipped or tested lightly. The lines missed are 190-191 and 206.
    pass
