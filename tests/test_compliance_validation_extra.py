"""Extra coverage for compliance_radar validation (Plan 12)."""

import json
from unittest.mock import patch

from scripts.compliance_radar import (
    _validate_patch,
    apply_compliance_patch,
    load_rules_manifest,
    print_status,
    save_rules_manifest,
)


def test_validate_patch_valid_minimal():
    assert _validate_patch({"b2cl_threshold": {"value": 100000.0}}) is True
    assert _validate_patch({"interest_rates": {"section_50_1_net_cash_p_a": 0.18}}) is True
    assert _validate_patch({"late_fee_caps": {"nil_return_daily_cgst": 10.0}}) is True
    assert _validate_patch({"statutory_gst_rates": [0.0, 5.0, 18.0]}) is True
    assert _validate_patch({"table_12_hsn_b2b_b2c_split": {"mandatory": True}}) is True


def test_validate_patch_rejects_unknown_top_key(capsys):
    assert _validate_patch({"unknown_key": {}}) is False
    assert "not allowlisted" in capsys.readouterr().out


def test_validate_b2cl_bounds():
    assert _validate_patch({"b2cl_threshold": {"value": 1000.0}}) is False  # below 50k
    assert _validate_patch({"b2cl_threshold": {"value": 600000.0}}) is False  # above 500k
    assert _validate_patch({"b2cl_threshold": {"value": True}}) is False  # bool
    assert _validate_patch({"b2cl_threshold": "not-a-dict"}) is False
    assert _validate_patch({"b2cl_threshold": {"unknown_sub": 100000.0}}) is False


def test_validate_interest_rates():
    assert _validate_patch({"interest_rates": {"section_50_1_net_cash_p_a": 0.5}}) is False  # >0.30
    assert _validate_patch({"interest_rates": {"section_50_1_net_cash_p_a": float("inf")}}) is False
    assert _validate_patch({"interest_rates": {"bad_key": 0.18}}) is False
    assert _validate_patch({"interest_rates": "not-dict"}) is False


def test_validate_late_fee_caps():
    assert _validate_patch({"late_fee_caps": {"nil_return_daily_cgst": float("nan")}}) is False
    assert _validate_patch({"late_fee_caps": {"nil_return_daily_cgst": True}}) is False
    assert _validate_patch({"late_fee_caps": {"unknown": 10.0}}) is False


def test_validate_drc():
    # percentage >100
    assert _validate_patch({"drc_surveillance_thresholds": {"drc_01b_rule_88c": {"percentage_threshold": 150, "amount_threshold": 1000}}}) is False
    # amount <=0
    assert _validate_patch({"drc_surveillance_thresholds": {"drc_01b_rule_88c": {"percentage_threshold": 10, "amount_threshold": 0}}}) is False
    # description must be str
    assert _validate_patch({"drc_surveillance_thresholds": {"drc_01b_rule_88c": {"description": 123}}}) is False
    # unknown outer key
    assert _validate_patch({"drc_surveillance_thresholds": {"unknown_outer": {"percentage_threshold": 10}}}) is False
    # unknown inner key
    assert _validate_patch({"drc_surveillance_thresholds": {"drc_01b_rule_88c": {"unknown_inner": 10}}}) is False
    # not dict
    assert _validate_patch({"drc_surveillance_thresholds": "bad"}) is False
    assert _validate_patch({"drc_surveillance_thresholds": {"drc_01b_rule_88c": "bad"}}) is False


def test_validate_gst_rates():
    assert _validate_patch({"statutory_gst_rates": "not-list"}) is False
    assert _validate_patch({"statutory_gst_rates": [True]}) is False
    assert _validate_patch({"statutory_gst_rates": [float("inf")]}) is False
    assert _validate_patch({"statutory_gst_rates": [0.0, 18.0]}) is True


def test_validate_table12():
    assert _validate_patch({"table_12_hsn_b2b_b2c_split": {"mandatory": "yes"}}) is False
    assert _validate_patch({"table_12_hsn_b2b_b2c_split": {"unknown": True}}) is False
    assert _validate_patch({"table_12_hsn_b2b_b2c_split": "bad"}) is False


def test_apply_patch_invalid_rejected(tmp_path):
    # patch with unknown top key should be filtered; but invalid statutory_rules should be rejected
    bad_patch = tmp_path / "bad.json"
    bad_patch.write_text(json.dumps({"statutory_rules": {"b2cl_threshold": {"value": 1.0}}}))
    # value 1.0 is out of bounds -> _validate_patch False -> apply returns False, manifest unchanged
    before = load_rules_manifest()
    result = apply_compliance_patch(str(bad_patch))
    assert result is False
    after = load_rules_manifest()
    assert before == after


def test_apply_patch_valid_mocked(tmp_path):
    # Valid patch with mocked verification success
    good_patch = tmp_path / "good.json"
    good_patch.write_text(json.dumps({
        "statutory_rules": {"b2cl_threshold": {"value": 100000.0}},
        "manifest_version": "2099.9.9"
    }))
    before = load_rules_manifest()
    try:
        with patch("scripts.compliance_radar.run_self_verification", return_value=True):
            result = apply_compliance_patch(str(good_patch))
            assert result is True
    finally:
        # Cleanup: restore original manifest (apply committed, so we restore)
        save_rules_manifest(before)
    assert load_rules_manifest() == before


def test_apply_patch_rollback_on_verify_fail(tmp_path):
    good_patch = tmp_path / "good2.json"
    good_patch.write_text(json.dumps({
        "statutory_rules": {"b2cl_threshold": {"value": 150000.0}},
    }))
    before = load_rules_manifest()
    with patch("scripts.compliance_radar.run_self_verification", return_value=False):
        result = apply_compliance_patch(str(good_patch))
        assert result is False
    after = load_rules_manifest()
    assert after == before


def test_apply_patch_missing_file():
    assert apply_compliance_patch("/tmp/nonexistent_patch_12345.json") is False


def test_print_status(capsys):
    print_status()
    out = capsys.readouterr().out
    assert "STATUTORY COMPLIANCE MANIFEST" in out
    assert "B2CL Threshold" in out


def test_load_save_roundtrip(tmp_path):
    data = load_rules_manifest()
    # save to tmp via direct function
    tmp_manifest = tmp_path / "manifest.json"
    with patch("scripts.compliance_radar.MANIFEST_PATH", str(tmp_manifest)):
        save_rules_manifest(data)
        assert tmp_manifest.exists()
        loaded = json.loads(tmp_manifest.read_text())
        assert loaded["manifest_version"] == data["manifest_version"]
