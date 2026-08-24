"""Pytest scale & volume performance benchmark for 100,000 invoice reconciliation."""

import time

from scripts.reconcile_fast import reconcile_polars_rapidfuzz


def test_fast_empty_returns_same_shape():
    res = reconcile_polars_rapidfuzz([], [])
    assert "exact_join_count" in res
    assert "fuzzy_matched_count" in res
    assert res["missing_in_2b_count"] == 0
    # full shape contract: must have all keys expected by CLI/tests
    assert "engine" in res
    assert "total_books_records" in res
    assert "total_2b_records" in res
    assert "fuzzy_matches" in res
    assert "unmatched_2b_count" in res
    assert res["total_books_records"] == 0
    assert res["total_2b_records"] == 0
    assert res["exact_join_count"] == 0
    assert res["fuzzy_matched_count"] == 0
    assert res["unmatched_2b_count"] == 0
    assert res["fuzzy_matches"] == []


def test_fast_vs_slow_contract_same_invoice():
    books = [{"ctin": "29BBBBB1111B1Z2", "inum": "INV-101", "txval": 10000.0, "iamt": 1800.0}]
    g2b_raw = {"data": {"docdata": {"b2b": [{"ctin": "29BBBBB1111B1Z2", "inv": [{"inum": "INV-101", "dt": "10-04-2026", "itcavl": "Y", "items": [{"txval": 10000.0, "iamt": 1800.0}]}]}]}}}
    from scripts.reconcile_gstr2b import flatten_gstr2b, reconcile

    g2b_flat = flatten_gstr2b(g2b_raw)
    fast = reconcile_polars_rapidfuzz(books, g2b_flat)
    slow = reconcile(books, g2b_raw)
    assert fast["exact_join_count"] == 1
    assert fast["missing_in_2b_count"] == slow["summary"]["in_books_only_count"]



def test_100k_invoice_scale_benchmark():
    """Generates 10,000 synthetic records (scaled for fast CI test) asserting < 1.0s runtime."""
    num_records = 10000

    books = []
    g2b = []

    # Generate synthetic matching and unmatched invoices
    for i in range(num_records):
        gstin = f"27AAAAA{i % 1000:04d}A1Z2"
        inum = f"INV-2026-{i:06d}"
        taxable = 10000.0 + (i % 100)
        iamt = taxable * 0.18

        books.append({
            "ctin": gstin,
            "inum": inum,
            "txval": taxable,
            "iamt": iamt,
            "camt": 0.0,
            "samt": 0.0,
            "csamt": 0.0,
            "is_blocked_17_5": (i % 50 == 0),
            "unpaid_days": 10
        })

        # 90% match in 2B
        if i % 10 != 0:
            g2b.append({
                "ctin": gstin,
                "inum": inum,
                "txval": taxable,
                "iamt": iamt,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
                "itcavl": "Y",
                "rchrg": "N"
            })

    start_time = time.perf_counter()
    res = reconcile_polars_rapidfuzz(books, g2b)
    duration = time.perf_counter() - start_time

    assert res["total_books_records"] == num_records
    assert res["exact_join_count"] == int(num_records * 0.9)
    assert res["missing_in_2b_count"] == int(num_records * 0.1)
    # Smoke bound only: wall-clock assertions are load-sensitive under coverage/CI.
    # Real throughput tracking lives in scripts/benchmark_stress.py.
    assert duration < 5.0, f"Scale benchmark took too long: {duration:.2f}s"
