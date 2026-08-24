#!/usr/bin/env python3
"""Deterministic GST computation engine for GSTR-1 and GSTR-3B.

Computes:
  - GSTR-1 table aggregations (Tables 4, 5, 6, 7, 8, 9, 11, 12, 13)
  - Table 12 HSN summary with mandatory B2B (12A) and B2C (12B) bifurcation
  - B2CL thresholding (₹1,00,000 per Notification No. 12/2024-CT)
  - GSTR-3B Table 3.1 outward liabilities & Table 3.2 inter-state supplies
  - Section 50 statutory interest (18% p.a. per day on net cash liability)
  - Section 47 statutory late fees (with turnover-based caps)

Usage:
  python3 scripts/gst_engine.py <input.json> [--json]
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.constants import B2CL_THRESHOLD
from scripts.models import StatutoryInterestResult, StatutoryLateFeeResult

if sys.version_info < (3, 12):
    sys.exit("gstr-wala requires Python 3.12+")


def safe_float(val: Any, default: float = 0.0) -> float:
    """Defensively converts values to float, handling strings and nulls safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_date(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str.strip(), "%d-%m-%Y")
    except Exception:
        return None


def round_cur(val: Any) -> float:
    """Rounds currency to 2 decimal places using exact Decimal ROUND_HALF_UP."""
    if val is None:
        return 0.0
    try:
        d = Decimal(str(val))
        return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def compute_gstr1_tables(data: Dict[str, Any]) -> Dict[str, Any]:
    """Processes sales invoices into official GSTR-1 tables."""
    gstin = data.get("gstin", "")
    supplier_state = gstin[:2]
    fp = data.get("fp", "")

    # Storage buckets
    b2b_invoices: List[Dict[str, Any]] = []
    b2cl_invoices: List[Dict[str, Any]] = []
    b2cs_groups: Dict[Tuple[str, float, str], Dict[str, float]] = {}  # (pos, rate, etin) -> amounts
    exp_invoices: List[Dict[str, Any]] = []
    hsn_b2b_groups: Dict[Tuple[str, str, str, float], Dict[str, float]] = {}  # (hsn, desc, uqc, rate) -> amounts
    hsn_b2c_groups: Dict[Tuple[str, str, str, float], Dict[str, float]] = {}

    total_taxable = 0.0
    total_igst = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_cess = 0.0

    invoices = data.get("invoices", [])
    for inv in invoices:
        inum = inv.get("inum", "")
        idt = inv.get("idt", "")
        pos = inv.get("pos")
        ctin = inv.get("ctin")
        
        if not pos:
            if ctin:
                pos = str(ctin)[:2]
            elif supplier_state:
                pos = supplier_state
            else:
                raise ValueError(f"Invoice '{inum}' is missing required Place of Supply ('pos')")

        rchrg = inv.get("rchrg", "N")
        inv_typ = inv.get("inv_typ", "R")
        etin = inv.get("etin", "")
        inv_val = safe_float(inv.get("val", 0.0))
        items = inv.get("items", [])

        is_b2b = bool(ctin)
        is_interstate = (pos != supplier_state)
        is_export = bool(inv.get("exp_typ"))

        # Calculate invoice totals from items if val is missing/zero
        items_total_val = 0.0
        for itm in items:
            tx = safe_float(itm.get("txval", 0.0))
            i = safe_float(itm.get("iamt", 0.0))
            c = safe_float(itm.get("camt", 0.0))
            s = safe_float(itm.get("samt", 0.0))
            cs = safe_float(itm.get("csamt", 0.0))
            items_total_val += (tx + i + c + s + cs)
            total_taxable += tx
            total_igst += i
            total_cgst += c
            total_sgst += s
            total_cess += cs

            # HSN aggregation
            hsn = str(itm.get("hsn_sc", "") or "").strip()
            desc = str(itm.get("desc", "") or "").strip()
            uqc = str(itm.get("uqc", "OTH") or "OTH").strip()
            rt = safe_float(itm.get("rt", 0.0))
            qty = safe_float(itm.get("qty", 0.0))

            if hsn:
                hsn_key = (hsn, desc, uqc, rt)
                target_hsn_map = hsn_b2b_groups if is_b2b else hsn_b2c_groups
                if hsn_key not in target_hsn_map:
                    target_hsn_map[hsn_key] = {"qty": 0.0, "val": 0.0, "txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
                
                target_hsn_map[hsn_key]["qty"] += qty
                target_hsn_map[hsn_key]["val"] += (tx + i + c + s + cs)
                target_hsn_map[hsn_key]["txval"] += tx
                target_hsn_map[hsn_key]["iamt"] += i
                target_hsn_map[hsn_key]["camt"] += c
                target_hsn_map[hsn_key]["samt"] += s
                target_hsn_map[hsn_key]["csamt"] += cs

        effective_inv_val = inv_val if inv_val > 0 else items_total_val

        if is_export:
            exp_invoices.append(inv)
        elif is_b2b:
            b2b_invoices.append(inv)
        else:
            # B2C Invoice
            if is_interstate and effective_inv_val > B2CL_THRESHOLD:
                # Table 5: B2CL (Inter-state > ₹1,00,000)
                b2cl_invoices.append(inv)
            else:
                # Table 7: B2CS (Intra-state or Inter-state <= ₹1,00,000)
                for itm in items:
                    rt = safe_float(itm.get("rt", 0.0))
                    b2cs_key = (pos, rt, etin)
                    if b2cs_key not in b2cs_groups:
                        b2cs_groups[b2cs_key] = {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
                    b2cs_groups[b2cs_key]["txval"] += float(itm.get("txval", 0.0))
                    b2cs_groups[b2cs_key]["iamt"] += float(itm.get("iamt", 0.0))
                    b2cs_groups[b2cs_key]["camt"] += float(itm.get("camt", 0.0))
                    b2cs_groups[b2cs_key]["samt"] += float(itm.get("samt", 0.0))
                    b2cs_groups[b2cs_key]["csamt"] += float(itm.get("csamt", 0.0))

    # Format Table 7 (B2CS list)
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

    # Format Table 12 HSN Summary (12A B2B + 12B B2C)
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

    return {
        "gstin": gstin,
        "fp": fp,
        "summary": {
            "total_invoices": len(invoices),
            "b2b_count": len(b2b_invoices),
            "b2cl_count": len(b2cl_invoices),
            "b2cs_lines": len(table_7_b2cs),
            "export_count": len(exp_invoices),
            "total_taxable": round_cur(total_taxable),
            "total_igst": round_cur(total_igst),
            "total_cgst": round_cur(total_cgst),
            "total_sgst": round_cur(total_sgst),
            "total_cess": round_cur(total_cess),
            "total_tax": round_cur(total_igst + total_cgst + total_sgst + total_cess),
        },
        "table_4_b2b": b2b_invoices,
        "table_5_b2cl": b2cl_invoices,
        "table_6_exp": exp_invoices,
        "table_7_b2cs": table_7_b2cs,
        "table_8_nil_exempt": data.get("nil_exempt_non_gst", {}),
        "table_9_cdnr": data.get("credit_debit_notes", []),
        "table_11_advances": {
            "received": data.get("advances_received", []),
            "adjusted": data.get("advances_adjusted", [])
        },
        "table_12_hsn": table_12_hsn_data,
        "table_13_docs": data.get("doc_summary", [])
    }


def compute_statutory_interest(net_cash_liability: float, due_date_str: Optional[str], filing_date_str: Optional[str]) -> StatutoryInterestResult:
    """Calculates Section 50 interest (18% p.a. per day on net cash tax liability)."""
    due_dt = parse_date(due_date_str)
    file_dt = parse_date(filing_date_str)

    if not due_dt or not file_dt:
        return {
            "delay_days": 0,
            "annual_rate": 0.18,
            "net_cash_liability": net_cash_liability,
            "interest_amount": 0.0,
            "due_date": due_date_str or "",
            "filing_date": filing_date_str or ""
        }

    delay_days = max(0, (file_dt - due_dt).days)
    if delay_days == 0 or net_cash_liability <= 0:
        return {
            "delay_days": 0,
            "annual_rate": 0.18,
            "net_cash_liability": net_cash_liability,
            "interest_amount": 0.0,
            "due_date": due_date_str or "",
            "filing_date": filing_date_str or ""
        }

    # Daily interest rate: 18% / 365
    interest = round_cur(net_cash_liability * (0.18 / 365.0) * delay_days)
    return {
        "delay_days": delay_days,
        "annual_rate": 0.18,
        "net_cash_liability": net_cash_liability,
        "interest_amount": interest,
        "due_date": due_date_str or "",
        "filing_date": filing_date_str or ""
    }


def compute_statutory_late_fee(is_nil_return: bool, turnover_slab: str, due_date_str: Optional[str], filing_date_str: Optional[str]) -> StatutoryLateFeeResult:
    """Calculates Section 47 late fee per day subject to statutory caps."""
    due_dt = parse_date(due_date_str)
    file_dt = parse_date(filing_date_str)

    if not due_dt or not file_dt:
        return {"delay_days": 0, "cgst_late_fee": 0.0, "sgst_late_fee": 0.0, "total_late_fee": 0.0}

    delay_days = max(0, (file_dt - due_dt).days)
    if delay_days == 0:
        return {"delay_days": 0, "cgst_late_fee": 0.0, "sgst_late_fee": 0.0, "total_late_fee": 0.0}

    if is_nil_return:
        # ₹20/day (₹10 CGST + ₹10 SGST), cap ₹500 (₹250 + ₹250)
        daily_cgst, daily_sgst = 10.0, 10.0
        cap_cgst, cap_sgst = 250.0, 250.0
    else:
        # ₹50/day (₹25 CGST + ₹25 SGST)
        daily_cgst, daily_sgst = 25.0, 25.0
        if turnover_slab == "upto_1.5cr":
            cap_cgst, cap_sgst = 1000.0, 1000.0  # Max ₹2,000
        elif turnover_slab == "1.5cr_to_5cr":
            cap_cgst, cap_sgst = 2500.0, 2500.0  # Max ₹5,000
        else:
            cap_cgst, cap_sgst = 5000.0, 5000.0  # Max ₹10,000

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
        "capped": (calc_cgst == cap_cgst)
    }


def compute(data: Dict[str, Any]) -> Dict[str, Any]:
    """Primary computation dispatch."""
    if "invoices" in data or "fp" in data:
        gstr1_res = compute_gstr1_tables(data)
        return {"return_type": "GSTR-1", **gstr1_res}
    else:
        # Handle standalone 3B calculations if given
        outward = data.get("outward_supplies", {}).get("taxable", {})
        txval = float(outward.get("txval", 0.0))
        iamt = float(outward.get("iamt", 0.0))
        camt = float(outward.get("camt", 0.0))
        samt = float(outward.get("samt", 0.0))
        csamt = float(outward.get("csamt", 0.0))
        total_tax = iamt + camt + samt + csamt
        return {
            "return_type": "GSTR-3B",
            "gstin": data.get("gstin", ""),
            "ret_period": data.get("ret_period", ""),
            "taxable_turnover": txval,
            "total_tax_liability": total_tax,
            "breakdown": {"iamt": iamt, "camt": camt, "samt": samt, "csamt": csamt}
        }


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
    """Formats an ASCII markdown table."""
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

            if result["table_12_hsn"]:
                print("\n[Table 12 HSN Summary (12A B2B & 12B B2C)]")
                hsn_rows = [
                    [h["source_type"], h["hsn_sc"], h["uqc"], h["qty"], f"₹{h['txval']:,.2f}", f"{h['rt']}%", f"₹{h['iamt']:,.2f}", f"₹{h['camt']:,.2f}", f"₹{h['samt']:,.2f}"]
                    for h in result["table_12_hsn"]
                ]
                print(format_table(["Type", "HSN", "UQC", "Qty", "Taxable Val", "Rate", "IGST", "CGST", "SGST"], hsn_rows))

    sys.exit(0)


if __name__ == "__main__":
    main()
