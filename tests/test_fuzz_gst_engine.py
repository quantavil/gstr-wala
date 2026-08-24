"""Pytest integration for property-based fuzzer."""

from scripts.fuzz_gst_engine import run_fuzzer


def test_fuzzer_1000_iterations():
    assert run_fuzzer(1000) is True
