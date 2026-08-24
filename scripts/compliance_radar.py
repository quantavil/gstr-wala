#!/usr/bin/env python3
"""Agentic Compliance Radar for gstr-wala.

Monitors, validates, and autonomously applies statutory rule updates (e.g. rate changes,
threshold revisions, late fee caps, DRC triggers) from CBIC notifications & GSTN advisories.
"""

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

MANIFEST_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "rules_manifest.json"))


def load_rules_manifest() -> Dict[str, Any]:
    """Loads active statutory rules manifest."""
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"Rules manifest not found at: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_rules_manifest(data: Dict[str, Any]):
    """Saves updated statutory rules manifest."""
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    dir_name = os.path.dirname(MANIFEST_PATH) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(data, tmp, indent=2)
        os.replace(tmp_path, MANIFEST_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def run_self_verification() -> bool:
    """Runs core test suite to verify that statutory rules do not violate invariants."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Run full test suite avoiding recursive invocation of self-test
    import shutil

    if shutil.which("uv"):
        cmd = ["uv", "run", "pytest", "tests/", "-k", "not test_compliance_radar", "-q"]
    else:
        cmd = [sys.executable, "-m", "pytest", "tests/", "-k", "not test_compliance_radar", "-q"]
    try:
        res = subprocess.run(cmd, cwd=root_dir, capture_output=True, text=True, timeout=300)
        return res.returncode == 0
    except Exception as e:
        print(f"Verification error: {e}")
        return False


def apply_compliance_patch(patch_file: str) -> bool:
    """Agentically applies and tests a statutory compliance patch."""
    if not os.path.exists(patch_file):
        print(f"Error: Patch file '{patch_file}' not found.")
        return False

    try:
        with open(patch_file, "r", encoding="utf-8") as f:
            patch_data = json.load(f)
    except Exception as e:
        print(f"Error: failed to load patch '{patch_file}': {e}")
        return False

    try:
        current_manifest = load_rules_manifest()
    except Exception as e:
        print(f"Error: failed to load rules manifest: {e}")
        return False
    backup_manifest = copy.deepcopy(current_manifest)

    print("=" * 70)
    print(" AGENTIC COMPLIANCE RADAR: APPLYING STATUTORY RULE UPDATE")
    print("=" * 70)
    print(f"Incoming Patch: {patch_data.get('patch_id', 'STATUTORY_DELTA')} (Authority: {patch_data.get('authority', 'CBIC/GSTN')})")

    def deep_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                deep_update(d[k], v)
            else:
                d[k] = v

    # Strict nested allowlist + per-field bounds
    _ALLOWED_STATUTORY = {
        "b2cl_threshold": {"value": (50000, 500000)},
        "interest_rates": {
            "section_50_1_net_cash_p_a": (0.0, 0.30),
            "section_50_3_wrong_avail_utilized_p_a": (0.0, 0.30),
        },
        "late_fee_caps": {
            "nil_return_daily_cgst": (0, float("inf")),
            "nil_return_daily_sgst": (0, float("inf")),
            "nil_return_max_cap_total": (0, float("inf")),
            "upto_1.5cr_daily_cgst": (0, float("inf")),
            "upto_1.5cr_daily_sgst": (0, float("inf")),
            "upto_1.5cr_max_cap_total": (0, float("inf")),
            "slab_1.5cr_to_5cr_max_cap_total": (0, float("inf")),
            "above_5cr_max_cap_total": (0, float("inf")),
        },
        "drc_surveillance_thresholds": None,
        "statutory_gst_rates": None,
        "table_12_hsn_b2b_b2c_split": {"mandatory": None},
    }

    def _validate_patch(stat_rules: dict) -> bool:
        for key, val in stat_rules.items():
            if key not in _ALLOWED_STATUTORY:
                print(f"Error: statutory_rules key '{key}' not allowlisted — abort")
                return False
            allowed = _ALLOWED_STATUTORY[key]
            if key == "b2cl_threshold":
                if not isinstance(val, dict):
                    print("Error: b2cl_threshold must be object — abort")
                    return False
                for sub_k, sub_v in val.items():
                    if sub_k not in allowed:
                        print(f"Error: b2cl_threshold subkey '{sub_k}' not allowlisted — abort")
                        return False
                    lo, hi = allowed[sub_k]
                    if isinstance(sub_v, bool) or not isinstance(sub_v, (int, float)) or not math.isfinite(sub_v):
                        print(f"Error: b2cl_threshold {sub_k} not finite numeric — abort")
                        return False
                    fv = float(sub_v)
                    if not (lo <= fv <= hi):
                        print(f"Error: b2cl_threshold {sub_v} out of bounds [{lo},{hi}] — abort")
                        return False
            elif key == "interest_rates":
                if not isinstance(val, dict):
                    print("Error: interest_rates must be object — abort")
                    return False
                for sub_k, sub_v in val.items():
                    if sub_k not in allowed:
                        print(f"Error: interest_rates subkey '{sub_k}' not allowlisted — abort")
                        return False
                    lo, hi = allowed[sub_k]
                    if isinstance(sub_v, bool) or not isinstance(sub_v, (int, float)) or not math.isfinite(sub_v):
                        print(f"Error: interest_rates {sub_k} not finite numeric — abort")
                        return False
                    fv = float(sub_v)
                    if not (lo <= fv <= hi):
                        print(f"Error: interest_rates {sub_k} {sub_v} out of bounds [{lo},{hi}] — abort")
                        return False
            elif key == "late_fee_caps":
                if not isinstance(val, dict):
                    print("Error: late_fee_caps must be object — abort")
                    return False
                for sub_k, sub_v in val.items():
                    if sub_k not in allowed:
                        print(f"Error: late_fee_caps subkey '{sub_k}' not allowlisted — abort")
                        return False
                    lo, hi = allowed[sub_k]
                    if isinstance(sub_v, bool) or not isinstance(sub_v, (int, float)) or not math.isfinite(sub_v):
                        print(f"Error: late_fee_caps {sub_k} not finite numeric — abort")
                        return False
                    fv = float(sub_v)
                    if not (lo <= fv <= hi):
                        print(f"Error: late_fee_caps {sub_k} {sub_v} out of bounds [{lo},{hi}] — abort")
                        return False
            elif key == "drc_surveillance_thresholds":
                if not isinstance(val, dict):
                    print("Error: drc_surveillance_thresholds must be object — abort")
                    return False
                allowed_outer = {"drc_01b_rule_88c", "drc_01c_rule_88d"}
                for outer_k, outer_v in val.items():
                    if outer_k not in allowed_outer:
                        print(f"Error: drc_surveillance_thresholds key '{outer_k}' not allowlisted — abort")
                        return False
                    if not isinstance(outer_v, dict):
                        print(f"Error: {outer_k} must be object — abort")
                        return False
                    for inner_k, inner_v in outer_v.items():
                        if inner_k == "percentage_threshold":
                            if isinstance(inner_v, bool) or not isinstance(inner_v, (int, float)) or not math.isfinite(inner_v):
                                print(f"Error: {outer_k} percentage_threshold not finite numeric — abort")
                                return False
                            fv = float(inner_v)
                            if not (0 < fv <= 100):
                                print(f"Error: {outer_k} percentage_threshold {inner_v} out of bounds (0,100] — abort")
                                return False
                        elif inner_k == "amount_threshold":
                            if isinstance(inner_v, bool) or not isinstance(inner_v, (int, float)) or not math.isfinite(inner_v):
                                print(f"Error: {outer_k} amount_threshold not finite numeric — abort")
                                return False
                            fv = float(inner_v)
                            if not (fv > 0):
                                print(f"Error: {outer_k} amount_threshold {inner_v} must be >0 — abort")
                                return False
                        elif inner_k == "description":
                            if not isinstance(inner_v, str):
                                print(f"Error: {outer_k} description must be str — abort")
                                return False
                            continue
                        else:
                            print(f"Error: {outer_k} subkey '{inner_k}' not allowlisted — abort")
                            return False
            elif key == "statutory_gst_rates":
                if not isinstance(val, list):
                    print("Error: statutory_gst_rates must be list — abort")
                    return False
                for elem in val:
                    if isinstance(elem, bool) or not isinstance(elem, (int, float)) or not math.isfinite(elem):
                        print(f"Error: statutory_gst_rates element {elem!r} not finite numeric — abort")
                        return False
            elif key == "table_12_hsn_b2b_b2c_split":
                if not isinstance(val, dict):
                    print("Error: table_12_hsn_b2b_b2c_split must be object — abort")
                    return False
                for sub_k, sub_v in val.items():
                    if sub_k not in allowed:
                        print(f"Error: table_12_hsn_b2b_b2c_split subkey '{sub_k}' not allowlisted — abort")
                        return False
                    if sub_k == "mandatory":
                        if not isinstance(sub_v, bool):
                            print(f"Error: table_12_hsn_b2b_b2c_split mandatory must be bool — abort")
                            return False
        return True

    # Basic allowlist + bounds for statutory patch
    _ALLOWED_TOP_KEYS = {"statutory_rules", "manifest_version", "effective_date", "last_synced"}
    for k in list(patch_data.keys()):
        if k not in _ALLOWED_TOP_KEYS and k not in ("patch_id", "authority", "discovered_triggers"):
            print(f"Warning: patch key '{k}' not allowlisted — ignoring")
            patch_data.pop(k, None)

    if "statutory_rules" in patch_data:
        if not _validate_patch(patch_data["statutory_rules"]):
            return False
        # filter to only allowlisted keys before deep_update (defense in depth)
        patch_data["statutory_rules"] = {k: v for k, v in patch_data["statutory_rules"].items() if k in _ALLOWED_STATUTORY}
        deep_update(current_manifest["statutory_rules"], patch_data["statutory_rules"])
    if "manifest_version" in patch_data:
        current_manifest["manifest_version"] = patch_data["manifest_version"]

    # Stage update
    save_rules_manifest(current_manifest)
    print("\n[Step 1/2] Staged new statutory thresholds in config/rules_manifest.json")

    # Run Automated Verification Gate
    print("\n[Step 2/2] Running Automated Verification Gate (Pytest & Invariant Fuzzer)...")
    success = run_self_verification()

    if success:
        print("\n[SUCCESS] Core business scenarios & invariant tests PASSED!")
        print("Statutory rule revision COMMITTED successfully.")
        return True
    else:
        print("\n[ALERT] Verification gate FAILED! New statutory rule broke invariant tests.")
        print("Rolling back rules_manifest.json to previous stable state...")
        save_rules_manifest(backup_manifest)
        print("[ROLLBACK COMPLETE] Codebase preserved in safe, verified state.")
        return False


def print_status():
    """Prints current statutory rules overview."""
    m = load_rules_manifest()
    r = m["statutory_rules"]

    print("=" * 70)
    print(f" gstr-wala STATUTORY COMPLIANCE MANIFEST (v{m.get('manifest_version')})")
    print(f" Effective Date: {m.get('effective_date')} | Last Synced: {m.get('last_synced')}")
    print("=" * 70)
    print(f" • Table 5 B2CL Threshold: ₹{r['b2cl_threshold']['value']:,.2f} ({r['b2cl_threshold']['authority']})")
    print(f" • Table 12 HSN B2B/B2C Split: {'Mandatory' if r['table_12_hsn_b2b_b2c_split']['mandatory'] else 'Optional'}")
    print(f" • Section 50(1) Net Cash Interest: {r['interest_rates']['section_50_1_net_cash_p_a']*100:.1f}% p.a.")
    print(f" • Section 50(3) Wrong Availment Interest: {r['interest_rates']['section_50_3_wrong_avail_utilized_p_a']*100:.1f}% p.a.")
    print(f" • Section 47 Late Fee (Turnover <= 1.5 Cr): ₹{r['late_fee_caps']['upto_1.5cr_max_cap_total']:,.2f} max cap")
    print(f" • Section 47 Late Fee (Turnover > 5 Cr): ₹{r['late_fee_caps']['above_5cr_max_cap_total']:,.2f} max cap")
    print(f" • DRC-01B Trigger (Rule 88C): Variance > {r['drc_surveillance_thresholds']['drc_01b_rule_88c']['percentage_threshold']}% AND ₹{r['drc_surveillance_thresholds']['drc_01b_rule_88c']['amount_threshold']:,.2f}")
    print(f" • DRC-01C Trigger (Rule 88D): Excess > {r['drc_surveillance_thresholds']['drc_01c_rule_88d']['percentage_threshold']}% AND ₹{r['drc_surveillance_thresholds']['drc_01c_rule_88d']['amount_threshold']:,.2f}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Agentic Statutory Compliance Radar")
    parser.add_argument("--status", action="store_true", help="Print active compliance manifest status")
    parser.add_argument("--verify-rules", action="store_true", help="Run full self-verification test suite")
    parser.add_argument("--apply", help="Apply a statutory update patch JSON")

    args = parser.parse_args()

    if args.status or (not args.verify_rules and not args.apply):
        print_status()
    elif args.verify_rules:
        passed = run_self_verification()
        print(f"Self-Verification: {'PASS (100%)' if passed else 'FAIL'}")
        sys.exit(0 if passed else 1)
    elif args.apply:
        success = apply_compliance_patch(args.apply)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
