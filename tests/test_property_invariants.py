"""Hypothesis property-based invariant testing suite for gstr-wala."""

import pytest
from hypothesis import given, settings, strategies as st
from scripts.itc_optimizer import optimize_setoff
from scripts.validate_gst_input import STATE_CODES, compute_gstin_checksum, is_valid_gstin


# Strategy for generating valid GSTIN prefixes
@st.composite
def gstin_strategy(draw):
    state_str = draw(st.sampled_from(sorted(list(STATE_CODES.keys()))))
    pan_chars = "".join(draw(st.lists(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), min_size=5, max_size=5)))
    pan_digits = f"{draw(st.integers(min_value=1000, max_value=9999))}"
    pan_last = draw(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    entity_num = draw(st.sampled_from("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    prefix = f"{state_str}{pan_chars}{pan_digits}{pan_last}{entity_num}Z"
    chk = compute_gstin_checksum(prefix)
    return f"{prefix}{chk}"


@settings(max_examples=200)
@given(gstin=gstin_strategy())
def test_gstin_checksum_hypothesis(gstin):
    """Every generated GSTIN with computed checksum MUST pass is_valid_gstin."""
    valid, err = is_valid_gstin(gstin)
    assert valid is True
    assert err is None


@settings(max_examples=300)
@given(
    l_i=st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    l_c=st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    l_s=st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    l_cs=st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    c_i=st.floats(min_value=0.0, max_value=20000000.0, allow_nan=False, allow_infinity=False),
    c_c=st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    c_s=st.floats(min_value=0.0, max_value=10000000.0, allow_nan=False, allow_infinity=False),
    c_cs=st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    rcm_i=st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
    rcm_c=st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
    rcm_s=st.floats(min_value=0.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
    cash_i=st.floats(min_value=0.0, max_value=2000000.0, allow_nan=False, allow_infinity=False),
    cash_c=st.floats(min_value=0.0, max_value=2000000.0, allow_nan=False, allow_infinity=False),
    cash_s=st.floats(min_value=0.0, max_value=2000000.0, allow_nan=False, allow_infinity=False),
)
def test_rule_88a_hypothesis_invariants(l_i, l_c, l_s, l_cs, c_i, c_c, c_s, c_cs, rcm_i, rcm_c, rcm_s, cash_i, cash_c, cash_s):
    """Assimilates extreme boundary floats into Rule 88A optimizer testing invariants."""
    res = optimize_setoff(
        liabilities={"iamt": l_i, "camt": l_c, "samt": l_s, "csamt": l_cs},
        rcm_liabilities={"iamt": rcm_i, "camt": rcm_c, "samt": rcm_s, "csamt": 0.0},
        available_itc={"iamt": c_i, "camt": c_c, "samt": c_s, "csamt": c_cs},
        opening_cash={"iamt": cash_i, "camt": cash_c, "samt": cash_s, "csamt": 0.0}
    )

    m = res["setoff_matrix"]
    cu = res["credit_utilization"]
    cash = res["net_cash_required"]
    rcm = res["rcm_cash_liability"]

    # Invariant 1: Conservation of Tax
    total_outward_tax = round(l_i + l_c + l_s + l_cs, 2)
    total_credit_used = cu["total_credit_utilized"]
    regular_cash_paid = round(
        m["igst_liability"]["paid_by_cash"] +
        m["cgst_liability"]["paid_by_cash"] +
        m["sgst_liability"]["paid_by_cash"] +
        m["cess_liability"]["paid_by_cash"], 2
    )
    assert abs(total_outward_tax - (total_credit_used + regular_cash_paid)) <= 0.05

    # Invariant 2: Non-Negativity
    assert cu["total_credit_utilized"] >= 0.0
    assert cash["total_cash_payable"] >= 0.0

    # Invariant 3: RCM Purity (100% Cash)
    tot_rcm = round(rcm_i + rcm_c + rcm_s, 2)
    assert rcm["total"] == tot_rcm

    # Invariant 4: Rule 88A Exhaustion
    if cu["cgst_credit"]["utilized"] > 0.0 or cu["sgst_credit"]["utilized"] > 0.0:
        assert cu["igst_credit"]["closing_balance"] == 0.0
