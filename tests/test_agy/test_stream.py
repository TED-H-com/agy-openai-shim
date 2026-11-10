from unittest.mock import MagicMock
from types import SimpleNamespace
from agy.stream import _counter_delta, _delta_worker_usage, _renumber_tool_deltas, collect_stream_completion

def test_counter_delta():
    usage_data = {"input_tokens": 100}
    baseline = {"input_tokens": 40}

    assert _counter_delta(usage_data, baseline, "input_tokens") == 60
    assert _counter_delta(usage_data, baseline, "missing") == 0
    assert baseline["input_tokens"] == 100 # Should advance baseline

def test_delta_worker_usage():
    usage_data = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    baseline = {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}

    inp, out, tot, cache = _delta_worker_usage(usage_data, baseline)
    assert inp == 60
    assert out == 30
    assert tot == 90
    assert cache == 0

def test_renumber_tool_deltas():
    # parsed_calls, current_index, seen_tool_ids -> updated_calls, next_index
    c1 = SimpleNamespace(index=0, id="old_c1")
    c2 = SimpleNamespace(index=1, id="old_c2")
    c3 = SimpleNamespace(index=2, id="old_c1") # repeat id

    seen = set()
    calls, next_idx = _renumber_tool_deltas([c1, c2, c3], 0, seen)

    assert next_idx == 3
    assert len(calls) == 3
    assert calls[0].index == 0
    assert calls[1].index == 1
    assert calls[2].index == 2
    assert calls[2].id != "old_c1"

class DummyStream:
    def __init__(self, chunks, model="test-model"):
        self.chunks = chunks
        self.model = model
    def __iter__(self):
        return iter(self.chunks)

def test_collect_stream_completion_basic():
    c1 = SimpleNamespace(
        id="conv-1",
        model="test-model",
        choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"), finish_reason=None)]
    )
    c2 = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=" World"), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10)
    )

    stream = DummyStream([c1, c2])
    res = collect_stream_completion(stream)

    assert res.id == "conv-1"
    assert res.model == "test-model"
    assert len(res.choices) == 1
    assert res.choices[0].message.content == "Hello World"
    assert res.choices[0].finish_reason == "stop"
    assert res.usage.prompt_tokens == 10

def test_collect_stream_completion_fallback_tool_parse():
    c1 = SimpleNamespace(
        id="conv-1",
        model="test-model",
        choices=[SimpleNamespace(delta=SimpleNamespace(content="Pre <tool_call>{\"id\": \"t1\", \"function\": {\"name\": \"f\"}}</tool_call>"), finish_reason="stop")],
        usage=None
    )
    stream = DummyStream([c1])
    res = collect_stream_completion(stream)

    assert res.choices[0].finish_reason == "tool_calls"
    assert len(res.choices[0].message.tool_calls) == 1
    assert res.choices[0].message.tool_calls[0].id == "t1"
    assert res.choices[0].message.content == "Pre"
    assert res.usage.prompt_tokens == 0
