"""Pytest test suite for itc_optimizer.py."""

from scripts.itc_optimizer import optimize_setoff


def test_excess_igst_credit_zero_cash():
    res = optimize_setoff(
        liabilities={"iamt": 10000.0, "camt": 10000.0, "samt": 10000.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={"iamt": 50000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
    )
    assert res["net_cash_required"]["total_cash_payable"] == 0.0
    assert res["credit_utilization"]["igst_credit"]["closing_balance"] == 20000.0
    assert res["challan_pmt06"]["total_challan_amount"] == 0.0


def test_asymmetric_cgst_sgst_deficit_optimization():
    res = optimize_setoff(
        liabilities={"iamt": 10000.0, "camt": 20000.0, "samt": 5000.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={"iamt": 15000.0, "camt": 5000.0, "samt": 15000.0, "csamt": 0.0}
    )
    assert res["setoff_matrix"]["cgst_liability"]["paid_by_igst_credit"] == 5000.0
    assert res["setoff_matrix"]["sgst_liability"]["paid_by_igst_credit"] == 0.0
    assert res["net_cash_required"]["camt"] == 10000.0
    assert res["net_cash_required"]["samt"] == 0.0
    assert res["net_cash_required"]["total_cash_payable"] == 10000.0


def test_rcm_liability_strictly_cash():
    res = optimize_setoff(
        liabilities={"iamt": 10000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
        rcm_liabilities={"iamt": 0.0, "camt": 2500.0, "samt": 2500.0, "csamt": 0.0},
        available_itc={"iamt": 1000000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
    )
    assert res["setoff_matrix"]["igst_liability"]["paid_by_cash"] == 0.0
    assert res["rcm_cash_liability"]["total"] == 5000.0
    assert res["net_cash_required"]["total_cash_payable"] == 5000.0


def test_opening_cash_ledger_offset():
    res = optimize_setoff(
        liabilities={"iamt": 15000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
        rcm_liabilities={},
        available_itc={},
        opening_cash={"iamt": 10000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
    )
    assert res["net_cash_required"]["iamt"] == 15000.0
    assert res["challan_pmt06"]["iamt"] == 5000.0
    assert res["challan_pmt06"]["total_challan_amount"] == 5000.0
    assert res["closing_cash_ledger"]["iamt"] == 0.0
