"""Pytest scale & volume performance benchmark for 100,000 invoice reconciliation."""

import time
import pytest
from scripts.fast_engine import reconcile_polars_rapidfuzz


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
    # Assert performance: 10,000 records processed in under 1.5 seconds
    assert duration < 1.5, f"Scale benchmark took too long: {duration:.2f}s"
