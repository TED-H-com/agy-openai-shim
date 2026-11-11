import os
import shutil
import signal
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from agy.process import (
    resolve_agy_command, resolve_real_token_path, is_authenticated,
    setup_isolated_home, build_child_env, _check_early_quota_error,
    _is_existing_file, _kill_process_tree, terminate_process
)

def test_is_existing_file(tmp_path):
    f = tmp_path / "test.txt"
    assert not _is_existing_file(f)
    f.write_text("hello")
    assert _is_existing_file(f)

@patch("agy.process._is_existing_file", return_value=True)
@patch("os.access", return_value=True)
def test_resolve_agy_command_env_var(mock_access, mock_exists):
    with patch.dict(os.environ, {"ANTIGRAVITY_COMMAND": "/custom/agy"}):
        assert resolve_agy_command() == "/custom/agy"

@patch("shutil.which", return_value="/usr/bin/agy")
def test_resolve_agy_command_which(mock_which):
    with patch.dict(os.environ, clear=True):
        assert resolve_agy_command() == "/usr/bin/agy"

@patch("shutil.which", return_value=None)
@patch("agy.process._is_existing_file")
@patch("os.access", return_value=True)
def test_resolve_agy_command_fallback(mock_access, mock_exists, mock_which):
    def mock_exists_side_effect(path):
        return str(path).endswith("agy")
    mock_exists.side_effect = mock_exists_side_effect
    with patch.dict(os.environ, clear=True):
        cmd = resolve_agy_command()
        assert cmd.endswith("agy")
        assert "bin" in cmd

@patch("agy.process._is_existing_file")
def test_resolve_real_token_path_explicit(mock_exists):
    def mock_exists_side_effect(path):
        return "antigravity-oauth-token" in str(path)
    mock_exists.side_effect = mock_exists_side_effect

    with patch.dict(os.environ, {"ANTIGRAVITY_CONFIG_DIR": "/custom"}):
        res = resolve_real_token_path()
        assert res is not None
        assert str(res) == "/custom/antigravity-oauth-token"

@patch("agy.process._is_existing_file")
def test_resolve_real_token_path_implicit(mock_exists):
    mock_exists.return_value = True
    with patch.dict(os.environ, clear=True):
        res = resolve_real_token_path()
        assert res is not None

@patch("agy.process.resolve_real_token_path")
def test_is_authenticated(mock_resolve, tmp_path):
    mock_resolve.return_value = None
    assert not is_authenticated()

    token = tmp_path / "token"
    token.write_text("short")
    mock_resolve.return_value = token
    assert not is_authenticated() # <= 10 bytes

    token.write_text("long enough token content here")
    assert is_authenticated()

def test_build_child_env():
    env = build_child_env("/mock/home")
    assert env["HOME"] == "/mock/home"
    assert env["USERPROFILE"] == "/mock/home"

def test_check_early_quota_error(tmp_path):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    log_file = log_dir / "cli-2023.log"

    assert _check_early_quota_error(str(tmp_path)) is None

    log_file.write_text("Normal log line\nRESOURCE_EXHAUSTED Individual quota reached")
    err = _check_early_quota_error(str(tmp_path))
    assert "RESOURCE_EXHAUSTED" in err

def test_terminate_process():
    proc = MagicMock()
    proc.terminate.side_effect = Exception("failed")
    proc.poll.return_value = None

    with patch("agy.process._kill_process_tree") as mock_kill:
        terminate_process(proc)
        mock_kill.assert_called_once_with(proc)

def test_setup_isolated_home(tmp_path):
    real_token = tmp_path / "real-token"
    real_token.write_text("hello")

    cwd = tmp_path / "cwd"
    home, gemini = setup_isolated_home(cwd, real_token)

    assert home.is_dir()
    assert gemini.is_dir()

    linked_token = gemini / "real-token"
    assert linked_token.exists()
