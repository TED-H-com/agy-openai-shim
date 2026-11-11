import pytest
from unittest.mock import patch
from agy.models import _normalize_effort, resolve_model_and_effort

def test_normalize_effort():
    assert _normalize_effort(None) is None
    assert _normalize_effort("") is None

    assert _normalize_effort("none") == "low"
    assert _normalize_effort("off") == "low"
    assert _normalize_effort("minimal") == "low"

    assert _normalize_effort("xhigh") == "high"
    assert _normalize_effort("max") == "high"
    assert _normalize_effort("ultra") == "high"

    assert _normalize_effort("low") == "low"
    assert _normalize_effort("medium") == "medium"
    assert _normalize_effort("high") == "high"

    assert _normalize_effort("unknown") == "medium"
    assert _normalize_effort("  MaX  ") == "high"

def test_resolve_model_and_effort_basic():
    # Defaults
    assert resolve_model_and_effort(None) == ("gemini-3.8-flash-medium", "medium")
    assert resolve_model_and_effort("") == ("gemini-3.8-flash-medium", "medium")

    # Explicit Aliases
    assert resolve_model_and_effort("opus") == ("claude-opus-5-5-medium", "medium")
    assert resolve_model_and_effort("pro") == ("gemini-3.1-pro-high", "high") # pro gets medium effort default which maps to high for pro

def test_resolve_model_and_effort_gemini_3_1_pro():
    assert resolve_model_and_effort("gemini-3.1-pro", "low") == ("gemini-3.1-pro-low", "low")
    assert resolve_model_and_effort("gemini-3.1-pro", "medium") == ("gemini-3.1-pro-high", "high")
    assert resolve_model_and_effort("gemini-3.1-pro", "high") == ("gemini-3.1-pro-high", "high")

def test_resolve_model_and_effort_flash():
    assert resolve_model_and_effort("flash", "low") == ("gemini-3.8-flash-low", "low")
    assert resolve_model_and_effort("flash", "high") == ("gemini-3.8-flash-high", "high")

def test_resolve_model_and_effort_suffix_override():
    # Model has suffix, no explicit effort passed
    assert resolve_model_and_effort("gemini-3.8-flash-low") == ("gemini-3.8-flash-low", "low")

    # User passes different effort than model suffix
    assert resolve_model_and_effort("gemini-3.8-flash-low", "high") == ("gemini-3.8-flash-high", "high")

def test_resolve_model_and_effort_non_gemini_suffix_override():
    # Test lines 87-88: model has suffix, is not gemini flash/pro, and effort differs from suffix
    assert resolve_model_and_effort("claude-opus-5-5-medium", "high") == ("claude-opus-5-5-high", "high")
    assert resolve_model_and_effort("gpt-oss-120b-medium", "low") == ("gpt-oss-120b-low", "low")

def test_resolve_model_and_effort_with_hermes_config():
    import sys
    from types import ModuleType

    mock_module = ModuleType("hermes_cli.config")
    mock_module.load_config_readonly = lambda: {"agent": {"reasoning_effort": "ultra"}}
    sys.modules["hermes_cli.config"] = mock_module

    try:
        assert resolve_model_and_effort("flash") == ("gemini-3.8-flash-high", "high")
    finally:
        del sys.modules["hermes_cli.config"]
