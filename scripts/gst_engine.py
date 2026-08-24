#!/usr/bin/env python3
"""Deterministic GST computation engine for GSTR-1 and GSTR-3B.

Computes:
  - GSTR-1 table aggregations (Tables 4, 5, 6, 7, 8, 9, 11, 12, 13)
  - Table 12 HSN summary with mandatory B2B (12A) and B2C (12B) bifurcation
  - B2CL thresholding (₹1,00,000 per Notification No. 12/2024-CT)
  - Net liability computation accounting for CDNR and Advances
  - GSTR-3B Table 3.1 outward liabilities & Table 3.2 inter-state supplies
  - Section 50 statutory interest (manifest-driven rate per day on net cash liability)
  - Section 47 statutory late fees (manifest-driven slabs and turnover-based caps)

Usage:
  python3 scripts/gst_engine.py <input.json> [--json]
"""

import json
import os
import sys
from datetime import datetime
from typing import Any

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.constants import (
    B2CL_THRESHOLD,
    detect_return_type,
    get_interest_rate_50_1,
    get_late_fee_caps,
)
from scripts.models import StatutoryInterestResult, StatutoryLateFeeResult
from scripts.utils import format_table, round_cur, safe_float


def parse_date(dt_str: str | None) -> datetime | None:
    """Parses DD-MM-YYYY or ISO date string.

    Returns None if dt_str is None or empty.
    Raises ValueError if dt_str is present but malformed.
    """
    if not dt_str or not str(dt_str).strip():
        return None
    val = str(dt_str).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt)  # noqa: DTZ007
        except ValueError:
            pass
    raise ValueError(f"Malformed date string: {dt_str!r}. Expected DD-MM-YYYY or YYYY-MM-DD format.")


def compute_gstr1_tables(data: dict[str, Any]) -> dict[str, Any]:
    """Processes sales invoices into official GSTR-1 tables and computes net statutory liability."""
    gstin = data.get("gstin", "")
    supplier_state = gstin[:2]
    fp = data.get("fp", "")

    # Storage buckets
    b2b_invoices: list[dict[str, Any]] = []
    b2cl_invoices: list[dict[str, Any]] = []
    b2cs_groups: dict[tuple[str, float, str], dict[str, float]] = {}  # (pos, rate, etin) -> amounts
    exp_invoices: list[dict[str, Any]] = []
    hsn_b2b_groups: dict[tuple[str, str, str, float], dict[str, float]] = {}  # (hsn, desc, uqc, rate) -> amounts
    hsn_b2c_groups: dict[tuple[str, str, str, float], dict[str, float]] = {}

    gross_taxable = 0.0
    gross_igst = 0.0
    gross_cgst = 0.0
    gross_sgst = 0.0
    gross_cess = 0.0

    invoices = data.get("invoices", [])
    for inv in invoices:
        inum = inv.get("inum", "")
        pos = inv.get("pos")
        ctin = inv.get("ctin")

        if not pos:
            if ctin:
                pos = str(ctin)[:2]
            elif supplier_state:
                pos = supplier_state
            else:
                raise ValueError(f"Invoice '{inum}' is missing required Place of Supply ('pos')")
        resolved_pos = str(pos).zfill(2)
        pos = resolved_pos
        inv_view = {**inv, "pos": pos}

        etin = inv.get("etin", "")
        inv_val = safe_float(inv.get("val", 0.0))
        items = inv.get("items", [])

        is_b2b = bool(ctin)
        is_interstate = (pos != supplier_state)
        is_export = bool(inv.get("exp_typ"))

        # Calculate invoice totals from items if val is missing/zero
        items_total_val = 0.0
        for itm in items:
            txval = safe_float(itm.get("txval", 0.0))
            iamt = safe_float(itm.get("iamt", 0.0))
            camt = safe_float(itm.get("camt", 0.0))
            samt = safe_float(itm.get("samt", 0.0))
            csamt = safe_float(itm.get("csamt", 0.0))
            items_total_val += (txval + iamt + camt + samt + csamt)

        effective_inv_val = inv_val if inv_val > 0.0 else items_total_val

        # Route to Table 4 (B2B), Table 5 (B2CL), Table 6 (Exports), or Table 7 (B2CS)
        if is_export:
            exp_invoices.append(inv_view)
        elif is_b2b:
            b2b_invoices.append(inv_view)
        else:
            # B2C (Unregistered recipient)
            # Table 5 B2CL applies to inter-state B2C supplies > B2CL_THRESHOLD (₹1,00,000)
            if is_interstate and effective_inv_val > B2CL_THRESHOLD:
                b2cl_invoices.append(inv_view)
            else:
                # Table 7 B2CS — aggregate by (pos, rate, etin)
                for itm in items:
                    rt = safe_float(itm.get("rt", 0.0))
                    txval = safe_float(itm.get("txval", 0.0))
                    iamt = safe_float(itm.get("iamt", 0.0))
                    camt = safe_float(itm.get("camt", 0.0))
                    samt = safe_float(itm.get("samt", 0.0))
                    csamt = safe_float(itm.get("csamt", 0.0))

                    grp_key = (pos, rt, etin)
                    if grp_key not in b2cs_groups:
                        b2cs_groups[grp_key] = {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
                    b2cs_groups[grp_key]["txval"] += txval
                    b2cs_groups[grp_key]["iamt"] += iamt
                    b2cs_groups[grp_key]["camt"] += camt
                    b2cs_groups[grp_key]["samt"] += samt
                    b2cs_groups[grp_key]["csamt"] += csamt

        # Aggregate HSN Summary and Gross Invoice Totals
        for itm in items:
            txval = safe_float(itm.get("txval", 0.0))
            iamt = safe_float(itm.get("iamt", 0.0))
            camt = safe_float(itm.get("camt", 0.0))
            samt = safe_float(itm.get("samt", 0.0))
            csamt = safe_float(itm.get("csamt", 0.0))
            rt = safe_float(itm.get("rt", 0.0))
            qty = safe_float(itm.get("qty", 1.0))
            uqc = str(itm.get("uqc", "NOS"))
            hsn = str(itm.get("hsn_sc", "9999")).strip()
            desc = str(itm.get("desc", "Goods / Services")).strip()
            item_val = txval + iamt + camt + samt + csamt

            gross_taxable += txval
            gross_igst += iamt
            gross_cgst += camt
            gross_sgst += samt
            gross_cess += csamt

            hsn_key = (hsn, desc, uqc, rt)
            target_hsn_map = hsn_b2b_groups if is_b2b else hsn_b2c_groups
            if hsn_key not in target_hsn_map:
                target_hsn_map[hsn_key] = {"qty": 0.0, "val": 0.0, "txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            target_hsn_map[hsn_key]["qty"] += qty
            target_hsn_map[hsn_key]["val"] += item_val
            target_hsn_map[hsn_key]["txval"] += txval
            target_hsn_map[hsn_key]["iamt"] += iamt
            target_hsn_map[hsn_key]["camt"] += camt
            target_hsn_map[hsn_key]["samt"] += samt
            target_hsn_map[hsn_key]["csamt"] += csamt

    # Format Table 7 B2CS Summary
    table_7_b2cs = []
    for (pos, rt, etin), amts in sorted(b2cs_groups.items()):
        typ = "E" if etin else "OE"
        sply_ty = "INTER" if pos != supplier_state else "INTRA"
        entry = {
            "sply_ty": sply_ty,
            "pos": pos,
            "typ": typ,
            "rt": rt,
            "txval": round_cur(amts["txval"]),
            "iamt": round_cur(amts["iamt"]),
            "camt": round_cur(amts["camt"]),
            "samt": round_cur(amts["samt"]),
            "csamt": round_cur(amts["csamt"]),
        }
        if etin:
            entry["etin"] = etin
        table_7_b2cs.append(entry)

    # Format Table 12 HSN Summary (12A B2B and 12B B2C)
    table_12_hsn_data = []
    num = 1
    # 12A: B2B
    for (hsn, desc, uqc, rt), amts in sorted(hsn_b2b_groups.items()):
        table_12_hsn_data.append({
            "num": num,
            "hsn_sc": hsn,
            "desc": desc,
            "uqc": uqc,
            "qty": round_cur(amts["qty"]),
            "val": round_cur(amts["val"]),
            "txval": round_cur(amts["txval"]),
            "rt": rt,
            "iamt": round_cur(amts["iamt"]),
            "camt": round_cur(amts["camt"]),
            "samt": round_cur(amts["samt"]),
            "csamt": round_cur(amts["csamt"]),
            "source_type": "B2B"
        })
        num += 1

    # 12B: B2C
    for (hsn, desc, uqc, rt), amts in sorted(hsn_b2c_groups.items()):
        table_12_hsn_data.append({
            "num": num,
            "hsn_sc": hsn,
            "desc": desc,
            "uqc": uqc,
            "qty": round_cur(amts["qty"]),
            "val": round_cur(amts["val"]),
            "txval": round_cur(amts["txval"]),
            "rt": rt,
            "iamt": round_cur(amts["iamt"]),
            "camt": round_cur(amts["camt"]),
            "samt": round_cur(amts["samt"]),
            "csamt": round_cur(amts["csamt"]),
            "source_type": "B2C"
        })
        num += 1

    # Netting: CDNR (Table 9) + Advances (Table 11) into Net Summary
    net_taxable = gross_taxable
    net_igst = gross_igst
    net_cgst = gross_cgst
    net_sgst = gross_sgst
    net_cess = gross_cess

    cdnr_list = data.get("credit_debit_notes", [])
    for note in cdnr_list:
        sign = -1.0 if str(note.get("ntty", "C")).upper() == "C" else 1.0
        for itm in note.get("items", []):
            net_taxable += safe_float(itm.get("txval", 0.0)) * sign
            net_igst += safe_float(itm.get("iamt", 0.0)) * sign
            net_cgst += safe_float(itm.get("camt", 0.0)) * sign
            net_sgst += safe_float(itm.get("samt", 0.0)) * sign
            net_cess += safe_float(itm.get("csamt", 0.0)) * sign

    adv_rec = data.get("advances_received", [])
    for adv in adv_rec:
        for itm in adv.get("items", []):
            net_taxable += safe_float(itm.get("txval", 0.0))
            net_igst += safe_float(itm.get("iamt", 0.0))
            net_cgst += safe_float(itm.get("camt", 0.0))
            net_sgst += safe_float(itm.get("samt", 0.0))
            net_cess += safe_float(itm.get("csamt", 0.0))

    adv_adj = data.get("advances_adjusted", [])
    for adj in adv_adj:
        for itm in adj.get("items", []):
            net_taxable -= safe_float(itm.get("txval", 0.0))
            net_igst -= safe_float(itm.get("iamt", 0.0))
            net_cgst -= safe_float(itm.get("camt", 0.0))
            net_sgst -= safe_float(itm.get("samt", 0.0))
            net_cess -= safe_float(itm.get("csamt", 0.0))

    return {
        "gstin": gstin,
        "fp": fp,
        "summary": {
            "total_invoices": len(invoices),
            "b2b_count": len(b2b_invoices),
            "b2cl_count": len(b2cl_invoices),
            "b2cs_lines": len(table_7_b2cs),
            "export_count": len(exp_invoices),
            "total_taxable": round_cur(net_taxable),
            "total_igst": round_cur(net_igst),
            "total_cgst": round_cur(net_cgst),
            "total_sgst": round_cur(net_sgst),
            "total_cess": round_cur(net_cess),
            "total_tax": round_cur(net_igst + net_cgst + net_sgst + net_cess),
        },
        "table_4_b2b": b2b_invoices,
        "table_5_b2cl": b2cl_invoices,
        "table_6_exp": exp_invoices,
        "table_7_b2cs": table_7_b2cs,
        "table_8_nil_exempt": data.get("nil_exempt_non_gst", {}),
        "table_9_cdnr": cdnr_list,
        "table_11_advances": {
            "received": adv_rec,
            "adjusted": adv_adj,
        },
        "table_12_hsn": table_12_hsn_data,
        "table_13_docs": data.get("doc_summary", []),
    }


def compute_statutory_interest(
    net_cash_liability: float,
    due_date_str: str | None,
    filing_date_str: str | None,
) -> StatutoryInterestResult:
    """Calculates Section 50 interest on net cash tax liability.

    Malformed dates raise ValueError; absent dates return zero-delay result.
    Annual interest rate is driven by rules_manifest.json (Section 50(1) net cash rate).
    """
    due_dt = parse_date(due_date_str)
    file_dt = parse_date(filing_date_str)
    rate = get_interest_rate_50_1()

    if not due_dt or not file_dt:
        return {
            "delay_days": 0,
            "annual_rate": rate,
            "net_cash_liability": net_cash_liability,
            "interest_amount": 0.0,
            "due_date": due_date_str or "",
            "filing_date": filing_date_str or "",
        }

    delay_days = max(0, (file_dt - due_dt).days)
    if delay_days == 0 or net_cash_liability <= 0:
        return {
            "delay_days": 0,
            "annual_rate": rate,
            "net_cash_liability": net_cash_liability,
            "interest_amount": 0.0,
            "due_date": due_date_str or "",
            "filing_date": filing_date_str or "",
        }

    # Daily interest rate: rate / 365
    interest = round_cur(net_cash_liability * (rate / 365.0) * delay_days)
    return {
        "delay_days": delay_days,
        "annual_rate": rate,
        "net_cash_liability": net_cash_liability,
        "interest_amount": interest,
        "due_date": due_date_str or "",
        "filing_date": filing_date_str or "",
    }


def compute_statutory_late_fee(
    is_nil_return: bool,
    turnover_slab: str,
    due_date_str: str | None,
    filing_date_str: str | None,
) -> StatutoryLateFeeResult:
    """Calculates Section 47 late fee per day subject to statutory caps.

    Malformed dates raise ValueError; absent dates return zero-delay result.
    Fee rates and slab caps are driven by rules_manifest.json.
    """
    due_dt = parse_date(due_date_str)
    file_dt = parse_date(filing_date_str)

    if not due_dt or not file_dt:
        return {"delay_days": 0, "cgst_late_fee": 0.0, "sgst_late_fee": 0.0, "total_late_fee": 0.0}

    delay_days = max(0, (file_dt - due_dt).days)
    if delay_days == 0:
        return {"delay_days": 0, "cgst_late_fee": 0.0, "sgst_late_fee": 0.0, "total_late_fee": 0.0}

    caps = get_late_fee_caps()
    if is_nil_return:
        daily_cgst = caps["nil_return_daily_cgst"]
        daily_sgst = caps["nil_return_daily_sgst"]
        cap_cgst = caps["nil_return_max_cap_total"] / 2.0
        cap_sgst = caps["nil_return_max_cap_total"] / 2.0
    else:
        daily_cgst = caps["upto_1.5cr_daily_cgst"]
        daily_sgst = caps["upto_1.5cr_daily_sgst"]
        if turnover_slab == "upto_1.5cr":
            cap_cgst = caps["upto_1.5cr_max_cap_total"] / 2.0
            cap_sgst = caps["upto_1.5cr_max_cap_total"] / 2.0
        elif turnover_slab == "1.5cr_to_5cr":
            cap_cgst = caps["slab_1.5cr_to_5cr_max_cap_total"] / 2.0
            cap_sgst = caps["slab_1.5cr_to_5cr_max_cap_total"] / 2.0
        else:
            cap_cgst = caps["above_5cr_max_cap_total"] / 2.0
            cap_sgst = caps["above_5cr_max_cap_total"] / 2.0

    calc_cgst = min(cap_cgst, delay_days * daily_cgst)
    calc_sgst = min(cap_sgst, delay_days * daily_sgst)

    return {
        "delay_days": delay_days,
        "is_nil_return": is_nil_return,
        "turnover_slab": turnover_slab,
        "cgst_late_fee": round_cur(calc_cgst),
        "sgst_late_fee": round_cur(calc_sgst),
        "camt": round_cur(calc_cgst),
        "samt": round_cur(calc_sgst),
        "total_late_fee": round_cur(calc_cgst + calc_sgst),
        "capped": (calc_cgst == cap_cgst),
    }


def _extract_gstr3b_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Helper to extract outward liabilities summary from GSTR-3B structure."""
    outward = (
        data.get("outward_supplies", {}).get("taxable", {})
        or data.get("sup_details", {}).get("osup_det", {})
    )
    txval = safe_float(outward.get("txval", 0.0))
    iamt = safe_float(outward.get("iamt", 0.0))
    camt = safe_float(outward.get("camt", 0.0))
    samt = safe_float(outward.get("samt", 0.0))
    csamt = safe_float(outward.get("csamt", 0.0))
    total_tax = round_cur(iamt + camt + samt + csamt)
    return {
        "return_type": "GSTR-3B",
        "gstin": data.get("gstin", ""),
        "ret_period": data.get("ret_period", ""),
        "taxable_turnover": txval,
        "total_tax_liability": total_tax,
        "breakdown": {"iamt": iamt, "camt": camt, "samt": samt, "csamt": csamt},
    }


def compute(data: dict[str, Any]) -> dict[str, Any]:
    """Primary computation dispatch using unified return type detector."""
    ret_type = detect_return_type(data)
    if ret_type == "GSTR-1":
        gstr1_res = compute_gstr1_tables(data)
        return {"return_type": "GSTR-1", **gstr1_res}
    elif ret_type == "GSTR-3B":
        return _extract_gstr3b_summary(data)
    else:
        raise ValueError(f"Unsupported return type: {ret_type}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 gst_engine.py <input.json> [--json]")
        sys.exit(1)

    file_path = sys.argv[1]
    json_output = "--json" in sys.argv

    if not os.path.exists(file_path):
        sys.exit(f"Error: File '{file_path}' not found.")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = compute(data)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if result["return_type"] == "GSTR-1":
            s = result["summary"]
            print("=" * 60)
            print(f" GSTR-1 COMPUTATION SUMMARY: {result['gstin']} (Period: {result['fp']})")
            print("=" * 60)
            summary_rows = [
                ["Total Invoices Processed", s["total_invoices"]],
                ["Table 4 (B2B Invoices)", s["b2b_count"]],
                ["Table 5 (B2CL > ₹1L Invoices)", s["b2cl_count"]],
                ["Table 7 (B2CS Summary Lines)", s["b2cs_lines"]],
                ["Table 6 (Exports)", s["export_count"]],
                ["Total Taxable Turnover", f"₹{s['total_taxable']:,.2f}"],
                ["Integrated Tax (IGST)", f"₹{s['total_igst']:,.2f}"],
                ["Central Tax (CGST)", f"₹{s['total_cgst']:,.2f}"],
                ["State/UT Tax (SGST)", f"₹{s['total_sgst']:,.2f}"],
                ["Cess", f"₹{s['total_cess']:,.2f}"],
                ["TOTAL OUTWARD TAX LIABILITY", f"₹{s['total_tax']:,.2f}"]
            ]
            print(format_table(["Metric / Field", "Value"], summary_rows))

            if result.get("table_12_hsn"):
                print("\n[Table 12 HSN Summary (12A B2B & 12B B2C)]")
                hsn_rows = [
                    [h["source_type"], h["hsn_sc"], h["uqc"], h["qty"], f"₹{h['txval']:,.2f}", f"{h['rt']}%", f"₹{h['iamt']:,.2f}", f"₹{h['camt']:,.2f}", f"₹{h['samt']:,.2f}"]
                    for h in result["table_12_hsn"]
                ]
                print(format_table(["Type", "HSN", "UQC", "Qty", "Taxable Val", "Rate", "IGST", "CGST", "SGST"], hsn_rows))
        elif result["return_type"] == "GSTR-3B":
            print("=" * 60)
            print(f" GSTR-3B COMPUTATION SUMMARY: {result.get('gstin', '')} (Period: {result.get('ret_period', '')})")
            print("=" * 60)
            bd = result.get("breakdown", {})
            summary_rows = [
                ["Total Taxable Turnover", f"₹{result.get('taxable_turnover', 0.0):,.2f}"],
                ["Integrated Tax (IGST)", f"₹{bd.get('iamt', 0.0):,.2f}"],
                ["Central Tax (CGST)", f"₹{bd.get('camt', 0.0):,.2f}"],
                ["State/UT Tax (SGST)", f"₹{bd.get('samt', 0.0):,.2f}"],
                ["Cess", f"₹{bd.get('csamt', 0.0):,.2f}"],
                ["TOTAL TAX LIABILITY", f"₹{result.get('total_tax_liability', 0.0):,.2f}"]
            ]
            print(format_table(["Metric / Field", "Value"], summary_rows))

    sys.exit(0)


if __name__ == "__main__":
    main()
