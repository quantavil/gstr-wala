#!/usr/bin/env python3
"""GSTR-2B vs Purchase Register (Books) 2-Way Reconciliation Engine.

Performs:
  - Alphanumeric invoice normalization (strips slashes, dashes, whitespace, leading zeroes)
  - Multi-tier matching: EXACT_MATCH, TOLERANCE_MATCH (+/- ₹1), VALUE_MISMATCH, IN_BOOKS_ONLY, IN_2B_ONLY
  - Section 17(5) Blocked Credit identification -> Table 4(B)(1)
  - Rule 37 (180-day non-payment) & Rule 37A tracking -> Table 4(B)(2)
  - Inward RCM supplies (rev == 'Y') -> Table 4(A)(3)
  - Import of Goods (impg) -> Table 4(A)(1)
  - ISD Invoices (isd) -> Table 4(A)(4)
  - Credit Notes (cdnr) handling (reduces gross ITC)
  - 2B Ineligible credit (itcavl == 'N') -> Table 4(D)(2)
  - Auto-derivation of GSTR-3B Table 4 Eligible/Ineligible ITC fields

Usage:
  python3 scripts/reconcile_2b.py <purchase_register.json> <gstr2b.json> [--json]
"""

import json
import os
import re
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List, Optional, Set, Tuple


def round_cur(val: float) -> float:
    return round(float(val) + 1e-9, 2)


def normalize_inum(inum: str) -> str:
    """Normalizes invoice numbers for robust fuzzy matching."""
    if not inum:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(inum)).upper()
    # Strip leading zeroes at start or after alphabetic prefix
    normalized = re.sub(r"(^|[A-Z]+)0+(\d+)", r"\1\2", cleaned)
    return normalized


def extract_trailing_digits(s: str) -> str:
    """Extracts trailing digits stripped of leading zeroes."""
    m = re.search(r"(\d+)$", s)
    if m:
        digits = m.group(1).lstrip("0")
        return digits if digits else "0"
    return s


def flatten_gstr2b(g2b_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flattens nested official GSTR-2B JSON into a flat list of normalized invoice records."""
    records = []
    data_block = g2b_data.get("data", {}).get("docdata", g2b_data.get("docdata", g2b_data))
    
    # 1. Process B2B Invoices
    b2b_list = data_block.get("b2b", [])
    for supplier in b2b_list:
        ctin = supplier.get("ctin", "").strip().upper()
        trdnm = supplier.get("trdnm", "")
        inv_list = supplier.get("inv", [])
        for inv in inv_list:
            inum = str(inv.get("inum", "")).strip()
            idt = inv.get("dt", "")
            val = float(inv.get("val", 0.0))
            pos = inv.get("pos", "")
            rchrg = inv.get("rev", "N")
            itcavl = inv.get("itcavl", "Y")
            rsn = inv.get("rsn", "")
            items = inv.get("items", [])

            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                txval += float(itm.get("txval", 0.0))
                iamt += float(itm.get("iamt", 0.0))
                camt += float(itm.get("camt", 0.0))
                samt += float(itm.get("samt", 0.0))
                csamt += float(itm.get("csamt", 0.0))

            norm = normalize_inum(inum)
            records.append({
                "source": "GSTR-2B",
                "section": "B2B",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": inum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": idt,
                "val": val,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 2. Process Credit / Debit Notes (cdnr)
    cdnr_list = data_block.get("cdnr", [])
    for supplier in cdnr_list:
        ctin = supplier.get("ctin", "").strip().upper()
        trdnm = supplier.get("trdnm", "")
        nt_list = supplier.get("nt", [])
        for nt in nt_list:
            nt_num = str(nt.get("nt_num", "")).strip()
            nt_dt = nt.get("dt", "")
            ntty = nt.get("ntty", "C")  # C: Credit Note (decreases ITC), D: Debit Note (increases ITC)
            val = float(nt.get("val", 0.0))
            pos = nt.get("pos", "")
            rchrg = nt.get("rev", "N")
            itcavl = nt.get("itcavl", "Y")
            rsn = nt.get("rsn", "")
            items = nt.get("items", [])

            sign = -1.0 if ntty == "C" else 1.0
            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                txval += float(itm.get("txval", 0.0)) * sign
                iamt += float(itm.get("iamt", 0.0)) * sign
                camt += float(itm.get("camt", 0.0)) * sign
                samt += float(itm.get("samt", 0.0)) * sign
                csamt += float(itm.get("csamt", 0.0)) * sign

            norm = normalize_inum(nt_num)
            records.append({
                "source": "GSTR-2B",
                "section": "CDNR",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": nt_num,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": nt_dt,
                "val": val * sign,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "ntty": ntty,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 3. Process Input Service Distributor (isd)
    for isd_sup in data_block.get("isd", []):
        ctin = isd_sup.get("ctin", "").strip().upper()
        for doc in isd_sup.get("doclist", []):
            docnum = str(doc.get("docnum", "")).strip()
            iamt = float(doc.get("iamt", 0.0))
            camt = float(doc.get("camt", 0.0))
            samt = float(doc.get("samt", 0.0))
            csamt = float(doc.get("csamt", 0.0))
            norm = normalize_inum(docnum)
            records.append({
                "source": "GSTR-2B",
                "section": "ISD",
                "ctin": ctin,
                "inum": docnum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": doc.get("docdt", ""),
                "itcavl": doc.get("itcavl", "Y"),
                "txval": 0.0,
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 4. Process Import of Goods (impg & impgsez)
    for imp in data_block.get("impg", []) + data_block.get("impgsez", []):
        for boe in imp.get("boe", []):
            boenum = str(boe.get("boenum", "")).strip()
            txval, iamt, csamt = 0.0, 0.0, 0.0
            for itm in boe.get("items", []):
                txval += float(itm.get("txval", 0.0))
                iamt += float(itm.get("iamt", 0.0))
                csamt += float(itm.get("csamt", 0.0))
            norm = normalize_inum(boenum)
            records.append({
                "source": "GSTR-2B",
                "section": "IMPG",
                "ctin": "ICEGATE",
                "inum": boenum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": boe.get("boedt", ""),
                "itcavl": boe.get("itcavl", "Y"),
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": 0.0,
                "samt": 0.0,
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + csamt)
            })

    return records


def reconcile(purchase_register: List[Dict[str, Any]], gstr2b_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Reconciles Purchase Register against GSTR-2B records."""
    g2b_records = flatten_gstr2b(gstr2b_raw)

    matched: List[Dict[str, Any]] = []
    tolerance_matched: List[Dict[str, Any]] = []
    value_mismatches: List[Dict[str, Any]] = []
    in_books_only: List[Dict[str, Any]] = []
    blocked_17_5: List[Dict[str, Any]] = []
    rule_37_reversals: List[Dict[str, Any]] = []
    ineligible_2b: List[Dict[str, Any]] = []
    rcm_inward_2b: List[Dict[str, Any]] = []
    isd_inward_2b: List[Dict[str, Any]] = []
    impg_inward_2b: List[Dict[str, Any]] = []

    matched_2b_indices: Set[int] = set()

    # Index 2B records by (ctin, norm_inum) and (ctin, trailing_digits)
    g2b_exact_map: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    g2b_trailing_map: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}

    for idx, rec in enumerate(g2b_records):
        key_exact = (rec["ctin"], rec["norm_inum"])
        if key_exact not in g2b_exact_map:
            g2b_exact_map[key_exact] = []
        g2b_exact_map[key_exact].append((idx, rec))

        key_trailing = (rec["ctin"], rec["trailing_digits"])
        if key_trailing not in g2b_trailing_map:
            g2b_trailing_map[key_trailing] = []
        g2b_trailing_map[key_trailing].append((idx, rec))

    for pr_inv in purchase_register:
        ctin = pr_inv.get("ctin", "").strip().upper()
        inum = str(pr_inv.get("inum", "")).strip()
        norm_in = normalize_inum(inum)
        trail_in = extract_trailing_digits(norm_in)

        txval = float(pr_inv.get("txval", 0.0))
        iamt = float(pr_inv.get("iamt", 0.0))
        camt = float(pr_inv.get("camt", 0.0))
        samt = float(pr_inv.get("samt", 0.0))
        csamt = float(pr_inv.get("csamt", 0.0))
        tot_tax = round_cur(iamt + camt + samt + csamt)

        is_blocked = pr_inv.get("is_blocked_17_5", False) or (pr_inv.get("hsn_sc") in ["8702", "8703", "9963", "9965"])
        is_unpaid_180 = pr_inv.get("unpaid_days", 0) > 180 or pr_inv.get("rule_37_reversal", False)

        # 1. First try exact norm_inum match
        candidates = [
            (idx, rec) for idx, rec in g2b_exact_map.get((ctin, norm_in), [])
            if idx not in matched_2b_indices
        ]

        # 2. If no exact match, try trailing digits match
        if not candidates:
            candidates = [
                (idx, rec) for idx, rec in g2b_trailing_map.get((ctin, trail_in), [])
                if idx not in matched_2b_indices
            ]

        if not candidates:
            # Not found in 2B
            item_record = {**pr_inv, "reason": "Missing in GSTR-2B (Supplier not filed GSTR-1 yet)"}
            in_books_only.append(item_record)
            continue

        # Sort candidates by tax amount and taxable value proximity to books invoice
        candidates.sort(
            key=lambda c: (
                abs(tot_tax - c[1]["tot_tax"]),
                abs(txval - c[1]["txval"])
            )
        )
        best_idx, best_2b = candidates[0]
        matched_2b_indices.add(best_idx)

        diff_tax = round_cur(abs(tot_tax - best_2b["tot_tax"]))
        diff_txval = round_cur(abs(txval - best_2b["txval"]))

        match_entry = {
            "books_invoice": pr_inv,
            "gstr2b_invoice": best_2b,
            "tax_diff": diff_tax,
            "txval_diff": diff_txval
        }

        # Check RCM Inward supplies (reported under Table 4(A)(3), NOT Table 4(A)(5))
        if best_2b.get("rchrg") == "Y":
            if best_2b.get("itcavl") == "N":
                ineligible_2b.append({**match_entry, "reason": f"GSTR-2B Marked Ineligible: {best_2b.get('rsn', 'Restriction')}"})
            elif is_blocked:
                blocked_17_5.append({**match_entry, "reason": "Section 17(5) Blocked Credit"})
            else:
                rcm_inward_2b.append(match_entry)
            continue

        # Check Ineligible in 2B flag
        if best_2b.get("itcavl") == "N":
            ineligible_2b.append({**match_entry, "reason": f"GSTR-2B Marked Ineligible: {best_2b.get('rsn', 'Restriction')}"})
            continue

        if is_blocked:
            blocked_17_5.append({**match_entry, "reason": "Section 17(5) Blocked Credit"})
            continue

        if is_unpaid_180:
            rule_37_reversals.append({**match_entry, "reason": "Rule 37 Reversal (Unpaid > 180 days)"})
            continue

        if diff_tax == 0.0 and diff_txval == 0.0:
            matched.append(match_entry)
        elif diff_tax <= 1.0 and diff_txval <= 2.0:
            tolerance_matched.append(match_entry)
        else:
            value_mismatches.append(match_entry)

    # In 2B Only (Unmatched 2B records)
    in_2b_only = []
    unrecorded_purchases = []
    for idx, rec in enumerate(g2b_records):
        if idx not in matched_2b_indices:
            in_2b_only.append(rec)
            if rec["section"] == "IMPG":
                impg_inward_2b.append(rec)
            elif rec["section"] == "ISD":
                isd_inward_2b.append(rec)
            else:
                unrecorded_purchases.append(rec)

    # Calculate GSTR-3B Table 4 Amounts
    # Table 4(A)(1) Import of Goods
    impg_i = sum(r.get("iamt", 0.0) for r in impg_inward_2b)
    impg_cs = sum(r.get("csamt", 0.0) for r in impg_inward_2b)

    # Table 4(A)(3) Inward RCM
    rcm_txval = sum(m["gstr2b_invoice"].get("txval", 0.0) for m in rcm_inward_2b)
    rcm_i = sum(m["gstr2b_invoice"]["iamt"] for m in rcm_inward_2b)
    rcm_c = sum(m["gstr2b_invoice"]["camt"] for m in rcm_inward_2b)
    rcm_s = sum(m["gstr2b_invoice"]["samt"] for m in rcm_inward_2b)
    rcm_cs = sum(m["gstr2b_invoice"]["csamt"] for m in rcm_inward_2b)

    # Table 4(A)(4) ISD
    isd_i = sum(r.get("iamt", 0.0) for r in isd_inward_2b)
    isd_c = sum(r.get("camt", 0.0) for r in isd_inward_2b)
    isd_s = sum(r.get("samt", 0.0) for r in isd_inward_2b)
    isd_cs = sum(r.get("csamt", 0.0) for r in isd_inward_2b)

    # Table 4(A)(5) All Other ITC (excluding RCM/ISD/IMPG which are in 4A1, 4A3, 4A4)
    claim_i = sum(m["gstr2b_invoice"]["iamt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "ISD"]) + sum(min(m["books_invoice"].get("iamt", 0), m["gstr2b_invoice"]["iamt"]) for m in value_mismatches)
    claim_c = sum(m["gstr2b_invoice"]["camt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "ISD"]) + sum(min(m["books_invoice"].get("camt", 0), m["gstr2b_invoice"]["camt"]) for m in value_mismatches)
    claim_s = sum(m["gstr2b_invoice"]["samt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "ISD"]) + sum(min(m["books_invoice"].get("samt", 0), m["gstr2b_invoice"]["samt"]) for m in value_mismatches)
    claim_cs = sum(m["gstr2b_invoice"]["csamt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "ISD"]) + sum(min(m["books_invoice"].get("csamt", 0), m["gstr2b_invoice"]["csamt"]) for m in value_mismatches)

    # Permanent Reversal Table 4(B)(1)
    rev_perm_i = sum(b["gstr2b_invoice"]["iamt"] for b in blocked_17_5)
    rev_perm_c = sum(b["gstr2b_invoice"]["camt"] for b in blocked_17_5)
    rev_perm_s = sum(b["gstr2b_invoice"]["samt"] for b in blocked_17_5)
    rev_perm_cs = sum(b["gstr2b_invoice"]["csamt"] for b in blocked_17_5)

    # Temporary Reversal Table 4(B)(2)
    rev_temp_i = sum(r["gstr2b_invoice"]["iamt"] for r in rule_37_reversals)
    rev_temp_c = sum(r["gstr2b_invoice"]["camt"] for r in rule_37_reversals)
    rev_temp_s = sum(r["gstr2b_invoice"]["samt"] for r in rule_37_reversals)
    rev_temp_cs = sum(r["gstr2b_invoice"]["csamt"] for r in rule_37_reversals)

    # Ineligible Table 4(D)(2)
    inelg_i = sum(e["gstr2b_invoice"]["iamt"] for e in ineligible_2b)
    inelg_c = sum(e["gstr2b_invoice"]["camt"] for e in ineligible_2b)
    inelg_s = sum(e["gstr2b_invoice"]["samt"] for e in ineligible_2b)
    inelg_cs = sum(e["gstr2b_invoice"]["csamt"] for e in ineligible_2b)

    # Deferred ITC (Missing in 2B)
    def_i = sum(float(b.get("iamt", 0.0)) for b in in_books_only)
    def_c = sum(float(b.get("camt", 0.0)) for b in in_books_only)
    def_s = sum(float(b.get("samt", 0.0)) for b in in_books_only)
    def_cs = sum(float(b.get("csamt", 0.0)) for b in in_books_only)

    return {
        "summary": {
            "total_books_invoices": len(purchase_register),
            "total_2b_invoices": len(g2b_records),
            "exact_matched_count": len(matched),
            "tolerance_matched_count": len(tolerance_matched),
            "value_mismatch_count": len(value_mismatches),
            "in_books_only_count": len(in_books_only),
            "in_2b_only_count": len(unrecorded_purchases),
            "total_unmatched_2b_records": len(in_2b_only),
            "blocked_17_5_count": len(blocked_17_5),
            "rule_37_count": len(rule_37_reversals),
            "ineligible_2b_count": len(ineligible_2b),
            "rcm_inward_count": len(rcm_inward_2b),
            "isd_count": len(isd_inward_2b),
            "impg_count": len(impg_inward_2b)
        },
        "gstr3b_table_4_auto_population": {
            "table_4_a_1_import_goods": {
                "iamt": round_cur(impg_i), "csamt": round_cur(impg_cs), "total": round_cur(impg_i + impg_cs)
            },
            "table_4_a_3_rcm_inward": {
                "txval": round_cur(rcm_txval),
                "iamt": round_cur(rcm_i), "camt": round_cur(rcm_c), "samt": round_cur(rcm_s), "csamt": round_cur(rcm_cs),
                "total": round_cur(rcm_i + rcm_c + rcm_s + rcm_cs)
            },
            "table_4_a_4_isd": {
                "iamt": round_cur(isd_i), "camt": round_cur(isd_c), "samt": round_cur(isd_s), "csamt": round_cur(isd_cs),
                "total": round_cur(isd_i + isd_c + isd_s + isd_cs)
            },
            "table_4_a_5_all_other_itc": {
                "iamt": round_cur(claim_i), "camt": round_cur(claim_c), "samt": round_cur(claim_s), "csamt": round_cur(claim_cs),
                "total": round_cur(claim_i + claim_c + claim_s + claim_cs)
            },
            "table_4_b_1_permanent_reversals_17_5": {
                "iamt": round_cur(rev_perm_i), "camt": round_cur(rev_perm_c), "samt": round_cur(rev_perm_s), "csamt": round_cur(rev_perm_cs),
                "total": round_cur(rev_perm_i + rev_perm_c + rev_perm_s + rev_perm_cs)
            },
            "table_4_b_2_temporary_reversals_rule37": {
                "iamt": round_cur(rev_temp_i), "camt": round_cur(rev_temp_c), "samt": round_cur(rev_temp_s), "csamt": round_cur(rev_temp_cs),
                "total": round_cur(rev_temp_i + rev_temp_c + rev_temp_s + rev_temp_cs)
            },
            "table_4_c_net_itc": {
                "iamt": round_cur(claim_i + impg_i + isd_i - rev_perm_i - rev_temp_i),
                "camt": round_cur(claim_c + isd_c - rev_perm_c - rev_temp_c),
                "samt": round_cur(claim_s + isd_s - rev_perm_s - rev_temp_s),
                "csamt": round_cur(claim_cs + impg_cs + isd_cs - rev_perm_cs - rev_temp_cs),
                "total": round_cur(
                    (claim_i + impg_i + isd_i - rev_perm_i - rev_temp_i) +
                    (claim_c + isd_c - rev_perm_c - rev_temp_c) +
                    (claim_s + isd_s - rev_perm_s - rev_temp_s) +
                    (claim_cs + impg_cs + isd_cs - rev_perm_cs - rev_temp_cs)
                )
            },
            "table_4_d_2_ineligible_16_4": {
                "iamt": round_cur(inelg_i), "camt": round_cur(inelg_c), "samt": round_cur(inelg_s), "csamt": round_cur(inelg_cs),
                "total": round_cur(inelg_i + inelg_c + inelg_s + inelg_cs)
            },
            "deferred_itc_missing_in_2b": {
                "iamt": round_cur(def_i), "camt": round_cur(def_c), "samt": round_cur(def_s), "csamt": round_cur(def_cs),
                "total": round_cur(def_i + def_c + def_s + def_cs)
            }
        },
        "details": {
            "exact_matched": matched,
            "tolerance_matched": tolerance_matched,
            "value_mismatches": value_mismatches,
            "in_books_only": in_books_only,
            "in_2b_only": in_2b_only,
            "blocked_17_5": blocked_17_5,
            "rule_37_reversals": rule_37_reversals,
            "ineligible_2b": ineligible_2b
        }
    }


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    data_lines = []
    for row in rows:
        data_lines.append("| " + " | ".join(str(val).rjust(col_widths[i]) if isinstance(val, (int, float)) else str(val).ljust(col_widths[i]) for i, val in enumerate(row)) + " |")
    return "\n".join([header_line, sep_line] + data_lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 reconcile_2b.py <purchase_register.json> <gstr2b.json> [--json]")
        sys.exit(1)

    pr_file = sys.argv[1]
    g2b_file = sys.argv[2]
    json_output = "--json" in sys.argv

    if not os.path.exists(pr_file) or not os.path.exists(g2b_file):
        sys.exit("Error: Input files not found.")

    with open(pr_file, "r", encoding="utf-8") as f:
        pr_data = json.load(f)
    with open(g2b_file, "r", encoding="utf-8") as f:
        g2b_data = json.load(f)

    if isinstance(pr_data, dict):
        raw_list = pr_data.get("purchases") or pr_data.get("invoices") or []
        pr_list: List[Dict[str, Any]] = raw_list if isinstance(raw_list, list) else []
    elif isinstance(pr_data, list):
        pr_list = pr_data
    else:
        pr_list = []

    result = reconcile(pr_list, g2b_data)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        s = result["summary"]
        t4 = result["gstr3b_table_4_auto_population"]
        print("=" * 70)
        print(" GSTR-2B vs PURCHASE REGISTER RECONCILIATION SUMMARY")
        print("=" * 70)
        summary_rows = [
            ["Total Invoices in Purchase Register (Books)", s["total_books_invoices"]],
            ["Total Invoices in GSTR-2B (Portal)", s["total_2b_invoices"]],
            ["Exact Matched Invoices", s["exact_matched_count"]],
            ["Tolerance Matched Invoices (+/- ₹1)", s["tolerance_matched_count"]],
            ["Value Mismatches (Flagged)", s["value_mismatch_count"]],
            ["In Books Only (Rule 36(4) Deferred)", s["in_books_only_count"]],
            ["In 2B Only (Unrecorded Purchases)", s["in_2b_only_count"]],
            ["Section 17(5) Blocked Credit", s["blocked_17_5_count"]],
            ["Rule 37 Reversals (> 180 Days Unpaid)", s["rule_37_count"]],
            ["Ineligible in 2B (POS/16(4) Barred)", s["ineligible_2b_count"]]
        ]
        print(format_table(["Reconciliation Category", "Count"], summary_rows))

        print("\n[AUTO-DERIVED GSTR-3B TABLE 4 ITC VALUES]")
        t4_rows = [
            ["Table 4(A)(1) Import of Goods", f"₹{t4['table_4_a_1_import_goods']['iamt']:,.2f}", "-", "-", f"₹{t4['table_4_a_1_import_goods']['total']:,.2f}"],
            ["Table 4(A)(4) ISD Inward", f"₹{t4['table_4_a_4_isd']['iamt']:,.2f}", f"₹{t4['table_4_a_4_isd']['camt']:,.2f}", f"₹{t4['table_4_a_4_isd']['samt']:,.2f}", f"₹{t4['table_4_a_4_isd']['total']:,.2f}"],
            ["Table 4(A)(5) All Other ITC", f"₹{t4['table_4_a_5_all_other_itc']['iamt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['camt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['samt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['total']:,.2f}"],
            ["Table 4(B)(1) Permanent Reversal (17(5))", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['iamt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['camt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['samt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['total']:,.2f}"],
            ["Table 4(B)(2) Temporary Reversal (Rule 37)", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['iamt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['camt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['samt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['total']:,.2f}"],
            ["TABLE 4(C) NET AVAILABLE ITC", f"₹{t4['table_4_c_net_itc']['iamt']:,.2f}", f"₹{t4['table_4_c_net_itc']['camt']:,.2f}", f"₹{t4['table_4_c_net_itc']['samt']:,.2f}", f"₹{t4['table_4_c_net_itc']['total']:,.2f}"]
        ]
        print(format_table(["GSTR-3B Schedule", "IGST", "CGST", "SGST", "Total Net ITC"], t4_rows))

    sys.exit(0)


if __name__ == "__main__":
    main()
