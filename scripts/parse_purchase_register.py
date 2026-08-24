#!/usr/bin/env python3
"""Parses CSV or JSON purchase registers (Books) into canonical format for 2B reconciliation.

Truthfulness contract (mirrors parse_sales_register):
  - Missing invoice date raises ValueError — no fabricated "01-04-2026".
  - Money fields parsed truthfully (accounting negatives, currency symbols,
    Indian grouping); garbage raises instead of becoming a plausible number.
  - Short CSV rows never leak the literal string "None" into fields.

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
from scripts.utils import excel_cell_to_str, normalize_date_str, round_cur, safe_float_strict


def _money(row_norm: Dict[str, str], aliases: tuple, row_idx: int) -> float:
    """Parses an optional money field truthfully.

    Absent/blank cell -> 0.0; present-but-unparseable -> ValueError naming the
    row and column.
    """
    for alias in aliases:
        if alias not in row_norm:
            continue
        raw = row_norm[alias]
        if raw == "":
            continue
        try:
            return safe_float_strict(raw)
        except ValueError:
            raise ValueError(
                f"Row {row_idx}: column '{alias}' has unparseable amount {raw!r}"
            )
    return 0.0


def parse_csv_purchases(csv_path: str) -> List[Dict[str, Any]]:
    """Parses standard CSV purchase register."""
    purchases: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"Purchase register '{csv_path}' contains no data rows — cannot reconcile against an empty register.")

    for row_idx, row in enumerate(rows, start=1):
        # excel_cell_to_str: None->"" so short rows never become the string "None"
        row_norm = {
            str(k).strip().lower(): excel_cell_to_str(v)
            for k, v in row.items()
            if k is not None
        }

        inum = (
            row_norm.get("invoice_number")
            or row_norm.get("inv_num")
            or row_norm.get("inum")
            or row_norm.get("invoice no")
            or ""
        )
        if not inum or inum == "INV-UNKNOWN":
            raise ValueError(f"Row {row_idx}: missing invoice number (invoice_number/inum)")
        date_raw = (
            row_norm.get("invoice_date")
            or row_norm.get("date")
            or row_norm.get("idt")
            or ""
        )
        if not date_raw:
            raise ValueError(
                f"Row {row_idx}: missing invoice date (tried columns: invoice_date, date, idt) — refusing to fabricate one"
            )
        idt = normalize_date_str(date_raw, context=f"Row {row_idx} column 'invoice_date'")
        ctin = row_norm.get("supplier_gstin") or row_norm.get("gstin") or row_norm.get("ctin") or ""
        pos = row_norm.get("pos") or ""

        txval = _money(row_norm, ("taxable_value", "txval", "taxable_amount"), row_idx)
        iamt = _money(row_norm, ("igst", "iamt", "igst_amount"), row_idx)
        camt = _money(row_norm, ("cgst", "camt", "cgst_amount"), row_idx)
        samt = _money(row_norm, ("sgst", "samt", "sgst_amount"), row_idx)
        csamt = _money(row_norm, ("cess", "csamt"), row_idx)

        is_blocked = (
            row_norm.get("is_blocked_17_5", "").lower() in ["true", "yes", "y", "1"] or
            row_norm.get("blocked", "").lower() in ["true", "yes", "y", "1"]
        )
        try:
            unpaid_days = int(float(row_norm.get("unpaid_days", "") or 0))
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

    lower_file = input_file.lower()
    if lower_file.endswith(".csv"):
        purchases = parse_csv_purchases(input_file)
    elif lower_file.endswith(".json"):
        with open(input_file, "r", encoding="utf-8") as f:
            purchases = json.load(f)
    else:
        sys.exit("Error: Currently .csv and .json files are supported.")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"purchases": purchases}, f, indent=2)

    print(f"SUCCESS: Parsed {len(purchases)} purchase invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
