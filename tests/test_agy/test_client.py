from unittest.mock import MagicMock, patch
from agy.client import AntigravityClient, _PooledStream
import pytest

def test_resolve_model_and_effort():
    client = AntigravityClient()

    # Defaults
    model, effort = client._resolve_model_and_effort(None, None)
    assert model == "gemini-3.8-flash-medium"
    assert effort == "medium"

    model, effort = client._resolve_model_and_effort("opus", "high")
    assert model == "claude-opus-5-5-high"
    assert effort == "high"

def test_pooled_stream_success():
    account = "mock_account"
    inner_stream = iter(["chunk1", "chunk2"])

    mock_retry = MagicMock()

    with patch("agy.client.agy_pool.mark_success") as mock_mark:
        pooled = _PooledStream(account, inner_stream, mock_retry, "test_model")

        c1 = next(pooled)
        assert c1 == "chunk1"
        mock_mark.assert_called_once_with(account, "test_model")

        c2 = next(pooled)
        assert c2 == "chunk2"

        with pytest.raises(StopIteration):
            next(pooled)

        pooled.close()

def test_pooled_stream_retry_early():
    account1 = "acct1"
    account2 = "acct2"

    # inner stream fails immediately
    def failing_stream():
        raise RuntimeError("auth error")
        yield "never"

    def success_stream():
        yield "chunk2"

    def mock_retry(exc):
        assert str(exc) == "auth error"
        return account2, success_stream()

    with patch("agy.client.agy_pool.mark_success") as mock_mark:
        pooled = _PooledStream(account1, failing_stream(), mock_retry, "test_model")

        c = next(pooled)
        assert c == "chunk2"
        assert pooled.account == account2
        mock_mark.assert_called_once_with(account2, "test_model")

        with pytest.raises(StopIteration):
            next(pooled)

        pooled.close()

def test_pooled_stream_no_retry_after_yield():
    # If the stream yields at least one chunk, it cannot retry
    def mid_fail_stream():
        yield "first chunk"
        raise RuntimeError("midway fail")

    mock_retry = MagicMock()

    with patch("agy.client.agy_pool.mark_success"):
        pooled = _PooledStream("acct1", mid_fail_stream(), mock_retry, "test_model")

        c = next(pooled)
        assert c == "first chunk"

        with pytest.raises(RuntimeError, match="midway fail"):
            next(pooled)

        mock_retry.assert_not_called()
        pooled.close()

def test_client_close():
    client = AntigravityClient()
    mock_proc = MagicMock()
    client._active_processes.add(mock_proc)

    with patch("agy.client.AntigravityClient._terminate_process") as mock_term:
        client.close()
        assert client.is_closed is True
        mock_term.assert_called_once_with(mock_proc)

def test_account_dirs():
    client = AntigravityClient()

    # account is none returns initial isolated defaults
    home, gemini = client._account_dirs(None)
    assert home == client._isolated_home
    assert gemini == client._isolated_gemini_dir

    # With a pool account
    from agy.accounts import Account
    from pathlib import Path
    a1 = Account("test-acct", Path("p1"))

    with patch("agy.client.setup_isolated_home") as mock_setup:
        mock_setup.return_value = (Path("home2"), Path("gemini2"))

        h2, g2 = client._account_dirs(a1)
        assert h2 == Path("home2")
        assert g2 == Path("gemini2")

        # Second call should be cached
        h3, g3 = client._account_dirs(a1)
        assert h3 == Path("home2")
        mock_setup.assert_called_once()

def test_terminate_worker():
    client = AntigravityClient()
    mock_proc = MagicMock()
    client._worker_proc = mock_proc
    client._worker_model = "test-model"

    with patch("agy.client.AntigravityClient._terminate_process") as mock_term:
        client._terminate_worker()
        assert client._worker_proc is None
        assert client._worker_model is None
        mock_term.assert_called_once_with(mock_proc)
