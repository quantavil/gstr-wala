#!/usr/bin/env python3
"""Parses CSV, Excel, or JSON sales registers into canonical gstr1_input.json.

Handles standard accounting columns:
  - Invoice Number, Date, Customer GSTIN, Customer Name, Place of Supply (POS),
  - Taxable Value, GST Rate, IGST, CGST, SGST, Cess, Total Invoice Value,
  - HSN/SAC Code, Description, Unit Quantity Code (UQC), Quantity, Export Type.

Usage:
  python3 scripts/parse_sales_register.py <sales_register.csv|xlsx|json> <gstin> <fp> [output.json]
"""

import csv
import json
import os
import re
import sys

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List, Optional
from scripts.validate_gst_input import compute_gstin_checksum, is_valid_gstin


def parse_rows_sales(rows: List[Dict[str, Any]], gstin: str, fp: str) -> Dict[str, Any]:
    """Normalizes generic row dictionaries into canonical GSTR-1 invoices."""
    invoices_map: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        row_norm = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k is not None}

        inum = row_norm.get("invoice_number") or row_norm.get("inv_num") or row_norm.get("inum") or row_norm.get("invoice no") or row_norm.get("invoice_no") or "INV-UNKNOWN"
        idt = row_norm.get("invoice_date") or row_norm.get("date") or row_norm.get("idt") or "01-04-2026"
        ctin = row_norm.get("customer_gstin") or row_norm.get("gstin") or row_norm.get("ctin") or ""
        pos = row_norm.get("pos") or row_norm.get("place_of_supply") or row_norm.get("state_code") or (ctin[:2] if ctin else gstin[:2])
        
        if "/" in idt:
            idt = idt.replace("/", "-")

        try:
            txval = float(row_norm.get("taxable_value") or row_norm.get("txval") or row_norm.get("taxable_amount") or 0.0)
        except Exception:
            txval = 0.0
        try:
            rt = float(row_norm.get("gst_rate") or row_norm.get("rate") or row_norm.get("rt") or 0.0)
        except Exception:
            rt = 0.0
        try:
            iamt = float(row_norm.get("igst") or row_norm.get("iamt") or row_norm.get("igst_amount") or 0.0)
        except Exception:
            iamt = 0.0
        try:
            camt = float(row_norm.get("cgst") or row_norm.get("camt") or row_norm.get("cgst_amount") or 0.0)
        except Exception:
            camt = 0.0
        try:
            samt = float(row_norm.get("sgst") or row_norm.get("samt") or row_norm.get("sgst_amount") or 0.0)
        except Exception:
            samt = 0.0
        try:
            csamt = float(row_norm.get("cess") or row_norm.get("csamt") or 0.0)
        except Exception:
            csamt = 0.0
        
        hsn = str(row_norm.get("hsn") or row_norm.get("hsn_code") or row_norm.get("hsn_sc") or "9999").strip()
        desc = row_norm.get("description") or row_norm.get("item_description") or row_norm.get("desc") or "Goods / Services"
        uqc = row_norm.get("uqc") or row_norm.get("unit") or "NOS"
        try:
            qty = float(row_norm.get("quantity") or row_norm.get("qty") or 1.0)
        except Exception:
            qty = 1.0
        exp_typ = row_norm.get("exp_typ") or row_norm.get("export_type") or ("WOPAY" if pos == "97" and rt == 0 else None)

        # Auto-calculate taxes ONLY if rate > 0 and no taxes given and not zero-rated export
        supplier_state = gstin[:2]
        is_interstate = (pos != supplier_state)
        if iamt == 0 and camt == 0 and samt == 0 and rt > 0 and txval > 0 and exp_typ != "WOPAY":
            if is_interstate:
                iamt = round((txval * rt) / 100.0, 2)
            else:
                camt = round((txval * rt) / 200.0, 2)
                samt = round((txval * rt) / 200.0, 2)

        if inum not in invoices_map:
            invoices_map[inum] = {
                "inum": inum,
                "idt": idt,
                "pos": str(pos).zfill(2),
                "val": 0.0,
                "items": []
            }
            if ctin:
                invoices_map[inum]["ctin"] = ctin.upper()
            if exp_typ:
                invoices_map[inum]["exp_typ"] = exp_typ

        invoices_map[inum]["items"].append({
            "txval": txval,
            "rt": rt,
            "iamt": iamt,
            "camt": camt,
            "samt": samt,
            "csamt": csamt,
            "hsn_sc": hsn,
            "desc": desc,
            "uqc": uqc,
            "qty": qty
        })
        invoices_map[inum]["val"] = round(invoices_map[inum]["val"] + txval + iamt + camt + samt + csamt, 2)

    return {
        "gstin": gstin,
        "fp": fp,
        "invoices": list(invoices_map.values())
    }


def parse_csv_sales(csv_path: str, gstin: str, fp: str) -> Dict[str, Any]:
    """Parses standard CSV sales register into canonical format."""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return parse_rows_sales(rows, gstin, fp)


def parse_excel_sales(excel_path: str, gstin: str, fp: str) -> Dict[str, Any]:
    """Parses Excel (.xlsx, .xls, .xlsb) sales register using fast Calamine engine."""
    from scripts.fast_engine import read_excel_calamine
    rows = read_excel_calamine(excel_path)
    return parse_rows_sales(rows, gstin, fp)


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 parse_sales_register.py <sales_register.csv|xlsx|json> <gstin> <fp> [output.json]")
        sys.exit(1)

    sales_file = sys.argv[1]
    gstin = sys.argv[2]
    fp = sys.argv[3]
    out_file = sys.argv[4] if len(sys.argv) > 4 else "gstr1_input.json"

    if not os.path.exists(sales_file):
        sys.exit(f"Error: File '{sales_file}' not found.")

    lower_file = sales_file.lower()
    if lower_file.endswith(".csv"):
        canonical = parse_csv_sales(sales_file, gstin, fp)
    elif lower_file.endswith((".xlsx", ".xls", ".xlsb")):
        canonical = parse_excel_sales(sales_file, gstin, fp)
    elif lower_file.endswith(".json"):
        with open(sales_file, "r", encoding="utf-8") as f:
            canonical = json.load(f)
    else:
        sys.exit("Error: Unsupported file format. Supported: .csv, .xlsx, .xls, .xlsb, .json")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2)

    print(f"SUCCESS: Parsed {len(canonical.get('invoices', []))} invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
