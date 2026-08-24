#!/usr/bin/env python3
"""Parses CSV, Excel, or JSON sales registers into canonical gstr1_input.json.

Handles standard accounting columns:
  - Invoice Number, Date, Customer GSTIN, Customer Name, Place of Supply (POS),
  - Taxable Value, GST Rate, IGST, CGST, SGST, Cess, Total Invoice Value,
  - HSN/SAC Code, Description, Unit Quantity Code (UQC), Quantity, Export Type.

Truthfulness contract:
  - Missing required fields (invoice number, invoice date) raise ValueError —
    no fabricated dates or coalesced placeholders.
  - Money fields are parsed truthfully (accounting negatives, currency symbols,
    Indian grouping); garbage raises instead of becoming a plausible number.
  - Taxes are NEVER derived from rate unless `derive_taxes=True` is explicitly
    passed; otherwise a missing tax column set is a loud error.
  - Optional fields absent from the source stay empty/None — never invented.

Usage:
  python3 scripts/parse_sales_register.py <sales_register.csv|xlsx|json> <gstin> <fp> [output.json] [--derive-taxes]
"""

import argparse
import csv
import json
import os
import sys

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any

from scripts.utils import excel_cell_to_str, normalize_date_str, safe_float_strict

_INUM_ALIASES = ("invoice_number", "inv_num", "inum", "invoice no", "invoice_no")
_DATE_ALIASES = ("invoice_date", "date", "idt")
_CTIN_ALIASES = ("customer_gstin", "gstin", "ctin")
_POS_ALIASES = ("pos", "place_of_supply", "state_code")
_TXVAL_ALIASES = ("taxable_value", "txval", "taxable_amount")
_RATE_ALIASES = ("gst_rate", "rate", "rt")
_IGST_ALIASES = ("igst", "iamt", "igst_amount")
_CGST_ALIASES = ("cgst", "camt", "cgst_amount")
_SGST_ALIASES = ("sgst", "samt", "sgst_amount")
_CESS_ALIASES = ("cess", "csamt")
_TAX_COL_ALIASES = _IGST_ALIASES + _CGST_ALIASES + _SGST_ALIASES


def _pick(row_norm: dict[str, str], aliases: tuple) -> str:
    """Returns the first non-blank value among aliases, else ''."""
    for alias in aliases:
        val = row_norm.get(alias)
        if val:
            return val
    return ""


def _money(
    row_norm: dict[str, str],
    aliases: tuple,
    row_idx: int,
    required: bool = False,
) -> float:
    """Parses an optional money field truthfully.

    Absent/blank cell -> 0.0 (blank means zero charge, not garbage).
    Present-but-unparseable -> ValueError naming the row and column.
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
    if required:
        raise ValueError(
            f"Row {row_idx}: missing required taxable value "
            f"(tried columns: {', '.join(aliases)})"
        )
    return 0.0


def parse_rows_sales(
    rows: list[dict[str, Any]], gstin: str, fp: str, derive_taxes: bool = False
) -> dict[str, Any]:
    """Normalizes generic row dictionaries into canonical GSTR-1 invoices."""
    if not rows:
        raise ValueError("Sales register contains no data rows — cannot produce GSTR-1 input from an empty register.")

    # Does the register actually carry IGST/CGST/SGST columns anywhere? Shared
    # by the CSV and Excel entry points (both funnel through this function).
    all_keys: set = set()
    for row in rows:
        all_keys.update(str(k).strip().lower() for k in row if k is not None)
    tax_alias_present = any(alias in all_keys for alias in _TAX_COL_ALIASES)

    invoices_map: dict[str, dict[str, Any]] = {}

    for row_idx, row in enumerate(rows, start=1):
        # excel_cell_to_str: None->"", int-valued floats de-poisoned ("1001.0"->"1001"),
        # datetimes -> canonical DD-MM-YYYY.
        row_norm = {
            str(k).strip().lower(): excel_cell_to_str(v)
            for k, v in row.items()
            if k is not None
        }

        inum = _pick(row_norm, _INUM_ALIASES)
        if not inum or inum == "INV-UNKNOWN":
            raise ValueError(f"Row {row_idx}: missing invoice number (tried columns: {', '.join(_INUM_ALIASES)}) — cannot use INV-UNKNOWN coalesce")
        date_raw = _pick(row_norm, _DATE_ALIASES)
        if not date_raw:
            raise ValueError(
                f"Row {row_idx}: missing invoice date (tried columns: {', '.join(_DATE_ALIASES)}) — refusing to fabricate one"
            )
        idt = normalize_date_str(date_raw, context=f"Row {row_idx} column 'invoice_date'")
        ctin = _pick(row_norm, _CTIN_ALIASES)
        pos = _pick(row_norm, _POS_ALIASES) or (ctin[:2] if ctin else gstin[:2])

        txval = _money(row_norm, _TXVAL_ALIASES, row_idx, required=True)
        rt = _money(row_norm, _RATE_ALIASES, row_idx)
        iamt = _money(row_norm, _IGST_ALIASES, row_idx)
        camt = _money(row_norm, _CGST_ALIASES, row_idx)
        samt = _money(row_norm, _SGST_ALIASES, row_idx)
        csamt = _money(row_norm, _CESS_ALIASES, row_idx)

        hsn = _pick(row_norm, ("hsn", "hsn_code", "hsn_sc"))
        desc = _pick(row_norm, ("description", "item_description", "desc"))
        uqc = _pick(row_norm, ("uqc", "unit"))
        qty_raw = _pick(row_norm, ("quantity", "qty"))
        qty: float | None
        if qty_raw:
            try:
                qty = safe_float_strict(qty_raw)
            except ValueError:
                raise ValueError(
                    f"Row {row_idx}: column 'quantity' has unparseable value {qty_raw!r}"
                )
        else:
            qty = None
        exp_typ = row_norm.get("exp_typ") or row_norm.get("export_type") or ("WOPAY" if pos == "97" and rt == 0 else None)

        # Tax truthfulness: distinguish tax columns ABSENT from the register vs
        # tax columns PRESENT with explicit/blank zero cells. User-provided
        # zeros (e.g. exempt supplies whose template auto-populates the rate)
        # are respected — never overwritten by derivation, only warned about.
        # Derivation applies solely when the file has no tax alias columns at
        # all, and only when the caller explicitly opts in via derive_taxes.
        supplier_state = gstin[:2]
        is_interstate = (pos != supplier_state)
        taxes_all_zero = (iamt == 0 and camt == 0 and samt == 0)
        needs_tax_amounts = (rt > 0 and txval > 0 and exp_typ != "WOPAY")
        if needs_tax_amounts and taxes_all_zero:
            if not tax_alias_present and not derive_taxes:
                raise ValueError(
                    f"Row {row_idx}: no tax amounts found for invoice '{inum}' with GST rate "
                    f"{rt}% and taxable value ₹{txval:,.2f}. Tried IGST columns "
                    f"({', '.join(_IGST_ALIASES)}), CGST columns ({', '.join(_CGST_ALIASES)}), "
                    f"SGST columns ({', '.join(_SGST_ALIASES)}). Refusing to fabricate tax "
                    f"amounts — pass derive_taxes=True to compute them from the rate."
                )
            elif not tax_alias_present and derive_taxes:
                if is_interstate:
                    iamt = round((txval * rt) / 100.0, 2)
                else:
                    camt = round((txval * rt) / 200.0, 2)
                    samt = round((txval * rt) / 200.0, 2)
            else:
                print(
                    f"Row {row_idx}: WARNING invoice '{inum}': GST rate {rt:g}% with "
                    f"taxable value ₹{txval:,.2f} but zero tax cells "
                    f"(igst/cgst/sgst) — booked as zero",
                    file=sys.stderr,
                )

        existing = invoices_map.get(inum)
        if existing:
            prev_ctin = existing.get("ctin", "")
            cur_ctin = ctin.upper() if ctin else ""
            if prev_ctin and cur_ctin and prev_ctin != cur_ctin:
                raise ValueError(
                    f"Row {row_idx}: invoice number '{inum}' already booked under "
                    f"GSTIN '{prev_ctin}' but this row declares '{cur_ctin}' — conflicting "
                    f"counterparty for the same invoice number; split or correct the register"
                )
            if cur_ctin and not prev_ctin:
                # First occurrence(s) had a blank GSTIN; backfill so a later
                # conflicting counterparty is still detected.
                existing["ctin"] = cur_ctin
        else:
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


def parse_csv_sales(csv_path: str, gstin: str, fp: str, derive_taxes: bool = False) -> dict[str, Any]:
    """Parses standard CSV sales register into canonical format."""
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return parse_rows_sales(rows, gstin, fp, derive_taxes=derive_taxes)


def parse_excel_sales(excel_path: str, gstin: str, fp: str, derive_taxes: bool = False) -> dict[str, Any]:
    """Parses Excel (.xlsx, .xls, .xlsb) sales register using fast Calamine engine."""
    from scripts.reconcile_fast import read_excel_calamine

    rows = read_excel_calamine(excel_path)
    return parse_rows_sales(rows, gstin, fp, derive_taxes=derive_taxes)


def main():
    parser = argparse.ArgumentParser(
        prog="parse_sales_register.py",
        description="Parses a CSV/Excel/JSON sales register into canonical GSTR-1 input JSON.",
    )
    parser.add_argument("sales_file", help="Sales register file (.csv, .xlsx, .xls, .xlsb or .json)")
    parser.add_argument("gstin", help="Supplier GSTIN")
    parser.add_argument("fp", help="Filing period, e.g. 042026")
    parser.add_argument(
        "out_file", nargs="?", default="gstr1_input.json",
        help="Output path (default: gstr1_input.json)",
    )
    parser.add_argument(
        "--derive-taxes", action="store_true", dest="derive_taxes",
        help="Derive tax amounts from the GST rate when the register has no "
             "IGST/CGST/SGST columns at all (never overrides populated cells)",
    )
    args = parser.parse_args()

    sales_file = args.sales_file
    out_file = args.out_file
    if not os.path.exists(sales_file):
        sys.exit(f"Error: File '{sales_file}' not found.")

    lower_file = sales_file.lower()
    try:
        if lower_file.endswith(".csv"):
            canonical = parse_csv_sales(sales_file, args.gstin, args.fp, derive_taxes=args.derive_taxes)
        elif lower_file.endswith((".xlsx", ".xls", ".xlsb")):
            canonical = parse_excel_sales(sales_file, args.gstin, args.fp, derive_taxes=args.derive_taxes)
        elif lower_file.endswith(".json"):
            with open(sales_file, "r", encoding="utf-8") as f:
                canonical = json.load(f)
        else:
            sys.exit("Error: Unsupported file format. Supported: .csv, .xlsx, .xls, .xlsb, .json")
    except ValueError as exc:
        sys.exit(f"Error: {exc}")

    if not isinstance(canonical, dict) or not canonical.get("invoices"):
        sys.exit(f"Error: '{sales_file}' contains no data rows — nothing to file.")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2)

    invoices_list = canonical.get("invoices") or []
    print(f"SUCCESS: Parsed {len(invoices_list)} invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
