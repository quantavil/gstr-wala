#!/usr/bin/env python3
"""Parses CSV or JSON purchase registers (Books) into canonical format for 2B reconciliation.

Usage:
  python3 scripts/parse_purchase_register.py <purchase_register.csv|json> [output.json]
"""

import csv
import json
import os
import sys

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List


def parse_csv_purchases(csv_path: str) -> List[Dict[str, Any]]:
    """Parses standard CSV purchase register."""
    from scripts.utils import safe_float, round_cur

    purchases = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=1):
            row_norm = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k is not None}

            inum = row_norm.get("invoice_number") or row_norm.get("inv_num") or row_norm.get("inum") or row_norm.get("invoice no") or ""
            if not inum or inum == "INV-UNKNOWN":
                raise ValueError(f"Row {row_idx}: missing invoice number (invoice_number/inum)")
            idt = row_norm.get("invoice_date") or row_norm.get("date") or row_norm.get("idt") or "01-04-2026"
            ctin = row_norm.get("supplier_gstin") or row_norm.get("gstin") or row_norm.get("ctin") or ""
            pos = row_norm.get("pos") or ""
            
            txval = safe_float(row_norm.get("taxable_value") or row_norm.get("txval") or 0.0)
            iamt = safe_float(row_norm.get("igst") or row_norm.get("iamt") or 0.0)
            camt = safe_float(row_norm.get("cgst") or row_norm.get("camt") or 0.0)
            samt = safe_float(row_norm.get("sgst") or row_norm.get("samt") or 0.0)
            csamt = safe_float(row_norm.get("cess") or row_norm.get("csamt") or 0.0)

            is_blocked = (
                row_norm.get("is_blocked_17_5", "").lower() in ["true", "yes", "y", "1"] or
                row_norm.get("blocked", "").lower() in ["true", "yes", "y", "1"]
            )
            try:
                unpaid_days = int(float(row_norm.get("unpaid_days", 0) or 0))
            except Exception:
                unpaid_days = 0

            purchases.append({
                "ctin": ctin.upper(),
                "inum": inum,
                "idt": idt,
                "pos": pos,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "is_blocked_17_5": is_blocked,
                "unpaid_days": unpaid_days
            })

    return purchases


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 parse_purchase_register.py <purchase_register.csv> [output.json]")
        sys.exit(1)

    input_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "purchase_register.json"

    if not os.path.exists(input_file):
        sys.exit(f"Error: File '{input_file}' not found.")

    if input_file.endswith(".csv"):
        purchases = parse_csv_purchases(input_file)
    elif input_file.endswith(".json"):
        with open(input_file, "r", encoding="utf-8") as f:
            purchases = json.load(f)
    else:
        sys.exit("Error: Currently .csv and .json files are supported.")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"purchases": purchases}, f, indent=2)

    print(f"SUCCESS: Parsed {len(purchases)} purchase invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
