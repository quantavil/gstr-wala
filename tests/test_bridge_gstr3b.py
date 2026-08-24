"""Task 8 robustness tests: due-date, dispatch, remainder 1p."""
from scripts.bridge_gstr1_to_gstr3b import derive_gstr3b_due_date


def test_due_date_rejects_invalid_period():
    assert derive_gstr3b_due_date("132026") == ""  # invalid mm 13
    assert derive_gstr3b_due_date("002026") == ""
    assert derive_gstr3b_due_date("") == ""
    assert derive_gstr3b_due_date("042026") == "20-05-2026"
    assert derive_gstr3b_due_date("122026") == "20-01-2027"
    # additional boundaries
    assert derive_gstr3b_due_date("042019") == ""
    assert derive_gstr3b_due_date("042036") == ""


def test_gst_engine_dispatch_not_misclassify():
    import pytest

    from scripts.gst_engine import compute

    data = {
        "gstin": "27ABCDE1234F1Z5",
        "ret_period": "042026",
        "outward_supplies": {"taxable": {"txval": 100.0, "iamt": 18.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}},
    }
    res = compute(data)
    assert res["return_type"] == "GSTR-3B"

    # ambiguous: both GSTR-1 and GSTR-3B keys present -> must raise ValueError
    data2 = {
        "gstin": "27ABCDE1234F1Z5",
        "ret_period": "042026",
        "fp": "042026",
        "outward_supplies": {"taxable": {"txval": 100.0, "iamt": 18.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}},
        "invoices": [{"inum": "INV-1", "idt": "10-04-2026", "pos": "27", "items": [{"txval": 100.0, "iamt": 18.0}]}],
    }
    with pytest.raises(ValueError, match="ambiguous payload"):
        compute(data2)


def test_interest_remainder_sum():
    from scripts.itc_optimizer import optimize_setoff

    res = optimize_setoff(
        liabilities={"iamt": 100.0, "camt": 100.0, "samt": 100.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={},
        opening_cash={},
        interest={"interest_amount": 10.03},
    )
    tot = res["interest_liability"]["total"]
    assert abs(tot - 10.03) < 0.01
    # ensure no negative cess
    assert res["interest_liability"]["csamt"] >= 0

    # edge where rounding would overshoot (0.05 would previously give 0.06)
    res2 = optimize_setoff(
        liabilities={"iamt": 100.0, "camt": 100.0, "samt": 100.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={},
        opening_cash={},
        interest={"interest_amount": 0.05},
    )
    assert abs(res2["interest_liability"]["total"] - 0.05) < 0.01
    assert res2["interest_liability"]["csamt"] >= 0

    res3 = optimize_setoff(
        liabilities={"iamt": 100.0, "camt": 100.0, "samt": 100.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={},
        opening_cash={},
        interest={"interest_amount": 0.08},
    )
    assert abs(res3["interest_liability"]["total"] - 0.08) < 0.01
    assert res3["interest_liability"]["csamt"] >= 0
