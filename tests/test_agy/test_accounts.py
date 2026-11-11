import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
import pytest

from agy.accounts import (
    parse_reset_seconds, _env_float, pool_enabled, accounts_dir, state_dir, strategy,
    token_in_dir, discover_accounts, classify_error, _locked_state, _event, _entry,
    acquire_order, in_cooldown, mark_success, mark_failure, status_lines, Account,
    AgyTransientError, STRATEGY_FILL_FIRST, STRATEGY_ROUND_ROBIN
)

def test_parse_reset_seconds():
    assert parse_reset_seconds("resets in 1s") == 1.0
    assert parse_reset_seconds("Resets in 1m 2s") == 62.0
    assert parse_reset_seconds("resets in 1h 2m 3s") == 3723.0
    assert parse_reset_seconds("resets in 1d 2h") == 93600.0
    assert parse_reset_seconds("no reset here") is None

def test_env_float():
    with patch.dict(os.environ, {"TEST_FLOAT": "12.5", "TEST_BAD": "abc"}):
        assert _env_float("TEST_FLOAT", 1.0) == 12.5
        assert _env_float("TEST_BAD", 1.0) == 1.0
        assert _env_float("TEST_MISSING", 2.0) == 2.0

def test_pool_enabled():
    with patch.dict(os.environ, {"ANTIGRAVITY_POOL": "off"}):
        assert pool_enabled() is False
    with patch.dict(os.environ, {"ANTIGRAVITY_CONFIG_DIR": "/some/dir"}):
        assert pool_enabled() is False
    with patch.dict(os.environ, {}, clear=True):
        assert pool_enabled() is True

def test_strategy():
    with patch.dict(os.environ, {"ANTIGRAVITY_POOL_STRATEGY": "fill_first"}):
        assert strategy() == STRATEGY_FILL_FIRST
    with patch.dict(os.environ, {"ANTIGRAVITY_POOL_STRATEGY": "round_robin"}):
        assert strategy() == STRATEGY_ROUND_ROBIN
    with patch.dict(os.environ, {}, clear=True):
        assert strategy() == STRATEGY_ROUND_ROBIN

def test_classify_error():
    assert classify_error("code 429 quota exceeded") == "quota"
    assert classify_error("authentication failed") == "auth"
    assert classify_error(AgyTransientError("test")) == "transient"
    assert classify_error("antigravity transient error: something") == "transient"
    assert classify_error("other error") is None

@patch("agy.accounts.pool_enabled", return_value=True)
def test_discover_accounts(mock_pool, tmp_path):
    acct1 = tmp_path / "acct1"
    acct1.mkdir()
    acct1_token = acct1 / "antigravity-oauth-token"
    acct1_token.write_text("token1-content-here")

    acct2 = tmp_path / "acct2"
    acct2.mkdir()
    acct2_token = acct2 / "antigravity-oauth-token"
    acct2_token.write_text("short") # Size <= 10

    with patch("agy.accounts.accounts_dir", return_value=tmp_path):
        accounts = discover_accounts()
        assert len(accounts) == 1
        assert accounts[0].name == "acct1"
        assert accounts[0].token_path == acct1_token

@patch("agy.accounts.pool_enabled", return_value=False)
def test_discover_accounts_pool_disabled(mock_pool):
    assert discover_accounts() == []

@patch("agy.accounts.pool_enabled", return_value=True)
def test_discover_accounts_explicit_dirs(mock_pool, tmp_path):
    acct1 = tmp_path / "acct1"
    acct1.mkdir()
    acct1_token = acct1 / "antigravity-oauth-token"
    acct1_token.write_text("token1-content-here")

    with patch.dict(os.environ, {"ANTIGRAVITY_ACCOUNT_DIRS": str(acct1)}):
        accounts = discover_accounts()
        assert len(accounts) == 1
        assert accounts[0].name == "acct1"

def test_acquire_order():
    a1 = Account("a1", Path("p1"))
    a2 = Account("a2", Path("p2"))

    with patch("agy.accounts._locked_state") as mock_locked:
        mock_locked.return_value.__enter__.return_value = {"cursor": 0, "accounts": {}}
        with patch("agy.accounts.strategy", return_value=STRATEGY_ROUND_ROBIN):
            order = acquire_order([a1, a2])
            assert order == [a1, a2]

            mock_locked.return_value.__enter__.return_value = {"cursor": 1, "accounts": {}}
            order = acquire_order([a1, a2])
            assert order == [a2, a1]

def test_acquire_order_empty():
    assert acquire_order([]) == []

def test_mark_success(tmp_path):
    a1 = Account("a1", Path("p1"))
    state_dict = {"accounts": {}}

    with patch("agy.accounts.state_dir", return_value=tmp_path):
        with patch("agy.accounts._locked_state") as mock_locked:
            mock_locked.return_value.__enter__.return_value = state_dict
            mark_success(a1, "model_x")

            assert state_dict["accounts"]["a1"]["served"] == 1
            assert state_dict["accounts"]["a1"]["last_model"] == "model_x"
            assert state_dict["accounts"]["a1"]["cooldown_until"] == 0.0

def test_mark_failure_quota(tmp_path):
    a1 = Account("a1", Path("p1"))
    state_dict = {"accounts": {}}

    with patch("agy.accounts.state_dir", return_value=tmp_path):
        with patch("agy.accounts._locked_state") as mock_locked:
            mock_locked.return_value.__enter__.return_value = state_dict
            mark_failure(a1, "quota", "resets in 10s")

            assert state_dict["accounts"]["a1"]["failures"] == 1
            assert state_dict["accounts"]["a1"]["cooldown_until"] > time.time()

def test_mark_failure_auth(tmp_path):
    a1 = Account("a1", Path("p1"))
    state_dict = {"accounts": {}}

    with patch("agy.accounts.state_dir", return_value=tmp_path):
        with patch("agy.accounts._locked_state") as mock_locked:
            mock_locked.return_value.__enter__.return_value = state_dict
            mark_failure(a1, "auth", "authentication error")

            assert state_dict["accounts"]["a1"]["failures"] == 1
            assert state_dict["accounts"]["a1"]["cooldown_until"] > time.time()

def test_in_cooldown():
    a1 = Account("a1", Path("p1"))

    with patch("agy.accounts._locked_state") as mock_locked:
        mock_locked.return_value.__enter__.return_value = {"accounts": {"a1": {"cooldown_until": time.time() + 100}}}
        assert in_cooldown(a1) is True

        mock_locked.return_value.__enter__.return_value = {"accounts": {"a1": {"cooldown_until": time.time() - 100}}}
        assert in_cooldown(a1) is False

def test_status_lines(tmp_path):
    with patch("agy.accounts.state_dir", return_value=tmp_path):
        lines = status_lines()
        assert any("pool enabled" in line for line in lines)
        assert any("active accounts" in line for line in lines)

def test_locked_state(tmp_path):
    with patch("agy.accounts.state_dir", return_value=tmp_path):
        with _locked_state() as state:
            state["accounts"]["test"] = {"served": 1}

        # Verify persistence
        state_file = tmp_path / "state.json"
        assert state_file.exists()
        persisted = json.loads(state_file.read_text())
        assert persisted["accounts"]["test"]["served"] == 1
