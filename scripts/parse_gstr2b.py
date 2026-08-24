#!/usr/bin/env python3
"""Parses and inspects official GSTR-2B JSON exports from the GST Portal.

Usage:
  python3 scripts/parse_gstr2b.py <gstr2b_portal.json>
"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List
from scripts.reconcile_gstr2b import flatten_gstr2b, format_table



def main():
    if len(sys.argv) < 2:
        print("Usage: python3 parse_gstr2b.py <gstr2b_portal.json>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        sys.exit(f"Error: File '{file_path}' not found.")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = flatten_gstr2b(data)

    tot_txval = sum(r["txval"] for r in records)
    tot_iamt = sum(r["iamt"] for r in records)
    tot_camt = sum(r["camt"] for r in records)
    tot_samt = sum(r["samt"] for r in records)
    tot_csamt = sum(r["csamt"] for r in records)

    print("=" * 70)
    print(f" GSTR-2B SUMMARY: {data.get('gstin', '')} (Period: {data.get('fp', '')})")
    print("=" * 70)
    summary_rows: List[List[Any]] = [
        ["Total Invoices / Records", len(records)],
        ["Total Taxable Value", f"₹{tot_txval:,.2f}"],
        ["Integrated Tax (IGST)", f"₹{tot_iamt:,.2f}"],
        ["Central Tax (CGST)", f"₹{tot_camt:,.2f}"],
        ["State/UT Tax (SGST)", f"₹{tot_samt:,.2f}"],
        ["Cess", f"₹{tot_csamt:,.2f}"],
        ["TOTAL ITC AVAILABLE IN 2B", f"₹{tot_iamt + tot_camt + tot_samt + tot_csamt:,.2f}"]
    ]
    print(format_table(["Field", "Value"], summary_rows))


if __name__ == "__main__":
    main()
