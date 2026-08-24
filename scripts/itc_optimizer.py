#!/usr/bin/env python3
"""Rule 88A / Section 49 Linear Optimization Engine for GST ITC Set-Off.

Optimizes electronic credit ledger utilization to strictly minimize net cash outflow:
  1. Exhausts IGST credit against IGST liability first.
  2. Optimally allocates remaining IGST credit between CGST and SGST liabilities to eliminate stranded credits.
  3. Only after IGST credit is zero, applies CGST credit against remaining CGST and IGST liabilities.
  4. Applies SGST credit against remaining SGST and IGST liabilities.
  5. Enforces Section 49(4): RCM liabilities must be paid 100% in CASH.
  6. Calculates exact PMT-06 Challan deposit amounts based on Electronic Cash Ledger balances.

Usage:
  python3 scripts/itc_optimizer.py <gstr3b_input.json> [--json]
"""

import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.models import TaxAmounts, OptimizationResult, SetOffMatrix, SetOffMatrixRow
from scripts.utils import round_cur


def optimize_setoff(
    liabilities: TaxAmounts,
    rcm_liabilities: TaxAmounts,
    available_itc: TaxAmounts,
    opening_cash: Optional[Dict[str, float]] = None,
    opening_credit: Optional[TaxAmounts] = None,
    interest: Optional[Dict[str, float]] = None,
    late_fee: Optional[Dict[str, float]] = None
) -> OptimizationResult:
    """Solves the Rule 88A set-off optimization problem."""
    # Outward liabilities
    l_i = float(liabilities.get("iamt", 0.0))
    l_c = float(liabilities.get("camt", 0.0))
    l_s = float(liabilities.get("samt", 0.0))
    l_cs = float(liabilities.get("csamt", 0.0))

    # Inward RCM liabilities (Must be 100% Cash)
    rcm_i = float(rcm_liabilities.get("iamt", 0.0))
    rcm_c = float(rcm_liabilities.get("camt", 0.0))
    rcm_s = float(rcm_liabilities.get("samt", 0.0))
    rcm_cs = float(rcm_liabilities.get("csamt", 0.0))

    # Total Available Credit = Current Month Net ITC + Opening Credit Ledger
    op_cr = opening_credit or {}
    c_i = float(available_itc.get("iamt", 0.0)) + float(op_cr.get("iamt", 0.0))
    c_c = float(available_itc.get("camt", 0.0)) + float(op_cr.get("camt", 0.0))
    c_s = float(available_itc.get("samt", 0.0)) + float(op_cr.get("samt", 0.0))
    c_cs = float(available_itc.get("csamt", 0.0)) + float(op_cr.get("csamt", 0.0))

    # -------------------------------------------------------------
    # Step 1: IGST Credit vs IGST Outward Liability
    # -------------------------------------------------------------
    igst_to_igst = min(l_i, c_i)
    rem_l_i = l_i - igst_to_igst
    rem_c_i = c_i - igst_to_igst

    # -------------------------------------------------------------
    # Step 2: Optimal Allocation of Remaining IGST Credit to CGST & SGST
    # -------------------------------------------------------------
    deficit_c = max(0.0, l_c - c_c)
    deficit_s = max(0.0, l_s - c_s)

    igst_to_cgst = 0.0
    igst_to_sgst = 0.0

    if rem_c_i > 0:
        # First allocate to cover credit deficits (to prevent cash outlays where own credit is lacking)
        alloc_c = min(deficit_c, min(l_c, rem_c_i))
        rem_c_i -= alloc_c
        alloc_s = min(deficit_s, min(l_s, rem_c_i))
        rem_c_i -= alloc_s

        # If there is still IGST credit left, split evenly or absorb remaining liabilities
        if rem_c_i > 0:
            avail_cap_c = max(0.0, l_c - alloc_c)
            avail_cap_s = max(0.0, l_s - alloc_s)
            
            # Equal split of remaining
            half_rem = rem_c_i / 2.0
            extra_c = min(avail_cap_c, half_rem)
            extra_s = min(avail_cap_s, rem_c_i - extra_c)
            
            # If extra_s didn't consume all remainder, try pushing more to C
            if (rem_c_i - extra_c - extra_s) > 0 and (avail_cap_c - extra_c) > 0:
                more_c = min(avail_cap_c - extra_c, rem_c_i - extra_c - extra_s)
                extra_c += more_c

            alloc_c += extra_c
            alloc_s += extra_s
            rem_c_i = max(0.0, rem_c_i - extra_c - extra_s)

        igst_to_cgst = alloc_c
        igst_to_sgst = alloc_s

    rem_l_c = max(0.0, l_c - igst_to_cgst)
    rem_l_s = max(0.0, l_s - igst_to_sgst)

    # -------------------------------------------------------------
    # Step 3: CGST Credit Utilization
    # -------------------------------------------------------------
    cgst_to_cgst = min(rem_l_c, c_c)
    rem_l_c -= cgst_to_cgst
    rem_c_c = c_c - cgst_to_cgst

    cgst_to_igst = min(rem_l_i, rem_c_c)
    rem_l_i -= cgst_to_igst
    rem_c_c -= cgst_to_igst

    # -------------------------------------------------------------
    # Step 4: SGST Credit Utilization
    # -------------------------------------------------------------
    sgst_to_sgst = min(rem_l_s, c_s)
    rem_l_s -= sgst_to_sgst
    rem_c_s = c_s - sgst_to_sgst

    sgst_to_igst = min(rem_l_i, rem_c_s)
    rem_l_i -= sgst_to_igst
    rem_c_s -= sgst_to_igst

    # -------------------------------------------------------------
    # Step 5: Cess Credit Utilization
    # -------------------------------------------------------------
    cess_to_cess = min(l_cs, c_cs)
    rem_l_cs = l_cs - cess_to_cess
    rem_c_cs = c_cs - cess_to_cess

    # -------------------------------------------------------------
    # Step 6: Net Tax Payable in Cash
    # -------------------------------------------------------------
    # Regular outward cash liability
    cash_outward_i = rem_l_i
    cash_outward_c = rem_l_c
    cash_outward_s = rem_l_s
    cash_outward_cs = rem_l_cs

    # Total cash tax requirement (Outward + RCM 100% Cash)
    total_cash_tax_i = cash_outward_i + rcm_i
    total_cash_tax_c = cash_outward_c + rcm_c
    total_cash_tax_s = cash_outward_s + rcm_s
    total_cash_tax_cs = cash_outward_cs + rcm_cs

    # Interest & Late fee liabilities (Must be 100% Cash)
    intr = interest or {}
    intr_i = float(intr.get("iamt", 0.0))
    intr_c = float(intr.get("camt", 0.0))
    intr_s = float(intr.get("samt", 0.0))
    intr_cs = float(intr.get("csamt", 0.0))
    
    # Fallback if a single total interest_amount is supplied
    if (intr_i + intr_c + intr_s + intr_cs) == 0.0 and "interest_amount" in intr:
        tot_intr = float(intr.get("interest_amount", 0.0))
        tot_cash_tax = total_cash_tax_i + total_cash_tax_c + total_cash_tax_s + total_cash_tax_cs
        if tot_cash_tax > 0:
            # Compute 3 heads with HALF_UP, remainder to 4th to preserve total (avoid 1p loss)
            raw_i = tot_intr * (total_cash_tax_i / tot_cash_tax)
            raw_c = tot_intr * (total_cash_tax_c / tot_cash_tax)
            raw_s = tot_intr * (total_cash_tax_s / tot_cash_tax)
            intr_i = round_cur(raw_i)
            intr_c = round_cur(raw_c)
            intr_s = round_cur(raw_s)
            # remainder ensures sum == tot_intr
            intr_cs = round_cur(tot_intr - intr_i - intr_c - intr_s)
            if intr_cs < 0:
                intr_cs = 0.0
        else:
            intr_i = tot_intr

    lf = late_fee or {}
    lf_c = float(lf.get("camt", lf.get("cgst_late_fee", 0.0)))
    lf_s = float(lf.get("samt", lf.get("sgst_late_fee", 0.0)))

    # Total Cash Requirements per Ledger Head
    req_cash_i = total_cash_tax_i + intr_i
    req_cash_c = total_cash_tax_c + intr_c + lf_c
    req_cash_s = total_cash_tax_s + intr_s + lf_s
    req_cash_cs = total_cash_tax_cs + intr_cs

    # -------------------------------------------------------------
    # Step 7: Electronic Cash Ledger Offsetting & Challan PMT-06
    # -------------------------------------------------------------
    op_cash = opening_cash or {}
    avail_cash_i = float(op_cash.get("iamt", 0.0))
    avail_cash_c = float(op_cash.get("camt", 0.0))
    avail_cash_s = float(op_cash.get("samt", 0.0))
    avail_cash_cs = float(op_cash.get("csamt", 0.0))

    challan_i = max(0.0, req_cash_i - avail_cash_i)
    challan_c = max(0.0, req_cash_c - avail_cash_c)
    challan_s = max(0.0, req_cash_s - avail_cash_s)
    challan_cs = max(0.0, req_cash_cs - avail_cash_cs)
    total_challan = challan_i + challan_c + challan_s + challan_cs

    closing_cash_i = max(0.0, avail_cash_i - req_cash_i)
    closing_cash_c = max(0.0, avail_cash_c - req_cash_c)
    closing_cash_s = max(0.0, avail_cash_s - req_cash_s)
    closing_cash_cs = max(0.0, avail_cash_cs - req_cash_cs)

    return {
        "setoff_matrix": {
            "igst_liability": {
                "total": round_cur(l_i),
                "paid_by_igst_credit": round_cur(igst_to_igst),
                "paid_by_cgst_credit": round_cur(cgst_to_igst),
                "paid_by_sgst_credit": round_cur(sgst_to_igst),
                "paid_by_cash": round_cur(cash_outward_i)
            },
            "cgst_liability": {
                "total": round_cur(l_c),
                "paid_by_igst_credit": round_cur(igst_to_cgst),
                "paid_by_cgst_credit": round_cur(cgst_to_cgst),
                "paid_by_cash": round_cur(cash_outward_c)
            },
            "sgst_liability": {
                "total": round_cur(l_s),
                "paid_by_igst_credit": round_cur(igst_to_sgst),
                "paid_by_sgst_credit": round_cur(sgst_to_sgst),
                "paid_by_cash": round_cur(cash_outward_s)
            },
            "cess_liability": {
                "total": round_cur(l_cs),
                "paid_by_cess_credit": round_cur(cess_to_cess),
                "paid_by_cash": round_cur(cash_outward_cs)
            }
        },
        "credit_utilization": {
            "igst_credit": {"available": round_cur(c_i), "utilized": round_cur(c_i - rem_c_i), "closing_balance": round_cur(rem_c_i)},
            "cgst_credit": {"available": round_cur(c_c), "utilized": round_cur(c_c - rem_c_c), "closing_balance": round_cur(rem_c_c)},
            "sgst_credit": {"available": round_cur(c_s), "utilized": round_cur(c_s - rem_c_s), "closing_balance": round_cur(rem_c_s)},
            "cess_credit": {"available": round_cur(c_cs), "utilized": round_cur(c_cs - rem_c_cs), "closing_balance": round_cur(rem_c_cs)},
            "total_credit_utilized": round_cur((c_i - rem_c_i) + (c_c - rem_c_c) + (c_s - rem_c_s) + (c_cs - rem_c_cs))
        },
        "rcm_cash_liability": {
            "iamt": round_cur(rcm_i),
            "camt": round_cur(rcm_c),
            "samt": round_cur(rcm_s),
            "csamt": round_cur(rcm_cs),
            "total": round_cur(rcm_i + rcm_c + rcm_s + rcm_cs)
        },
        "interest_liability": {
            "iamt": round_cur(intr_i), "camt": round_cur(intr_c), "samt": round_cur(intr_s), "csamt": round_cur(intr_cs),
            "total": round_cur(intr_i + intr_c + intr_s + intr_cs)
        },
        "late_fee_liability": {
            "camt": round_cur(lf_c), "samt": round_cur(lf_s), "total": round_cur(lf_c + lf_s)
        },
        "net_cash_required": {
            "iamt": round_cur(req_cash_i),
            "camt": round_cur(req_cash_c),
            "samt": round_cur(req_cash_s),
            "csamt": round_cur(req_cash_cs),
            "total_cash_payable": round_cur(req_cash_i + req_cash_c + req_cash_s + req_cash_cs)
        },
        "challan_pmt06": {
            "iamt": round_cur(challan_i),
            "camt": round_cur(challan_c),
            "samt": round_cur(challan_s),
            "csamt": round_cur(challan_cs),
            "total_challan_amount": round_cur(total_challan),
            "payment_required": total_challan > 0
        },
        "closing_cash_ledger": {
            "iamt": round_cur(closing_cash_i),
            "camt": round_cur(closing_cash_c),
            "samt": round_cur(closing_cash_s),
            "csamt": round_cur(closing_cash_cs)
        }
    }


def optimize_from_input_dict(data: Dict[str, Any]) -> OptimizationResult:
    """Extracts parameters from canonical GSTR-3B input and executes optimization."""
    outward = data.get("outward_supplies", {})
    taxable = outward.get("taxable", {})
    zero_rated = outward.get("zero_rated", {})
    rcm_inward = outward.get("rcm_inward", {})

    # Outward tax liabilities = taxable + zero_rated
    liabilities: TaxAmounts = {
        "iamt": float(taxable.get("iamt", 0.0)) + float(zero_rated.get("iamt", 0.0)),
        "camt": float(taxable.get("camt", 0.0)),
        "samt": float(taxable.get("samt", 0.0)),
        "csamt": float(taxable.get("csamt", 0.0)) + float(zero_rated.get("csamt", 0.0))
    }

    rcm_liabilities: TaxAmounts = {
        "iamt": float(rcm_inward.get("iamt", 0.0)),
        "camt": float(rcm_inward.get("camt", 0.0)),
        "samt": float(rcm_inward.get("samt", 0.0)),
        "csamt": float(rcm_inward.get("csamt", 0.0))
    }

    # ITC available from Table 4(A) minus reversals 4(B)
    itc = data.get("itc", {})
    avail = itc.get("available", {})
    rev = itc.get("reversed", {})

    # Sum all Table 4(A) items
    tot_avail_i = sum(float(avail.get(cat, {}).get("iamt", 0.0)) for cat in avail)
    tot_avail_c = sum(float(avail.get(cat, {}).get("camt", 0.0)) for cat in avail)
    tot_avail_s = sum(float(avail.get(cat, {}).get("samt", 0.0)) for cat in avail)
    tot_avail_cs = sum(float(avail.get(cat, {}).get("csamt", 0.0)) for cat in avail)

    # Sum all Table 4(B) reversals
    tot_rev_i = sum(float(rev.get(cat, {}).get("iamt", 0.0)) for cat in rev)
    tot_rev_c = sum(float(rev.get(cat, {}).get("camt", 0.0)) for cat in rev)
    tot_rev_s = sum(float(rev.get(cat, {}).get("samt", 0.0)) for cat in rev)
    tot_rev_cs = sum(float(rev.get(cat, {}).get("csamt", 0.0)) for cat in rev)

    net_itc: TaxAmounts = {
        "iamt": max(0.0, tot_avail_i - tot_rev_i),
        "camt": max(0.0, tot_avail_c - tot_rev_c),
        "samt": max(0.0, tot_avail_s - tot_rev_s),
        "csamt": max(0.0, tot_avail_cs - tot_rev_cs)
    }

    return optimize_setoff(
        liabilities=liabilities,
        rcm_liabilities=rcm_liabilities,
        available_itc=net_itc,
        opening_cash=data.get("opening_cash_ledger"),
        opening_credit=data.get("opening_credit_ledger"),
        interest=data.get("interest_details"),
        late_fee=data.get("late_fee_details")
    )


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
    from scripts.utils import format_table as _ft

    return _ft(headers, rows)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 itc_optimizer.py <gstr3b_input.json> [--json]")
        sys.exit(1)

    file_path = sys.argv[1]
    json_output = "--json" in sys.argv

    if not os.path.exists(file_path):
        sys.exit(f"Error: File '{file_path}' not found.")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = optimize_from_input_dict(data)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        m = result["setoff_matrix"]
        print("=" * 70)
        print(" GSTR-3B TABLE 6.1: RULE 88A OPTIMAL TAX SET-OFF MATRIX")
        print("=" * 70)
        matrix_rows = [
            ["Integrated Tax (IGST)", f"₹{m['igst_liability']['total']:,.2f}", f"₹{m['igst_liability']['paid_by_igst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_cgst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_sgst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_cash']:,.2f}"],
            ["Central Tax (CGST)", f"₹{m['cgst_liability']['total']:,.2f}", f"₹{m['cgst_liability']['paid_by_igst_credit']:,.2f}", f"₹{m['cgst_liability']['paid_by_cgst_credit']:,.2f}", "-", f"₹{m['cgst_liability']['paid_by_cash']:,.2f}"],
            ["State/UT Tax (SGST)", f"₹{m['sgst_liability']['total']:,.2f}", f"₹{m['sgst_liability']['paid_by_igst_credit']:,.2f}", "-", f"₹{m['sgst_liability']['paid_by_sgst_credit']:,.2f}", f"₹{m['sgst_liability']['paid_by_cash']:,.2f}"],
            ["Cess", f"₹{m['cess_liability']['total']:,.2f}", "-", "-", "-", f"₹{m['cess_liability']['paid_by_cash']:,.2f}"]
        ]
        print(format_table(["Tax Head", "Total Tax", "Paid via IGST Cr", "Paid via CGST Cr", "Paid via SGST Cr", "Paid via Cash"], matrix_rows))

        c = result["challan_pmt06"]
        print("\n[CHALLAN PMT-06 PAYMENT ESTIMATE]")
        challan_rows = [
            ["IGST Cash Required", f"₹{c['iamt']:,.2f}"],
            ["CGST Cash Required", f"₹{c['camt']:,.2f}"],
            ["SGST Cash Required", f"₹{c['samt']:,.2f}"],
            ["Cess Cash Required", f"₹{c['csamt']:,.2f}"],
            ["TOTAL CHALLAN TO DEPOSIT", f"₹{c['total_challan_amount']:,.2f}"]
        ]
        print(format_table(["Challan Head", "Amount to Deposit"], challan_rows))

    sys.exit(0)


if __name__ == "__main__":
    main()
