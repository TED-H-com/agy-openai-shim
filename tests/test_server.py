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



def test_host_header_validation_enabled(test_server, mock_client):
    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hi"}]
    }

    with patch("server.ALLOWED_HOSTS", {"localhost", "127.0.0.1", "::1"}):
        # Invalid host
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Host": "example.com"},
            method="POST"
        )

        try:
            urllib.request.urlopen(req)
            assert False, "Should have failed with 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            data = json.loads(e.read())
            assert data["error"]["message"] == "Invalid Host header"

        # Valid host with IPv6 bracket
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Host": "[::1]:18795"},
            method="POST"
        )

        # We mock client to not actually call API
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content="Hello!"))]
        )
        mock_client.return_value.chat.completions.create.return_value = mock_response

        try:
            with urllib.request.urlopen(req) as response:
                assert response.status == 200
        except urllib.error.HTTPError as e:
            assert e.code != 400

def test_host_header_validation_disabled(test_server, mock_client):
    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hi"}]
    }

    with patch("server.ALLOWED_HOSTS", None):
        # Even 'invalid' host should work if disabled
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Host": "example.com"},
            method="POST"
        )

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content="Hello!"))]
        )
        mock_client.return_value.chat.completions.create.return_value = mock_response

        try:
            with urllib.request.urlopen(req) as response:
                assert response.status == 200
        except urllib.error.HTTPError as e:
            assert e.code != 400

def test_auth_token_validation(test_server, mock_client):
    req_data = {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hi"}]
    }

    with patch("server.AUTH_TOKEN", "secret-token"):
        # No token
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req)
            assert False, "Should have failed with 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
            assert json.loads(e.read())["error"]["message"] == "invalid_api_key"

        # Invalid token
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer bad-token"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req)
            assert False, "Should have failed with 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401

        # Valid token
        req = urllib.request.Request(
            f"{test_server}/v1/chat/completions",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret-token"},
            method="POST"
        )
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content="Hello!"))]
        )
        mock_client.return_value.chat.completions.create.return_value = mock_response

        with urllib.request.urlopen(req) as response:
            assert response.status == 200


def test_body_size_limit(test_server):
    # Use a small limit so we don't trigger BrokenPipeError
    req = urllib.request.Request(
        f"{test_server}/v1/chat/completions",
        data=b"x" * 200,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with patch("server.MAX_BODY_SIZE", 100):
        try:
            urllib.request.urlopen(req)
            assert False, "Should have failed with 413"
        except urllib.error.HTTPError as e:
            assert e.code == 413
            assert json.loads(e.read())["error"]["message"] == "Payload Too Large"
