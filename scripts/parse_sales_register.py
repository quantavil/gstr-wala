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
  python3 scripts/parse_sales_register.py <sales_register.csv|xlsx|json> <gstin> <fp> [output.json]
"""

import csv
import json
import os
import sys

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List, Optional
from scripts.utils import excel_cell_to_str, normalize_date_str, safe_float_strict
from scripts.validate_gst_input import compute_gstin_checksum, is_valid_gstin

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


def _pick(row_norm: Dict[str, str], aliases: tuple) -> str:
    """Returns the first non-blank value among aliases, else ''."""
    for alias in aliases:
        val = row_norm.get(alias)
        if val:
            return val
    return ""


def _money(
    row_norm: Dict[str, str],
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
    rows: List[Dict[str, Any]], gstin: str, fp: str, derive_taxes: bool = False
) -> Dict[str, Any]:
    """Normalizes generic row dictionaries into canonical GSTR-1 invoices."""
    if not rows:
        raise ValueError("Sales register contains no data rows — cannot produce GSTR-1 input from an empty register.")

    # Does the register actually carry IGST/CGST/SGST columns anywhere? Shared
    # by the CSV and Excel entry points (both funnel through this function).
    all_keys: set = set()
    for row in rows:
        all_keys.update(str(k).strip().lower() for k in row.keys() if k is not None)
    tax_alias_present = any(alias in all_keys for alias in _TAX_COL_ALIASES)

    invoices_map: Dict[str, Dict[str, Any]] = {}

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
        qty: Optional[float]
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


def parse_csv_sales(csv_path: str, gstin: str, fp: str, derive_taxes: bool = False) -> Dict[str, Any]:
    """Parses standard CSV sales register into canonical format."""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return parse_rows_sales(rows, gstin, fp, derive_taxes=derive_taxes)


def parse_excel_sales(excel_path: str, gstin: str, fp: str, derive_taxes: bool = False) -> Dict[str, Any]:
    """Parses Excel (.xlsx, .xls, .xlsb) sales register using fast Calamine engine."""
    from scripts.reconcile_fast import read_excel_calamine

    rows = read_excel_calamine(excel_path)
    return parse_rows_sales(rows, gstin, fp, derive_taxes=derive_taxes)


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
    try:
        if lower_file.endswith(".csv"):
            canonical = parse_csv_sales(sales_file, gstin, fp)
        elif lower_file.endswith((".xlsx", ".xls", ".xlsb")):
            canonical = parse_excel_sales(sales_file, gstin, fp)
        elif lower_file.endswith(".json"):
            with open(sales_file, "r", encoding="utf-8") as f:
                canonical = json.load(f)
        else:
            sys.exit("Error: Unsupported file format. Supported: .csv, .xlsx, .xls, .xlsb, .json")
    except ValueError as exc:
        sys.exit(f"Error: {exc}")

    if not isinstance(canonical, dict) or not canonical.get("invoices"):
        raise ValueError(f"'{sales_file}' contains no data rows — nothing to file.")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2)

    print(f"SUCCESS: Parsed {len(canonical.get('invoices'))} invoice(s) -> '{out_file}'")


if __name__ == "__main__":
    main()
