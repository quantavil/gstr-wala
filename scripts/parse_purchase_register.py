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

from typing import Any

from scripts.utils import excel_cell_to_str, normalize_date_str, round_cur, safe_float_strict


def _money(row_norm: dict[str, str], aliases: tuple, row_idx: int) -> float:
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
            ) from None
    return 0.0


def parse_csv_purchases(csv_path: str) -> list[dict[str, Any]]:
    """Parses standard CSV purchase register."""
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return _parse_purchase_rows(rows, source_label=csv_path)


def _parse_purchase_rows(rows: list[dict[str, Any]], source_label: str = "purchase_register") -> list[dict[str, Any]]:
    """Shared row parser for CSV/Excel purchase registers (HSN + unpaid_value aware)."""
    if not rows:
        raise ValueError(f"Purchase register '{source_label}' contains no data rows — cannot reconcile against an empty register.")
    purchases: list[dict[str, Any]] = []
    for row_idx, row in enumerate(rows, start=1):
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
        date_raw = ""
        date_alias = ""
        for alias in ("invoice_date", "date", "idt"):
            val = row_norm.get(alias)
            if val:
                date_raw = val
                date_alias = alias
                break
        if not date_raw:
            raise ValueError(f"Row {row_idx}: missing invoice date (tried columns: invoice_date, date, idt) — refusing to fabricate one")
        idt = normalize_date_str(date_raw, context=f"Row {row_idx} column '{date_alias}'")
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
        hsn_sc = ""
        for _hsn_alias in ("hsn_sc", "hsn_code", "hsn", "sac"):
            _hsn_val = row_norm.get(_hsn_alias)
            if _hsn_val:
                hsn_sc = str(_hsn_val).strip()
                break
        unpaid_value: float | None = None
        for _uv_alias in ("unpaid_value", "unpaid_amount", "balance_payable"):
            _uv_raw = row_norm.get(_uv_alias)
            if _uv_raw:
                try:
                    unpaid_value = safe_float_strict(_uv_raw)
                except ValueError:
                    raise ValueError(f"Row {row_idx}: column '{_uv_alias}' has unparseable amount {_uv_raw!r}") from None
                break
        record: dict[str, Any] = {
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
            "unpaid_days": unpaid_days,
        }
        if hsn_sc:
            record["hsn_sc"] = hsn_sc
        if unpaid_value is not None:
            record["unpaid_value"] = round_cur(unpaid_value)
        purchases.append(record)
    return purchases


def parse_excel_purchases(excel_path: str) -> list[dict[str, Any]]:
    """Parses Excel (.xlsx, .xls, .xlsb) purchase register using Calamine engine."""
    from scripts.reconcile_fast import read_excel_calamine

    rows = read_excel_calamine(excel_path)
    return _parse_purchase_rows(rows, source_label=excel_path)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 parse_purchase_register.py <purchase_register.csv> [output.json]")
        sys.exit(1)

    input_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "purchase_register.json"

    if not os.path.exists(input_file):
        sys.exit(f"Error: File '{input_file}' not found.")

    lower_file = input_file.lower()
    try:
        if lower_file.endswith(".csv"):
            purchases = parse_csv_purchases(input_file)
        elif lower_file.endswith((".xlsx", ".xls", ".xlsb")):
            purchases = parse_excel_purchases(input_file)
        elif lower_file.endswith(".json"):
            with open(input_file, encoding="utf-8") as f:
                loaded = json.load(f)
            # Accept either a bare list or an already-wrapped document; never
            # double-wrap into {"purchases": {"purchases": [...]}}.
            purchases = loaded.get("purchases", []) if isinstance(loaded, dict) else loaded
            if not isinstance(purchases, list):
                sys.exit(
                    f"Error: '{input_file}' must contain a list of purchase "
                    f"invoices or an object with a 'purchases' array."
                )
        else:
            sys.exit("Error: Currently .csv, .xlsx, .xls, .xlsb and .json files are supported.")
    except ValueError as exc:
        sys.exit(f"Error: {exc}")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"purchases": purchases}, f, indent=2)

    print(f"SUCCESS: Parsed {len(purchases)} purchase invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
