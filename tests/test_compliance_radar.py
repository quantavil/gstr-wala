"""Pytest suite for the Agentic Compliance Radar."""

import os
import pytest
from scripts.compliance_radar import load_rules_manifest


def test_rules_manifest_structure():
    manifest = load_rules_manifest()
    assert "statutory_rules" in manifest
    assert "manifest_version" in manifest

    rules = manifest["statutory_rules"]
    assert rules["b2cl_threshold"]["value"] == 100000.0
    assert rules["table_12_hsn_b2b_b2c_split"]["mandatory"] is True
    assert rules["interest_rates"]["section_50_1_net_cash_p_a"] == 0.18
    assert rules["late_fee_caps"]["upto_1.5cr_max_cap_total"] == 2000.0
