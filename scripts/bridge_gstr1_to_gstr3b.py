#!/usr/bin/env python3
"""GSTR-1 to GSTR-3B Auto-Population Bridge & DRC-01B / DRC-01C Pre-Emptive Risk Radar.

Functions:
  1. Auto-populates GSTR-3B Table 3.1 (Outward Supplies) & Table 3.2 from GSTR-1 sales.
  2. Merges GSTR-2B reconciliation results into GSTR-3B Table 4 (Eligible & Ineligible ITC).
  3. Pre-Emptive DRC-01B Radar: Checks if GSTR-1 vs GSTR-3B outward tax liability mismatch exceeds statutory thresholds (Rule 88C).
  4. Pre-Emptive DRC-01C Radar: Checks if GSTR-3B claimed ITC vs GSTR-2B available ITC exceeds statutory thresholds (Rule 88D).
  5. Outputs a fully synthesized canonical `gstr3b_input.json`.

Usage:
  python3 scripts/gstr1_to_3b_bridge.py <gstr1_input.json> <reconciliation_result.json> [output_gstr3b_input.json]
"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any

from scripts.constants import DRC_01B_AMT, DRC_01B_PCT, DRC_01C_AMT, DRC_01C_PCT
from scripts.gst_engine import compute_gstr1_tables
from scripts.utils import round_cur


def derive_gstr3b_due_date(ret_period: str) -> str:
    """Derives default GSTR-3B monthly due date (20th of succeeding month)."""
    if not ret_period or len(ret_period) != 6 or not ret_period.isdigit():
        return ""
    mm = int(ret_period[:2])
    yyyy = int(ret_period[2:])
    if not (1 <= mm <= 12 and 2020 <= yyyy <= 2035):
        return ""
    next_mm = mm + 1 if mm < 12 else 1
    next_yyyy = yyyy if mm < 12 else yyyy + 1
    return f"20-{next_mm:02d}-{next_yyyy}"


def bridge_gstr1_and_2b_to_3b(
    gstr1_data: dict[str, Any],
    recon_data: dict[str, Any] | None = None,
    due_date: str | None = None,
    filing_date: str | None = None,
    turnover_slab: str = "upto_1.5cr",
    opening_credit_ledger: dict[str, float] | None = None,
    opening_cash_ledger: dict[str, float] | None = None
) -> dict[str, Any]:
    """Synthesizes complete GSTR-3B input from GSTR-1 and GSTR-2B reconciliation."""
    g1_res = compute_gstr1_tables(gstr1_data)
    gstin = g1_res["gstin"]
    ret_period = g1_res["fp"]
    computed_due_date = due_date or derive_gstr3b_due_date(ret_period)
    computed_filing_date = filing_date or computed_due_date

    # --- Outward Supplies (Table 3.1) ---
    taxable_txval = 0.0
    taxable_iamt = 0.0
    taxable_camt = 0.0
    taxable_samt = 0.0
    taxable_csamt = 0.0

    zero_txval = 0.0
    zero_iamt = 0.0
    zero_csamt = 0.0

    # B2B & SEZ
    for inv in g1_res["table_4_b2b"]:
        inv_typ = inv.get("inv_typ", "R")
        is_sez = inv_typ in ["SEZWP", "SEZWOP"]
        for itm in inv.get("items", []):
            tx = float(itm.get("txval", 0.0))
            i = float(itm.get("iamt", 0.0))
            c = float(itm.get("camt", 0.0))
            s = float(itm.get("samt", 0.0))
            cs = float(itm.get("csamt", 0.0))

            if is_sez:
                # SEZ supplies are Zero-Rated per Section 16 IGST Act -> Table 3.1(b)
                zero_txval += tx
                zero_iamt += i
                zero_csamt += cs
            else:
                taxable_txval += tx
                taxable_iamt += i
                taxable_camt += c
                taxable_samt += s
                taxable_csamt += cs

    # B2CL
    for inv in g1_res["table_5_b2cl"]:
        for itm in inv.get("items", []):
            taxable_txval += float(itm.get("txval", 0.0))
            taxable_iamt += float(itm.get("iamt", 0.0))
            taxable_csamt += float(itm.get("csamt", 0.0))

    # B2CS
    for row in g1_res["table_7_b2cs"]:
        taxable_txval += float(row.get("txval", 0.0))
        taxable_iamt += float(row.get("iamt", 0.0))
        taxable_camt += float(row.get("camt", 0.0))
        taxable_samt += float(row.get("samt", 0.0))
        taxable_csamt += float(row.get("csamt", 0.0))

    # Zero Rated (Table 6A Exports)
    for exp_inv in g1_res["table_6_exp"]:
        for itm in exp_inv.get("items", []):
            zero_txval += float(itm.get("txval", 0.0))
            zero_iamt += float(itm.get("iamt", 0.0))
            zero_csamt += float(itm.get("csamt", 0.0))

    # --- Net for Credit/Debit Notes (Table 9) & Advances (Table 11) ---
    # Credit notes (C) reduce taxable, Debit notes (D) increase it
    from scripts.utils import safe_float

    cdnr_adj_txval = 0.0
    cdnr_adj_iamt = 0.0
    cdnr_adj_camt = 0.0
    cdnr_adj_samt = 0.0
    cdnr_adj_csamt = 0.0
    for note in g1_res.get("table_9_cdnr", []):
        ntty = note.get("ntty", "C")
        sign = -1.0 if ntty == "C" else 1.0
        for itm in note.get("items", []):
            cdnr_adj_txval += sign * safe_float(itm.get("txval", 0.0))
            cdnr_adj_iamt += sign * safe_float(itm.get("iamt", 0.0))
            cdnr_adj_camt += sign * safe_float(itm.get("camt", 0.0))
            cdnr_adj_samt += sign * safe_float(itm.get("samt", 0.0))
            cdnr_adj_csamt += sign * safe_float(itm.get("csamt", 0.0))
    # Apply CDN adjustment to taxable outward (intra/inter detection via pos vs supplier_state already handled in items)
    taxable_txval += cdnr_adj_txval
    taxable_iamt += cdnr_adj_iamt
    taxable_camt += cdnr_adj_camt
    taxable_samt += cdnr_adj_samt
    taxable_csamt += cdnr_adj_csamt

    # Advances: Table 11A received increases liability, 11B adjusted decreases
    for adv in g1_res.get("table_11_advances", {}).get("received", []):
        taxable_txval += safe_float(adv.get("txval", 0.0))
        taxable_iamt += safe_float(adv.get("iamt", 0.0))
        taxable_camt += safe_float(adv.get("camt", 0.0))
        taxable_samt += safe_float(adv.get("samt", 0.0))
        taxable_csamt += safe_float(adv.get("csamt", 0.0))
    for adj in g1_res.get("table_11_advances", {}).get("adjusted", []):
        taxable_txval -= safe_float(adj.get("txval", 0.0))
        taxable_iamt -= safe_float(adj.get("iamt", 0.0))
        taxable_camt -= safe_float(adj.get("camt", 0.0))
        taxable_samt -= safe_float(adj.get("samt", 0.0))
        taxable_csamt -= safe_float(adj.get("csamt", 0.0))

    # Nil/Exempt (Table 8)
    exemp = g1_res.get("table_8_nil_exempt", {})
    nil_txval = sum(float(v) for k, v in exemp.items() if "nil" in k or "expt" in k)
    nongst_txval = sum(float(v) for k, v in exemp.items() if "ngsup" in k)

    # --- Table 3.2 Inter-state Supplies ---
    inter_state_supplies = []
    # From B2CL
    for inv in g1_res["table_5_b2cl"]:
        pos = inv.get("pos", "")
        tx = sum(float(itm.get("txval", 0.0)) for itm in inv.get("items", []))
        i = sum(float(itm.get("iamt", 0.0)) for itm in inv.get("items", []))
        inter_state_supplies.append({
            "pos": pos,
            "supply_type": "unregistered",
            "txval": round_cur(tx),
            "iamt": round_cur(i)
        })

    # From B2CS (inter-state only)
    for row in g1_res["table_7_b2cs"]:
        if row.get("sply_ty") == "INTER":
            inter_state_supplies.append({
                "pos": row.get("pos"),
                "supply_type": "unregistered",
                "txval": round_cur(row.get("txval", 0.0)),
                "iamt": round_cur(row.get("iamt", 0.0))
            })

    # --- Table 4 ITC (from Reconciliation Result) ---
    t4_auto = {}
    if recon_data and "gstr3b_table_4_auto_population" in recon_data:
        t4_auto = recon_data["gstr3b_table_4_auto_population"]

    t4_rcm = t4_auto.get("table_4_a_3_rcm_inward", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0, "txval": 0.0})
    t4_impg = t4_auto.get("table_4_a_1_import_goods", {"iamt": 0.0, "csamt": 0.0})
    t4_isd = t4_auto.get("table_4_a_4_isd", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0})

    itc_payload = {
        "available": {
            "import_goods": {"iamt": round_cur(t4_impg.get("iamt", 0.0)), "csamt": round_cur(t4_impg.get("csamt", 0.0))},
            "import_services": {"iamt": 0.0, "csamt": 0.0},
            "rcm_inward": {
                "iamt": round_cur(t4_rcm.get("iamt", 0.0)),
                "camt": round_cur(t4_rcm.get("camt", 0.0)),
                "samt": round_cur(t4_rcm.get("samt", 0.0)),
                "csamt": round_cur(t4_rcm.get("csamt", 0.0))
            },
            "isd": {
                "iamt": round_cur(t4_isd.get("iamt", 0.0)),
                "camt": round_cur(t4_isd.get("camt", 0.0)),
                "samt": round_cur(t4_isd.get("samt", 0.0)),
                "csamt": round_cur(t4_isd.get("csamt", 0.0))
            },
            "all_other": t4_auto.get("table_4_a_5_all_other_itc", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0})
        },
        "reversed": {
            "permanent_17_5_rules": t4_auto.get("table_4_b_1_permanent_reversals_17_5", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}),
            "temporary_others": t4_auto.get("table_4_b_2_temporary_reversals_rule37", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0})
        },
        "other_details": {
            "reclaimed": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "ineligible_16_4_pos": t4_auto.get("table_4_d_2_ineligible_16_4", {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0})
        }
    }

    gstr3b_input = {
        "gstin": gstin,
        "ret_period": ret_period,
        "due_date": computed_due_date,
        "filing_date": computed_filing_date,
        "turnover_slab": turnover_slab,
        "outward_supplies": {
            "taxable": {
                "txval": round_cur(taxable_txval),
                "iamt": round_cur(taxable_iamt),
                "camt": round_cur(taxable_camt),
                "samt": round_cur(taxable_samt),
                "csamt": round_cur(taxable_csamt)
            },
            "zero_rated": {
                "txval": round_cur(zero_txval),
                "iamt": round_cur(zero_iamt),
                "csamt": round_cur(zero_csamt)
            },
            "nil_exempt": {
                "txval": round_cur(nil_txval)
            },
            "rcm_inward": {
                "txval": round_cur(t4_rcm.get("txval", 0.0)),
                "iamt": round_cur(t4_rcm.get("iamt", 0.0)),
                "camt": round_cur(t4_rcm.get("camt", 0.0)),
                "samt": round_cur(t4_rcm.get("samt", 0.0)),
                "csamt": round_cur(t4_rcm.get("csamt", 0.0))
            },
            "non_gst": {
                "txval": round_cur(nongst_txval)
            }
        },
        "eco_supplies": {
            "eco_pays_tax": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "registered_through_eco": {"txval": 0.0}
        },
        "inter_state_supplies": inter_state_supplies,
        "itc": itc_payload,
        "inward_exempt_nil_non_gst": {
            "from_composition_exempt": {"inter": 0.0, "intra": 0.0},
            "non_gst": {"inter": 0.0, "intra": 0.0}
        },
        "opening_credit_ledger": opening_credit_ledger or {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
        "opening_cash_ledger": opening_cash_ledger or {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
    }

    return gstr3b_input


def check_drc_mismatch_risks(gstr1_summary: dict[str, Any], gstr3b_data: dict[str, Any], gstr2b_total_itc: float) -> dict[str, Any]:
    """Evaluates DRC-01B (Rule 88C) and DRC-01C (Rule 88D) pre-emptive audit risk."""
    g1_tax = gstr1_summary.get("total_tax", 0.0)

    outward = gstr3b_data.get("outward_supplies", {})
    taxable = outward.get("taxable", {})
    zero = outward.get("zero_rated", {})
    g3b_tax = (
        float(taxable.get("iamt", 0.0)) + float(taxable.get("camt", 0.0)) + float(taxable.get("samt", 0.0)) + float(taxable.get("csamt", 0.0)) +
        float(zero.get("iamt", 0.0)) + float(zero.get("csamt", 0.0))
    )

    drc01b_diff = max(0.0, g1_tax - g3b_tax)
    drc01b_pct = (drc01b_diff / g1_tax * 100.0) if g1_tax > 0 else 0.0
    # Statute is 20% AND ₹25L (conservative radar flags on OR, portal uses AND — keep AND for correctness)
    drc01b_risk = (drc01b_diff > DRC_01B_AMT and drc01b_pct > DRC_01B_PCT) if drc01b_diff > 0 else False

    # DRC-01C must check total net ITC claimed (sum all available minus reversals), not just all_other
    avail = gstr3b_data.get("itc", {}).get("available", {})
    rev = gstr3b_data.get("itc", {}).get("reversed", {})
    tot_avail = 0.0
    for cat_vals in avail.values():
        if isinstance(cat_vals, dict):
            tot_avail += float(cat_vals.get("iamt", 0.0)) + float(cat_vals.get("camt", 0.0)) + float(cat_vals.get("samt", 0.0)) + float(cat_vals.get("csamt", 0.0))
    tot_rev = 0.0
    for cat_vals in rev.values():
        if isinstance(cat_vals, dict):
            tot_rev += float(cat_vals.get("iamt", 0.0)) + float(cat_vals.get("camt", 0.0)) + float(cat_vals.get("samt", 0.0)) + float(cat_vals.get("csamt", 0.0))
    g3b_claimed_itc = max(0.0, tot_avail - tot_rev)

    drc01c_diff = max(0.0, g3b_claimed_itc - gstr2b_total_itc)
    drc01c_pct = (drc01c_diff / gstr2b_total_itc * 100.0) if gstr2b_total_itc > 0 else 0.0
    drc01c_risk = (drc01c_diff > DRC_01C_AMT and drc01c_pct > DRC_01C_PCT) if drc01c_diff > 0 else False

    return {
        "drc_01b_liability_mismatch": {
            "gstr1_total_tax": round_cur(g1_tax),
            "gstr3b_total_tax": round_cur(g3b_tax),
            "variance": round_cur(drc01b_diff),
            "variance_percentage": round_cur(drc01b_pct),
            "risk_flag": drc01b_risk,
            "warning": "HIGH RISK: DRC-01B notice will be triggered if variance exceeds 20% AND ₹25 Lakh." if drc01b_risk else "SAFE: Liability matches within safe thresholds."
        },
        "drc_01c_itc_mismatch": {
            "gstr2b_available_itc": round_cur(gstr2b_total_itc),
            "gstr3b_claimed_itc": round_cur(g3b_claimed_itc),
            "excess_claimed": round_cur(drc01c_diff),
            "excess_percentage": round_cur(drc01c_pct),
            "risk_flag": drc01c_risk,
            "warning": "HIGH RISK: DRC-01C notice will be triggered if ITC claimed exceeds GSTR-2B by >10% AND ₹1 Lakh." if drc01c_risk else "SAFE: ITC claimed matches GSTR-2B."
        }
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Auto-populate GSTR-3B from GSTR-1 and GSTR-2B reconciliation")
    parser.add_argument("g1_input", help="Path to GSTR-1 Input JSON")
    parser.add_argument("pos_args", nargs="*", help="Optional [recon_input] [output_3b]")
    parser.add_argument("--recon", dest="recon_opt", default=None, help="Explicit path to reconciliation JSON")
    parser.add_argument("-o", "--output", dest="out_opt", default=None, help="Explicit path to output GSTR-3B JSON")

    args = parser.parse_args()

    g1_file = args.g1_input
    recon_file = args.recon_opt
    out_file = args.out_opt or "gstr3b_input.json"

    if args.pos_args:
        if len(args.pos_args) == 1:
            arg0 = args.pos_args[0]
            if not recon_file and ("recon" in arg0.lower() or (os.path.exists(arg0) and "3b" not in arg0.lower())):
                recon_file = arg0
            else:
                out_file = arg0
        elif len(args.pos_args) >= 2:
            recon_file = args.pos_args[0] if not recon_file else recon_file
            out_file = args.pos_args[1]

    with open(g1_file, "r", encoding="utf-8") as f:
        g1_data = json.load(f)

    recon_data = None
    if recon_file and os.path.exists(recon_file):
        with open(recon_file, "r", encoding="utf-8") as f:
            recon_data = json.load(f)

    g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_data)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(g3b_input, f, indent=2)

    all_other = g3b_input.get("itc", {}).get("available", {}).get("all_other", {})
    tot_itc = float(all_other.get("iamt", 0.0)) + float(all_other.get("camt", 0.0)) + float(all_other.get("samt", 0.0)) + float(all_other.get("csamt", 0.0))

    print(f"SUCCESS: Auto-populated GSTR-3B input -> '{out_file}'")
    print(f"Taxable: ₹{g3b_input['outward_supplies']['taxable']['txval']:,.2f}, Total ITC: ₹{tot_itc:,.2f}")


if __name__ == "__main__":
    main()
