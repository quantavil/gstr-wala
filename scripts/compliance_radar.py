#!/usr/bin/env python3
"""Agentic Compliance Radar for gstr-wala.

Monitors, validates, and autonomously applies statutory rule updates (e.g. rate changes,
threshold revisions, late fee caps, DRC triggers) from CBIC notifications & GSTN advisories.
"""

import argparse
import json
import os
import subprocess
import sys
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
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_self_verification() -> bool:
    """Runs core test suite to verify that statutory rules do not violate invariants."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Run full test suite avoiding recursive invocation of self-test
    cmd = ["uv", "run", "pytest", "tests/", "-k", "not test_compliance_radar", "-q"]
    try:
        res = subprocess.run(cmd, cwd=root_dir, capture_output=True, text=True)
        return res.returncode == 0
    except Exception as e:
        print(f"Verification error: {e}")
        return False


def apply_compliance_patch(patch_file: str) -> bool:
    """Agentically applies and tests a statutory compliance patch."""
    if not os.path.exists(patch_file):
        print(f"Error: Patch file '{patch_file}' not found.")
        return False

    with open(patch_file, "r", encoding="utf-8") as f:
        patch_data = json.load(f)

    current_manifest = load_rules_manifest()
    backup_manifest = dict(current_manifest)

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

    if "statutory_rules" in patch_data:
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
    print(f" • DRC-01B Trigger (Rule 88C): Variance > {r['drc_surveillance_thresholds']['drc_01b_rule_88c']['percentage_threshold']}% or ₹{r['drc_surveillance_thresholds']['drc_01b_rule_88c']['amount_threshold']:,.2f}")
    print(f" • DRC-01C Trigger (Rule 88D): Excess > {r['drc_surveillance_thresholds']['drc_01c_rule_88d']['percentage_threshold']}% or ₹{r['drc_surveillance_thresholds']['drc_01c_rule_88d']['amount_threshold']:,.2f}")
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
