#!/usr/bin/env python3
"""Generates official GSTN Portal offline upload JSON for GSTR-1.

Transforms validated canonical GSTR-1 input into the exact JSON structure required by
the GST Portal Returns Offline Tool shape:
  - Table 4A/4B/4C/6B/6C: B2B Invoices (grouped by ctin)
  - Table 5A/5B: B2CL (Inter-state unregistered > ₹1,00,000, grouped by pos)
  - Table 6A: Exports (WPAY / WOPAY)
  - Table 7: B2CS (Intra-state & Inter-state <= ₹1,00,000)
  - Table 8: Nil/Exempt/Non-GST supplies
  - Table 9B: CDNR (Registered Credit/Debit Notes grouped by ctin) & CDNUR (Unregistered)
  - Table 11A/11B: Advances Received & Adjusted
  - Table 12: HSN-wise summary (Table 12A B2B & Table 12B B2C)
  - Table 13: Documents issued summary

Usage:
  python3 scripts/generate_gstr1_json.py <gstr1_input.json> [output_portal.json]
"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any

from scripts.gst_engine import compute_gstr1_tables, round_cur
from scripts.validate_gst_input import validate_gstr1_input

# Document type name map for Table 13
DOC_NUM_NAMES = {
    1: "Invoices for outward supply",
    2: "Invoices for inward supply from unregistered person",
    3: "Revised Invoice",
    4: "Debit Note",
    5: "Credit Note",
    6: "Receipt voucher",
    7: "Payment Voucher",
    8: "Refund voucher",
    9: "Delivery Challan for job work",
    10: "Delivery Challan for supply on approval",
    11: "Delivery Challan in case of liquid gas",
    12: "Other Delivery Challans"
}


# Payload version marker. This is a gstr-wala provenance tag, NOT the GSTN
# offline-tool token — if the portal rejects direct upload, regenerate via the
# official Returns Offline Tool or pass portal_version with the tool's value.
GSTR1_PORTAL_VERSION = "gstr-wala-gstr1-1.0"


def generate_portal_gstr1(input_data: dict[str, Any], portal_version: str | None = None) -> dict[str, Any]:
    """Transforms canonical input data into GSTN offline-tool-shaped GSTR-1 JSON."""
    comp = compute_gstr1_tables(input_data)

    gstin = comp["gstin"]
    fp = comp["fp"]
    gt = float(input_data.get("gt", 0.0))
    cur_gt = float(input_data.get("cur_gt", 0.0))

    # 1. Format B2B (Group by ctin)
    b2b_by_ctin: dict[str, list[dict[str, Any]]] = {}
    for inv in comp["table_4_b2b"]:
        ctin = inv.get("ctin", "").strip().upper()
        if ctin not in b2b_by_ctin:
            b2b_by_ctin[ctin] = []

        itms = []
        for itm_idx, itm in enumerate(inv.get("items", [])):
            itms.append({
                "num": itm_idx + 1,
                "itm_det": {
                    "txval": round_cur(itm.get("txval", 0.0)),
                    "rt": float(itm.get("rt", 0.0)),
                    "iamt": round_cur(itm.get("iamt", 0.0)),
                    "camt": round_cur(itm.get("camt", 0.0)),
                    "samt": round_cur(itm.get("samt", 0.0)),
                    "csamt": round_cur(itm.get("csamt", 0.0))
                }
            })

        b2b_by_ctin[ctin].append({
            "inum": inv.get("inum"),
            "idt": inv.get("idt"),
            "val": round_cur(inv.get("val", 0.0)),
            "pos": inv.get("pos"),
            "rchrg": inv.get("rchrg", "N"),
            "inv_typ": inv.get("inv_typ", "R"),
            "itms": itms
        })

    b2b_payload = [{"ctin": ctin, "inv": invs} for ctin, invs in sorted(b2b_by_ctin.items())]

    # 2. Format B2CL (Group by pos)
    b2cl_by_pos: dict[str, list[dict[str, Any]]] = {}
    for inv in comp["table_5_b2cl"]:
        pos = inv.get("pos", "")
        if pos not in b2cl_by_pos:
            b2cl_by_pos[pos] = []

        itms = []
        for itm_idx, itm in enumerate(inv.get("items", [])):
            itms.append({
                "num": itm_idx + 1,
                "itm_det": {
                    "txval": round_cur(itm.get("txval", 0.0)),
                    "rt": float(itm.get("rt", 0.0)),
                    "iamt": round_cur(itm.get("iamt", 0.0)),
                    "csamt": round_cur(itm.get("csamt", 0.0))
                }
            })

        b2cl_by_pos[pos].append({
            "inum": inv.get("inum"),
            "idt": inv.get("idt"),
            "val": round_cur(inv.get("val", 0.0)),
            "itms": itms
        })

    b2cl_payload = [{"pos": pos, "inv": invs} for pos, invs in sorted(b2cl_by_pos.items())]

    # 3. Format B2CS
    b2cs_payload = []
    for row in comp["table_7_b2cs"]:
        entry = {
            "sply_ty": row["sply_ty"],
            "pos": row["pos"],
            "typ": row["typ"],
            "rt": row["rt"],
            "txval": row["txval"],
            "iamt": row["iamt"],
            "camt": row["camt"],
            "samt": row["samt"],
            "csamt": row["csamt"]
        }
        if "etin" in row:
            entry["etin"] = row["etin"]
        b2cs_payload.append(entry)

    # 4. Format CDNR (Registered Credit/Debit Notes grouped by ctin)
    cdnr_by_ctin: dict[str, list[dict[str, Any]]] = {}
    cdnur_payload: list[dict[str, Any]] = []

    for note in input_data.get("credit_debit_notes", []):
        ctin = note.get("ctin")
        itms = []
        for itm_idx, itm in enumerate(note.get("items", [])):
            itms.append({
                "num": itm_idx + 1,
                "itm_det": {
                    "txval": round_cur(itm.get("txval", 0.0)),
                    "rt": float(itm.get("rt", 0.0)),
                    "iamt": round_cur(itm.get("iamt", 0.0)),
                    "camt": round_cur(itm.get("camt", 0.0)),
                    "samt": round_cur(itm.get("samt", 0.0)),
                    "csamt": round_cur(itm.get("csamt", 0.0))
                }
            })

        if ctin:
            ctin_upper = ctin.strip().upper()
            if ctin_upper not in cdnr_by_ctin:
                cdnr_by_ctin[ctin_upper] = []
            cdnr_by_ctin[ctin_upper].append({
                "nt_num": note.get("nt_num"),
                "nt_dt": note.get("nt_dt"),
                "ntty": note.get("ntty", "C"),
                "inum": note.get("inum"),
                "idt": note.get("idt"),
                "val": round_cur(note.get("val", 0.0)),
                "pos": note.get("pos"),
                "rchrg": note.get("rchrg", "N"),
                "itms": itms
            })
        else:
            cdnur_payload.append({
                "typ": note.get("typ", "B2CL"),
                "nt_num": note.get("nt_num"),
                "nt_dt": note.get("nt_dt"),
                "ntty": note.get("ntty", "C"),
                "inum": note.get("inum"),
                "idt": note.get("idt"),
                "val": round_cur(note.get("val", 0.0)),
                "pos": note.get("pos"),
                "itms": itms
            })

    cdnr_payload = [{"ctin": ctin, "nt": notes} for ctin, notes in sorted(cdnr_by_ctin.items())]

    # 5. Format Exports (Table 6A) — group by exp_typ per portal spec
    from collections import defaultdict

    exp_by_typ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for exp_inv in comp["table_6_exp"]:
        exp_by_typ[exp_inv.get("exp_typ", "WOPAY")].append(exp_inv)
    exp_payload = []
    for exp_typ, invs in sorted(exp_by_typ.items()):
        inv_payload = []
        for exp_inv in invs:
            itms = []
            for itm in exp_inv.get("items", []):
                itms.append({
                    "txval": round_cur(itm.get("txval", 0.0)),
                    "rt": float(itm.get("rt", 0.0)),
                    "iamt": round_cur(itm.get("iamt", 0.0)),
                    "csamt": round_cur(itm.get("csamt", 0.0))
                })
            inv_payload.append({
                "inum": exp_inv.get("inum"),
                "idt": exp_inv.get("idt"),
                "val": round_cur(exp_inv.get("val", 0.0)),
                "sbpcode": exp_inv.get("port_code", ""),
                "sbnum": exp_inv.get("sb_num", ""),
                "sbdt": exp_inv.get("sb_dt", ""),
                "itms": itms
            })
        exp_payload.append({"exp_typ": exp_typ, "inv": inv_payload})

    # 6. Format HSN Summary (Table 12)
    hsn_data = []
    for h in comp["table_12_hsn"]:
        hsn_data.append({
            "num": h["num"],
            "hsn_sc": h["hsn_sc"],
            "desc": h["desc"],
            "uqc": h["uqc"],
            "qty": h["qty"],
            "val": h["val"],
            "txval": h["txval"],
            "rt": float(h.get("rt", 0.0)),
            "iamt": h["iamt"],
            "camt": h["camt"],
            "samt": h["samt"],
            "csamt": h["csamt"]
        })

    # 7. Format Documents Summary (Table 13)
    doc_det = []
    for doc in comp["table_13_docs"]:
        d_num = int(doc.get("doc_num", 1))
        d_name = DOC_NUM_NAMES.get(d_num, "Invoices for outward supply")
        doc_det.append({
            "doc_num": d_num,
            "doc_typ": d_name,
            "docs": [{
                "num": 1,
                "from": doc.get("from", ""),
                "to": doc.get("to", ""),
                "totnum": doc.get("totnum", 0),
                "canc": doc.get("canc", 0),
                "net_issue": doc.get("net_issue", 0)
            }]
        })

    # 8. Format Table 8 Nil/Exempt/Non-GST supplies
    raw_exemp = comp.get("table_8_nil_exempt", {})
    exemp_payload = {
        "nil_supplies": {
            "inter_reg": round_cur(raw_exemp.get("nil_inter_reg", 0.0)),
            "inter_unreg": round_cur(raw_exemp.get("nil_inter_unreg", 0.0)),
            "intra_reg": round_cur(raw_exemp.get("nil_intra_reg", 0.0)),
            "intra_unreg": round_cur(raw_exemp.get("nil_intra_unreg", 0.0))
        },
        "exptd_supplies": {
            "inter_reg": round_cur(raw_exemp.get("expt_inter_reg", 0.0)),
            "inter_unreg": round_cur(raw_exemp.get("expt_inter_unreg", 0.0)),
            "intra_reg": round_cur(raw_exemp.get("expt_intra_reg", 0.0)),
            "intra_unreg": round_cur(raw_exemp.get("expt_intra_unreg", 0.0))
        },
        "ngsupplies": {
            "inter_reg": round_cur(raw_exemp.get("ngsup_inter_reg", 0.0)),
            "inter_unreg": round_cur(raw_exemp.get("ngsup_inter_unreg", 0.0)),
            "intra_reg": round_cur(raw_exemp.get("ngsup_intra_reg", 0.0)),
            "intra_unreg": round_cur(raw_exemp.get("ngsup_intra_unreg", 0.0))
        }
    }

    # Complete offline-tool-shaped portal JSON
    return {
        "version": portal_version or GSTR1_PORTAL_VERSION,
        "gstin": gstin,
        "fp": fp,
        "gt": gt,
        "cur_gt": cur_gt,
        "b2b": b2b_payload,
        "b2cl": b2cl_payload,
        "b2cs": b2cs_payload,
        "cdnr": cdnr_payload,
        "cdnur": cdnur_payload,
        "exp": exp_payload,
        "at": comp["table_11_advances"]["received"],
        "atadj": comp["table_11_advances"]["adjusted"],
        "exemp": exemp_payload,
        "hsn": {
            "data": hsn_data
        },
        "doc_issue": {
            "doc_det": doc_det
        }
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_gstr1_json.py <gstr1_input.json> [output_portal.json]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "gstr1_portal.json"


    if not os.path.exists(input_file):
        sys.exit(f"Error: File '{input_file}' not found.")

    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)

    val_res = validate_gstr1_input(data)
    if not val_res.is_valid:
        print(f"Error: Validation failed with {len(val_res.errors)} error(s):")
        for e in val_res.errors:
            print(f"  - {e}")
        sys.exit(1)

    portal_json = generate_portal_gstr1(data)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(portal_json, f, indent=2)

    print(f"SUCCESS: Generated official GSTR-1 portal JSON -> '{output_file}'")
    print(f"Summary: {len(portal_json['b2b'])} B2B entities, {len(portal_json['b2cl'])} B2CL groups, {len(portal_json['b2cs'])} B2CS lines, {len(portal_json['hsn']['data'])} HSN lines.")


if __name__ == "__main__":
    main()
