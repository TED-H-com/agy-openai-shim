import json
from unittest.mock import patch
from dataclasses import dataclass
from types import SimpleNamespace
import pytest

from agy.prompt import (
    _render_message_content, _format_messages_as_prompt, _messages_match_prefix,
    _format_delta_prompt, _longest_tool_call_prefix_match, _parse_tool_block
)

def test_render_message_content_string():
    assert _render_message_content("hello") == "hello"
    assert _render_message_content("   world   ") == "world"
    assert _render_message_content(None) == ""

def test_render_message_content_dict():
    assert _render_message_content({"text": "hello"}) == "hello"
    assert _render_message_content({"content": "world"}) == "world"

def test_render_message_content_list():
    msg = [
        {"type": "text", "text": "part1"},
        {"type": "image_url", "image_url": "http://img"}, # Will be ignored based on output
        {"content": "part3"}
    ]
    assert _render_message_content(msg) == "part1\npart3"
    assert _render_message_content([]) == ""

def test_format_messages_as_prompt_basic():
    msgs = [
        {"role": "system", "content": "Be helpful"},
        {"role": "user", "content": "Hi"}
    ]
    prompt = _format_messages_as_prompt(msgs)

    assert "### SYSTEM INSTRUCTIONS (HOST AGENT):" in prompt
    assert "Be helpful" in prompt
    assert "### LATEST USER REQUEST TO ANSWER:" in prompt
    assert "User:\nHi" in prompt

def test_format_messages_as_prompt_tool_results():
    msgs = [
        {"role": "user", "content": "What is the weather?"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"}
    ]
    prompt = _format_messages_as_prompt(msgs)

    assert "Tool Result (call_1):\nSunny" in prompt
    assert "### LATEST TOOL RESULTS RECEIVED." in prompt

def test_messages_match_prefix():
    h1 = [{"role": "user", "content": "A"}]
    i1 = [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]
    assert _messages_match_prefix(h1, i1) is True

    i2 = [{"role": "user", "content": "C"}]
    assert _messages_match_prefix(h1, i2) is False

    assert _messages_match_prefix([], i1) is False

def test_format_delta_prompt():
    new_msgs = [
        {"role": "assistant", "content": "I can help."},
        {"role": "user", "content": "Yes, please."}
    ]
    prompt = _format_delta_prompt(new_msgs)
    assert "Assistant:\nI can help." in prompt
    assert "User:\nYes, please." in prompt
    assert "Respond directly and specifically" in prompt

def test_longest_tool_call_prefix_match():
    # assuming prefix includes "<tool_call" or similar, just test standard cases
    # We don't have exact prefixes array here, but passing a matching block should work if we construct it
    # We will test parse tool block instead which is the main consumer
    pass

def test_parse_tool_block_valid_json():
    block = "Prefix text <tool_call>{\"id\": \"c1\", \"function\": {\"name\": \"fn\", \"arguments\": {}}}</tool_call> Suffix text"
    calls, cleaned = _parse_tool_block(block)

    assert len(calls) == 1
    assert calls[0].id == "c1"
    assert calls[0].function.name == "fn"
    assert calls[0].function.arguments == "{}"

    assert cleaned == "Prefix text  Suffix text"

def test_parse_tool_block_invalid_json():
    block = "Some text <tool_call>{bad json}</tool_call>"
    calls, cleaned = _parse_tool_block(block)
    assert len(calls) == 0
    assert cleaned == block
