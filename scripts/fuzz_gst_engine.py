#!/usr/bin/env python3
"""Invariant Property-Based Fuzzer for gstr-wala.

Performs 1,000+ randomized iterations testing mathematical and statutory invariants:
  1. Conservation of Tax: Outward Tax Liability == Credit Utilized + Regular Cash Paid.
  2. Non-Negativity: All credits, set-offs, cash balances, and challans are >= 0.0.
  3. RCM Cash Purity: Inward RCM liability must be paid strictly 100% in CASH.
  4. IGST Exhaustion First: CGST/SGST credits are never touched while IGST credit > 0.
  5. PMT-06 Challan Minimization: Challan required == max(0.0, Cash Required - Opening Cash Ledger).

Usage:
  python3 scripts/fuzz_gst_engine.py [--iterations 1000]
"""

import argparse
import random

from scripts.itc_optimizer import optimize_setoff
from scripts.models import TaxAmounts


def run_fuzzer(iterations: int = 1000):
    print(f"Starting gstr-wala Invariant Fuzzer ({iterations} randomized iterations)...")

    for i in range(1, iterations + 1):
        # Generate random liabilities (0 to 10,00,000 INR)
        outward_liabilities: TaxAmounts = {
            "iamt": round(random.uniform(0, 1000000), 2),
            "camt": round(random.uniform(0, 500000), 2),
            "samt": round(random.uniform(0, 500000), 2),
            "csamt": round(random.uniform(0, 200000), 2)
        }

        # Inward RCM liabilities (0 to 1,00,000 INR)
        rcm_liabilities: TaxAmounts = {
            "iamt": round(random.uniform(0, 100000), 2),
            "camt": round(random.uniform(0, 50000), 2),
            "samt": round(random.uniform(0, 50000), 2),
            "csamt": round(random.uniform(0, 20000), 2)
        }

        # Available ITC (0 to 12,00,000 INR)
        available_itc: TaxAmounts = {
            "iamt": round(random.uniform(0, 1200000), 2),
            "camt": round(random.uniform(0, 600000), 2),
            "samt": round(random.uniform(0, 600000), 2),
            "csamt": round(random.uniform(0, 300000), 2)
        }

        # Opening Cash Ledger (0 to 1,00,000 INR)
        opening_cash = {
            "iamt": round(random.uniform(0, 100000), 2),
            "camt": round(random.uniform(0, 50000), 2),
            "samt": round(random.uniform(0, 50000), 2),
            "csamt": round(random.uniform(0, 20000), 2)
        }

        result = optimize_setoff(
            liabilities=outward_liabilities,
            rcm_liabilities=rcm_liabilities,
            available_itc=available_itc,
            opening_cash=opening_cash
        )

        m = result["setoff_matrix"]
        cu = result.get("credit_utilization", {})
        cash = result["net_cash_required"]
        chal = result.get("challan_pmt06", {})
        rcm_cash = result["rcm_cash_liability"]

        # --- Invariant 1: Conservation of Outward Tax ---
        total_outward_tax = round(
            float(outward_liabilities["iamt"]) + float(outward_liabilities["camt"]) +
            float(outward_liabilities["samt"]) + float(outward_liabilities["csamt"]), 2
        )
        total_credit_used = round(
            float(cu.get("total_credit_utilized", 0.0)), 2
        )
        regular_cash_paid = round(
            float(m["igst_liability"]["paid_by_cash"]) +
            float(m["cgst_liability"]["paid_by_cash"]) +
            float(m["sgst_liability"]["paid_by_cash"]) +
            float(m["cess_liability"]["paid_by_cash"]), 2
        )
        diff_tax = abs(total_outward_tax - (total_credit_used + regular_cash_paid))
        assert diff_tax <= 0.05, f"Iteration {i}: Conservation of tax violated! Outward ₹{total_outward_tax} != Credit ₹{total_credit_used} + Cash ₹{regular_cash_paid} (diff ₹{diff_tax})"

        # --- Invariant 2: Non-Negativity ---
        for row in [m["igst_liability"], m["cgst_liability"], m["sgst_liability"], m["cess_liability"]]:
            for k, val in row.items():
                if isinstance(val, (int, float)):
                    assert val >= 0.0, f"Iteration {i}: Negative value in row {k} = {val}"

        assert cu.get("total_credit_utilized", 0.0) >= 0.0
        assert cash.get("total_cash_payable", 0.0) >= 0.0
        assert chal.get("total_challan_amount", 0.0) >= 0.0

        # --- Invariant 3: RCM Cash Purity ---
        expected_rcm_total = round(
            rcm_liabilities["iamt"] + rcm_liabilities["camt"] +
            rcm_liabilities["samt"] + rcm_liabilities["csamt"], 2
        )
        assert round(rcm_cash["total"], 2) == expected_rcm_total, f"Iteration {i}: RCM cash liability {rcm_cash['total']} != expected {expected_rcm_total}"

        # --- Invariant 4: Rule 88A Priority (IGST credit must be zero before CGST/SGST are used) ---
        igst_rem = float(cu.get("igst_credit", {}).get("closing_balance", 0.0))
        cgst_used = float(cu.get("cgst_credit", {}).get("utilized", 0.0))
        sgst_used = float(cu.get("sgst_credit", {}).get("utilized", 0.0))
        if cgst_used > 0 or sgst_used > 0:
            assert igst_rem == 0.0, f"Iteration {i}: Rule 88A violation: CGST/SGST credit used while IGST credit remained (rem IGST: ₹{igst_rem})"

        # --- Invariant 5: PMT-06 Challan Exact Math ---
        for head in ["iamt", "camt", "samt", "csamt"]:
            req_cash = float(cash.get(head, 0.0))
            op_cash = float(opening_cash.get(head, 0.0))
            expected_challan = max(0.0, round(req_cash - op_cash, 2))
            actual_challan = float(chal.get(head, 0.0))
            assert actual_challan == expected_challan, f"Iteration {i}: Challan mismatch on {head}: expected {expected_challan}, found {actual_challan}"

    print(f"SUCCESS: {iterations} randomized iterations passed all 5 mathematical & statutory invariants (0 violations).")
    return True


def main():
    parser = argparse.ArgumentParser(description="Invariant Property-Based Fuzzer for gstr-wala")
    parser.add_argument("--iterations", type=int, default=1000, help="Number of fuzzing iterations (default: 1000)")
    args = parser.parse_args()

    run_fuzzer(args.iterations)


if __name__ == "__main__":
    main()
