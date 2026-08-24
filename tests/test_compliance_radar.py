"""Pytest suite for the Agentic Compliance Radar."""

import json
import os
import pytest
from scripts.compliance_radar import load_rules_manifest
from scripts.constants import B2CL_THRESHOLD, VALID_RATES
from scripts.bridge_gstr1_to_gstr3b import check_drc_mismatch_risks


def test_rules_manifest_structure():
    manifest = load_rules_manifest()
    assert "statutory_rules" in manifest
    assert "manifest_version" in manifest

    rules = manifest["statutory_rules"]
    assert rules["b2cl_threshold"]["value"] == 100000.0
    assert rules["table_12_hsn_b2b_b2c_split"]["mandatory"] is True
    assert rules["interest_rates"]["section_50_1_net_cash_p_a"] == 0.18
    assert rules["late_fee_caps"]["upto_1.5cr_max_cap_total"] == 2000.0


def test_constants_match_manifest():
    with open("config/rules_manifest.json") as f:
        m = json.load(f)
    assert B2CL_THRESHOLD == m["statutory_rules"]["b2cl_threshold"]["value"]
    # also VALID_RATES matches manifest statutory_gst_rates
    assert VALID_RATES == set(m["statutory_rules"]["statutory_gst_rates"])


def test_drc_uses_manifest_not_hardcode():
    # patch manifest in memory by monkeypatching constants values? Instead test current thresholds are those from manifest by importing them
    from scripts.constants import DRC_01B_PCT, DRC_01B_AMT, DRC_01C_PCT, DRC_01C_AMT

    with open("config/rules_manifest.json") as f:
        m = json.load(f)
    assert DRC_01B_PCT == m["statutory_rules"]["drc_surveillance_thresholds"]["drc_01b_rule_88c"]["percentage_threshold"]
    assert DRC_01B_AMT == m["statutory_rules"]["drc_surveillance_thresholds"]["drc_01b_rule_88c"]["amount_threshold"]
    assert DRC_01C_PCT == m["statutory_rules"]["drc_surveillance_thresholds"]["drc_01c_rule_88d"]["percentage_threshold"]
    assert DRC_01C_AMT == m["statutory_rules"]["drc_surveillance_thresholds"]["drc_01c_rule_88d"]["amount_threshold"]
    # Also check bridge uses them: variance exactly at threshold should NOT flag
    g1_summary = {"total_tax": 10000000.0}
    g3b_data = {
        "outward_supplies": {
            "taxable": {"iamt": 4000000.0, "camt": 2000000.0, "samt": 2000000.0, "csamt": 0.0},
            "zero_rated": {"iamt": 0.0, "csamt": 0.0},
        },
        "itc": {
            "available": {"all_other": {"iamt": 50000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}},
            "reversed": {"permanent_17_5_rules": {}, "temporary_others": {}},
        },
    }
    res = check_drc_mismatch_risks(g1_summary, g3b_data, 40000.0)
    assert res["drc_01b_liability_mismatch"]["risk_flag"] is False
    # exact amount threshold edge for DRC-01C: diff exactly at 100k should NOT flag (requires >)
    g1_summary2 = {"total_tax": 0.0}
    g3b_data2 = {
        "outward_supplies": {"taxable": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}, "zero_rated": {"iamt": 0.0, "csamt": 0.0}},
        "itc": {
            "available": {"all_other": {"iamt": 200000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}},
            "reversed": {"permanent_17_5_rules": {}, "temporary_others": {}},
        },
    }
    # gstr2b_total_itc = 100000 => diff =100000 exactly at threshold, pct =100% >10% but amount not > => False
    res2 = check_drc_mismatch_risks(g1_summary2, g3b_data2, 100000.0)
    assert res2["drc_01c_itc_mismatch"]["risk_flag"] is False
