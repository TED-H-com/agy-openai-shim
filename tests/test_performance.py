import pytest
from types import SimpleNamespace
from server import to_plain

def test_to_plain_benchmark(benchmark):
    test_data = SimpleNamespace(
        a=1,
        b=None,
        c=[SimpleNamespace(d=2, e=None, f=[3, None, SimpleNamespace(g=None, h=4)]) for _ in range(100)]
    )
    benchmark(lambda: to_plain(test_data))
