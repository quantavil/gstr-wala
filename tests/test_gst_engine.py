"""Pytest test suite for gst_engine.py."""

import pytest
from scripts.gst_engine import (
    compute,
    compute_statutory_interest,
    compute_statutory_late_fee,
)


def test_b2b_vs_b2cl_vs_b2cs_splitting():
    data = {
        "gstin": "27AAAAA0000A1Z2",  # Maharashtra (27)
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-001",
                "idt": "10-04-2026",
                "pos": "29",  # Karnataka
                "ctin": "29BBBBB1111B1Z2",
                "val": 59000.0,
                "items": [{"txval": 50000.0, "rt": 18.0, "iamt": 9000.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 5}]
            },
            {
                "inum": "INV-002",
                "idt": "12-04-2026",
                "pos": "29",  # Karnataka (Inter-state unregistered > ₹1L)
                "val": 177000.0,
                "items": [{"txval": 150000.0, "rt": 18.0, "iamt": 27000.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 10}]
            },
            {
                "inum": "INV-003",
                "idt": "14-04-2026",
                "pos": "29",  # Karnataka (Inter-state unregistered <= ₹1L)
                "val": 94400.0,
                "items": [{"txval": 80000.0, "rt": 18.0, "iamt": 14400.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 8}]
            },
            {
                "inum": "INV-004",
                "idt": "15-04-2026",
                "pos": "27",  # Maharashtra (Intra-state unregistered)
                "val": 354000.0,
                "items": [{"txval": 300000.0, "rt": 18.0, "camt": 27000.0, "samt": 27000.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 30}]
            }
        ]
    }

    res = compute(data)
    assert res["summary"]["b2b_count"] == 1
    assert res["summary"]["b2cl_count"] == 1
    assert res["summary"]["b2cs_lines"] == 2

    # Check Table 12 HSN separation: B2B vs B2C
    hsn_list = res["table_12_hsn"]
    b2b_hsn = [h for h in hsn_list if h["source_type"] == "B2B"]
    b2c_hsn = [h for h in hsn_list if h["source_type"] == "B2C"]

    assert len(b2b_hsn) == 1
    assert b2b_hsn[0]["qty"] == 5
    assert b2b_hsn[0]["txval"] == 50000.0

    assert len(b2c_hsn) == 1
    assert b2c_hsn[0]["qty"] == 48  # 10 + 8 + 30
    assert b2c_hsn[0]["txval"] == 530000.0  # 150k + 80k + 300k


def test_statutory_interest_on_delay():
    res = compute_statutory_interest(
        net_cash_liability=100000.0,
        due_date_str="20-05-2026",
        filing_date_str="19-06-2026"
    )
    assert res["delay_days"] == 30
    assert pytest.approx(res["interest_amount"], 0.01) == 1479.45


def test_statutory_interest_on_time_is_zero():
    res = compute_statutory_interest(
        net_cash_liability=100000.0,
        due_date_str="20-05-2026",
        filing_date_str="20-05-2026"
    )
    assert res["delay_days"] == 0
    assert res["interest_amount"] == 0.0


def test_late_fee_turnover_caps():
    res_small = compute_statutory_late_fee(
        is_nil_return=False,
        turnover_slab="upto_1.5cr",
        due_date_str="20-05-2026",
        filing_date_str="28-08-2026"  # 100 days
    )
    assert res_small["total_late_fee"] == 2000.0
    assert res_small["capped"] is True

    res_nil = compute_statutory_late_fee(
        is_nil_return=True,
        turnover_slab="upto_1.5cr",
        due_date_str="20-05-2026",
        filing_date_str="28-08-2026"  # 100 days
    )
    assert res_nil["total_late_fee"] == 500.0
    assert res_nil["capped"] is True
