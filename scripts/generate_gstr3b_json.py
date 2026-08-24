#!/usr/bin/env python3
"""Serializes canonical GSTR-3B input JSON into official GST Portal upload payload.

Complies with the official GSTN Returns Offline Tool Schema (v3.x / 2026).
"""

import json
import os
import sys

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any

from scripts.itc_optimizer import optimize_from_input_dict
from scripts.utils import round_cur


def sum_tax_rows(rows: list[dict[str, Any]], key: str) -> float:
    """Helper to sum numeric tax fields from heterogeneous dicts."""
    total = 0.0
    for r in rows:
        val = r.get(key, 0.0)
        if isinstance(val, (int, float)):
            total += float(val)
    return total


def generate_portal_gstr3b(input_data: dict[str, Any]) -> dict[str, Any]:
    """Transforms canonical GSTR-3B input JSON into official portal JSON."""
    gstin = input_data.get("gstin", "")
    ret_period = input_data.get("ret_period", "")

    # Table 3.1: sup_details
    outward = input_data.get("outward_supplies", {})
    taxable = outward.get("taxable", {})
    zero_rated = outward.get("zero_rated", {})
    nil_exempt = outward.get("nil_exempt", {})
    rcm_inward = outward.get("rcm_inward", {})
    non_gst = outward.get("non_gst", {})

    sup_details = {
        "osup_det": {
            "txval": round_cur(taxable.get("txval", 0.0)),
            "iamt": round_cur(taxable.get("iamt", 0.0)),
            "camt": round_cur(taxable.get("camt", 0.0)),
            "samt": round_cur(taxable.get("samt", 0.0)),
            "csamt": round_cur(taxable.get("csamt", 0.0))
        },
        "osup_zero": {
            "txval": round_cur(zero_rated.get("txval", 0.0)),
            "iamt": round_cur(zero_rated.get("iamt", 0.0)),
            "csamt": round_cur(zero_rated.get("csamt", 0.0))
        },
        "osup_nil_exmp": {
            "txval": round_cur(nil_exempt.get("txval", 0.0))
        },
        "isup_rev": {
            "txval": round_cur(rcm_inward.get("txval", 0.0)),
            "iamt": round_cur(rcm_inward.get("iamt", 0.0)),
            "camt": round_cur(rcm_inward.get("camt", 0.0)),
            "samt": round_cur(rcm_inward.get("samt", 0.0)),
            "csamt": round_cur(rcm_inward.get("csamt", 0.0))
        },
        "osup_nongst": {
            "txval": round_cur(non_gst.get("txval", 0.0))
        }
    }

    # Table 3.1.1: eco_dtls
    eco = input_data.get("eco_supplies", {})
    eco_pays = eco.get("eco_pays_tax") or eco.get("supplies_under_9_5") or {}
    eco_reported = eco.get("registered_through_eco") or eco.get("supplies_reported_by_eco") or {}
    eco_dtls = {
        "eco_m_sup": {
            "txval": round_cur(eco_pays.get("txval", 0.0)),
            "iamt": round_cur(eco_pays.get("iamt", 0.0)),
            "camt": round_cur(eco_pays.get("camt", 0.0)),
            "samt": round_cur(eco_pays.get("samt", 0.0)),
            "csamt": round_cur(eco_pays.get("csamt", 0.0))
        },
        "eco_sup": {
            "txval": round_cur(eco_reported.get("txval", 0.0))
        }
    }

    # Table 3.2: inter_sup
    inter_sup_rows = input_data.get("inter_state_supplies", [])
    inter_sup = {
        "unreg_details": [
            {
                "pos": str(r.get("pos", "")).zfill(2),
                "txval": round_cur(r.get("txval", 0.0)),
                "iamt": round_cur(r.get("iamt", 0.0))
            }
            for r in inter_sup_rows if r.get("supply_type") == "unregistered"
        ],
        "comp_details": [
            {
                "pos": str(r.get("pos", "")).zfill(2),
                "txval": round_cur(r.get("txval", 0.0)),
                "iamt": round_cur(r.get("iamt", 0.0))
            }
            for r in inter_sup_rows if r.get("supply_type") == "composition"
        ],
        "uin_details": [
            {
                "pos": str(r.get("pos", "")).zfill(2),
                "txval": round_cur(r.get("txval", 0.0)),
                "iamt": round_cur(r.get("iamt", 0.0))
            }
            for r in inter_sup_rows if r.get("supply_type") in ["uin", "uin_holders"]
        ]
    }

    # Table 4: itc_elg
    itc_input = input_data.get("itc", {})
    avail = itc_input.get("available", {})
    rev = itc_input.get("reversed", {})
    other = itc_input.get("other_details", {})

    itc_avl: list[dict[str, Any]] = [
        {"ty": "IMPG", "iamt": round_cur(avail.get("import_goods", {}).get("iamt", 0.0)), "csamt": round_cur(avail.get("import_goods", {}).get("csamt", 0.0))},
        {"ty": "IMPS", "iamt": round_cur(avail.get("import_services", {}).get("iamt", 0.0)), "csamt": round_cur(avail.get("import_services", {}).get("csamt", 0.0))},
        {"ty": "ISRC", "iamt": round_cur(avail.get("rcm_inward", {}).get("iamt", 0.0)), "camt": round_cur(avail.get("rcm_inward", {}).get("camt", 0.0)), "samt": round_cur(avail.get("rcm_inward", {}).get("samt", 0.0)), "csamt": round_cur(avail.get("rcm_inward", {}).get("csamt", 0.0))},
        {"ty": "ISD", "iamt": round_cur(avail.get("isd", {}).get("iamt", 0.0)), "camt": round_cur(avail.get("isd", {}).get("camt", 0.0)), "samt": round_cur(avail.get("isd", {}).get("samt", 0.0)), "csamt": round_cur(avail.get("isd", {}).get("csamt", 0.0))},
        {"ty": "OTH", "iamt": round_cur(avail.get("all_other", {}).get("iamt", 0.0)), "camt": round_cur(avail.get("all_other", {}).get("camt", 0.0)), "samt": round_cur(avail.get("all_other", {}).get("samt", 0.0)), "csamt": round_cur(avail.get("all_other", {}).get("csamt", 0.0))}
    ]

    itc_rev: list[dict[str, Any]] = [
        {"ty": "RUL", "iamt": round_cur(rev.get("permanent_17_5_rules", {}).get("iamt", 0.0)), "camt": round_cur(rev.get("permanent_17_5_rules", {}).get("camt", 0.0)), "samt": round_cur(rev.get("permanent_17_5_rules", {}).get("samt", 0.0)), "csamt": round_cur(rev.get("permanent_17_5_rules", {}).get("csamt", 0.0))},
        {"ty": "OTH", "iamt": round_cur(rev.get("temporary_others", {}).get("iamt", 0.0)), "camt": round_cur(rev.get("temporary_others", {}).get("camt", 0.0)), "samt": round_cur(rev.get("temporary_others", {}).get("samt", 0.0)), "csamt": round_cur(rev.get("temporary_others", {}).get("csamt", 0.0))}
    ]

    tot_avail_i = sum_tax_rows(itc_avl, "iamt")
    tot_avail_c = sum_tax_rows(itc_avl, "camt")
    tot_avail_s = sum_tax_rows(itc_avl, "samt")
    tot_avail_cs = sum_tax_rows(itc_avl, "csamt")

    tot_rev_i = sum_tax_rows(itc_rev, "iamt")
    tot_rev_c = sum_tax_rows(itc_rev, "camt")
    tot_rev_s = sum_tax_rows(itc_rev, "samt")
    tot_rev_cs = sum_tax_rows(itc_rev, "csamt")

    itc_net = {
        "iamt": round_cur(max(0.0, tot_avail_i - tot_rev_i)),
        "camt": round_cur(max(0.0, tot_avail_c - tot_rev_c)),
        "samt": round_cur(max(0.0, tot_avail_s - tot_rev_s)),
        "csamt": round_cur(max(0.0, tot_avail_cs - tot_rev_cs))
    }

    reclaimed_obj = other.get("reclaimed") or other.get("reclaimed_itc") or {}
    ineligible_obj = other.get("ineligible_16_4_pos") or other.get("ineligible_pos_16_4") or {}

    itc_inelg = [
        {"ty": "RUL", "iamt": round_cur(reclaimed_obj.get("iamt", 0.0)), "camt": round_cur(reclaimed_obj.get("camt", 0.0)), "samt": round_cur(reclaimed_obj.get("samt", 0.0)), "csamt": round_cur(reclaimed_obj.get("csamt", 0.0))},
        {"ty": "OTH", "iamt": round_cur(ineligible_obj.get("iamt", 0.0)), "camt": round_cur(ineligible_obj.get("camt", 0.0)), "samt": round_cur(ineligible_obj.get("samt", 0.0)), "csamt": round_cur(ineligible_obj.get("csamt", 0.0))}
    ]

    itc_elg = {
        "itc_avl": itc_avl,
        "itc_rev": itc_rev,
        "itc_net": itc_net,
        "itc_inelg": itc_inelg
    }

    # Table 5: inward_sup
    inward_exmp = input_data.get("inward_exempt_nil_non_gst", {})
    comp_exempt = inward_exmp.get("from_composition_exempt") or inward_exmp.get("composition_nil_exempt") or {}
    non_gst_sup = inward_exmp.get("non_gst") or inward_exmp.get("non_gst_inward") or {}

    comp_inter = comp_exempt.get("inter") if "inter" in comp_exempt else comp_exempt.get("inter_state", 0.0)
    comp_intra = comp_exempt.get("intra") if "intra" in comp_exempt else comp_exempt.get("intra_state", 0.0)
    ng_inter = non_gst_sup.get("inter") if "inter" in non_gst_sup else non_gst_sup.get("inter_state", 0.0)
    ng_intra = non_gst_sup.get("intra") if "intra" in non_gst_sup else non_gst_sup.get("intra_state", 0.0)

    inward_sup = {
        "isup_details": [
            {
                "ty": "GST",
                "inter": round_cur(comp_inter),
                "intra": round_cur(comp_intra)
            },
            {
                "ty": "NONGST",
                "inter": round_cur(ng_inter),
                "intra": round_cur(ng_intra)
            }
        ]
    }

    # Table 6.1: tx_pmt (Tax Payment & Optimal Set-off)
    opt_res = optimize_from_input_dict(input_data)
    m = opt_res["setoff_matrix"]
    cash = opt_res["net_cash_required"]

    tx_pmt = {
        "tx_py": [
            {
                "trans_typ": "TAX",
                "iamt": round_cur(outward.get("taxable", {}).get("iamt", 0.0) + outward.get("zero_rated", {}).get("iamt", 0.0)),
                "camt": round_cur(outward.get("taxable", {}).get("camt", 0.0)),
                "samt": round_cur(outward.get("taxable", {}).get("samt", 0.0)),
                "csamt": round_cur(outward.get("taxable", {}).get("csamt", 0.0) + outward.get("zero_rated", {}).get("csamt", 0.0)),
                "paid_itc": {
                    "iamt": round_cur(m["igst_liability"]["paid_by_igst_credit"] + m["cgst_liability"]["paid_by_igst_credit"] + m["sgst_liability"]["paid_by_igst_credit"]),
                    "camt": round_cur(m["cgst_liability"]["paid_by_cgst_credit"] + m["igst_liability"]["paid_by_cgst_credit"]),
                    "samt": round_cur(m["sgst_liability"]["paid_by_sgst_credit"] + m["igst_liability"]["paid_by_sgst_credit"]),
                    "csamt": round_cur(m["cess_liability"]["paid_by_cess_credit"])
                },
                "paid_cash": {
                    "iamt": round_cur(cash.get("iamt", 0.0)),
                    "camt": round_cur(cash.get("camt", 0.0)),
                    "samt": round_cur(cash.get("samt", 0.0)),
                    "csamt": round_cur(cash.get("csamt", 0.0))
                },
                "tx_pmt_tax": {
                    "i_pd_i": round_cur(m["igst_liability"]["paid_by_igst_credit"]),
                    "i_pd_c": round_cur(m["cgst_liability"]["paid_by_igst_credit"]),
                    "i_pd_s": round_cur(m["sgst_liability"]["paid_by_igst_credit"]),
                    "c_pd_c": round_cur(m["cgst_liability"]["paid_by_cgst_credit"]),
                    "c_pd_i": round_cur(m["igst_liability"]["paid_by_cgst_credit"]),
                    "s_pd_s": round_cur(m["sgst_liability"]["paid_by_sgst_credit"]),
                    "s_pd_i": round_cur(m["igst_liability"]["paid_by_sgst_credit"]),
                    "cs_pd_cs": round_cur(m["cess_liability"]["paid_by_cess_credit"])
                },
                "tx_pmt_cash": {
                    "iamt": round_cur(cash.get("iamt", 0.0)),
                    "camt": round_cur(cash.get("camt", 0.0)),
                    "samt": round_cur(cash.get("samt", 0.0)),
                    "csamt": round_cur(cash.get("csamt", 0.0))
                },
                "liab_ldg_id": 0
            }
        ]
    }

    return {
        "version": "gstr-wala-gstr3b-1.0",
        "gstin": gstin,
        "ret_period": ret_period,
        "sup_details": sup_details,
        "eco_dtls": eco_dtls,
        "inter_sup": inter_sup,
        "itc_elg": itc_elg,
        "inward_sup": inward_sup,
        "tx_pmt": tx_pmt
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_gstr3b_json.py <gstr3b_input.json> [output_portal.json]")
        sys.exit(1)

    in_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "gstr3b_portal.json"


    if not os.path.exists(in_file):
        sys.exit(f"Error: File '{in_file}' not found.")

    with open(in_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    portal_json = generate_portal_gstr3b(data)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(portal_json, f, indent=2)

    print(f"SUCCESS: Generated GSTR-3B portal upload JSON -> '{out_file}'")


if __name__ == "__main__":
    main()
