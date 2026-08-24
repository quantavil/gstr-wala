#!/usr/bin/env python3
"""Strict validator for GST inputs (GSTR-1 and GSTR-3B) consumed by gstr-wala engines.

Validates:
  - 15-character GSTIN structure and Mod-36 checksum
  - 2-digit Indian State Codes & Place of Supply (POS) rules
  - Inter-state (IGST) vs Intra-state (CGST+SGST) tax split consistency
  - Tax calculation consistency within +/- 1 Rupee tolerance
  - B2CL threshold (₹1,00,000 per Notification 12/2024-CT)
  - HSN code format (4, 6, or 8 digits)
  - Non-negativity and date format validation (DD-MM-YYYY)
  - Credential and password blocking

Usage:
  python3 scripts/validate_gst_input.py <input.json> [--json]
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.constants import (
    B2CL_THRESHOLD,
    CHAR_SET,
    DATE_REGEX,
    GSTIN_REGEX,
    PERIOD_REGEX,
    STATE_CODES,
    VALID_RATES,
)

if sys.version_info < (3, 12):
    sys.exit(f"gstr-wala requires Python 3.12+ (found {sys.version_info.major}.{sys.version_info.minor})")


def compute_gstin_checksum(gstin14: str) -> str:
    """Computes the 15th check digit for a 14-character GSTIN string using Mod-36."""
    factor = 1
    total = 0
    for char in gstin14:
        code_point = CHAR_SET.index(char)
        addend = factor * code_point
        factor = 1 if factor == 2 else 2
        addend = (addend // 36) + (addend % 36)
        total += addend
    remainder = total % 36
    check_code = (36 - remainder) % 36
    return CHAR_SET[check_code]


def is_valid_gstin(gstin: str) -> Tuple[bool, Optional[str]]:
    """Validates GSTIN regex and checksum."""
    if not isinstance(gstin, str):
        return False, "GSTIN must be a string"
    gstin = gstin.strip().upper()
    if not GSTIN_REGEX.match(gstin):
        return False, f"Invalid GSTIN format: '{gstin}' (must be 15 alphanumeric characters matching standard pattern)"
    state_code = gstin[:2]
    if state_code not in STATE_CODES:
        return False, f"Invalid State Code '{state_code}' in GSTIN '{gstin}'"
    
    # Verify Mod-36 Checksum
    expected_check = compute_gstin_checksum(gstin[:14])
    if gstin[14] != expected_check:
        return False, f"GSTIN checksum mismatch for '{gstin}': expected check digit '{expected_check}', found '{gstin[14]}'"
    return True, None


class ValidationResult:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def validate_gstr1_input(data: Dict[str, Any]) -> ValidationResult:
    """Validates canonical GSTR-1 input JSON."""
    result = ValidationResult()

    # Top-level required fields
    if "gstin" not in data:
        result.error("Missing required top-level field: 'gstin'")
    else:
        valid_gstin, err = is_valid_gstin(data["gstin"])
        if not valid_gstin:
            result.error(err or "Invalid GSTIN")

    if "fp" not in data:
        result.error("Missing required top-level field: 'fp' (Return Period MMYYYY)")
    elif not isinstance(data["fp"], str) or not PERIOD_REGEX.match(data["fp"]):
        result.error(f"Invalid 'fp' format: '{data.get('fp')}'. Expected MMYYYY (e.g., '042026')")

    supplier_state = data.get("gstin", "")[:2]

    # Invoices validation
    invoices = data.get("invoices", [])
    if not isinstance(invoices, list):
        result.error("'invoices' must be a list")
        return result

    seen_invoice_numbers = set()

    for idx, inv in enumerate(invoices):
        prefix = f"Invoice #{idx + 1}"
        inum = inv.get("inum")
        if not inum or not isinstance(inum, str):
            result.error(f"{prefix}: Missing or invalid 'inum' (Invoice Number)")
        else:
            if inum in seen_invoice_numbers:
                result.error(f"{prefix}: Duplicate invoice number '{inum}' found")
            seen_invoice_numbers.add(inum)
            prefix = f"Invoice '{inum}'"

        # Date validation — regex + calendar check (reject 31-02-2026 etc.)
        idt = inv.get("idt")
        if not idt or not isinstance(idt, str) or not DATE_REGEX.match(idt):
            result.error(f"{prefix}: Invalid 'idt' date '{idt}'. Expected DD-MM-YYYY format.")
        else:
            try:
                from datetime import datetime

                datetime.strptime(idt, "%d-%m-%Y")
            except ValueError:
                result.error(f"{prefix}: Invalid calendar date '{idt}'")

        # POS validation
        pos = inv.get("pos")
        if not pos or pos not in STATE_CODES:
            result.error(f"{prefix}: Invalid Place of Supply (POS) code '{pos}'")

        # Recipient GSTIN check (for B2B)
        ctin = inv.get("ctin")
        is_b2b = bool(ctin)
        if is_b2b:
            valid_ctin, err = is_valid_gstin(ctin)
            if not valid_ctin:
                result.error(f"{prefix}: Invalid recipient GSTIN 'ctin': {err}")

        # Items validation
        items = inv.get("items", [])
        if not isinstance(items, list) or len(items) == 0:
            result.error(f"{prefix}: Must contain at least one item in 'items'")
            continue

        calc_inv_val = 0.0
        is_interstate = (pos != supplier_state) and (pos != "") and (supplier_state != "")

        for item_idx, itm in enumerate(items):
            item_pfx = f"{prefix} Item #{item_idx + 1}"
            import math
            from scripts.utils import safe_float as _sf

            txval = _sf(itm.get("txval", 0.0), default=float("nan"))
            rt = _sf(itm.get("rt", 0.0), default=float("nan"))
            iamt = _sf(itm.get("iamt", 0.0), default=float("nan"))
            camt = _sf(itm.get("camt", 0.0), default=float("nan"))
            samt = _sf(itm.get("samt", 0.0), default=float("nan"))
            csamt = _sf(itm.get("csamt", 0.0), default=float("nan"))

            # finite check
            for field_name, val in [("txval", txval), ("rt", rt), ("iamt", iamt), ("camt", camt), ("samt", samt), ("csamt", csamt)]:
                if not isinstance(val, (int, float)) or not math.isfinite(val):
                    result.error(f"{item_pfx}: '{field_name}' is not a finite number ({val})")
                    continue

            if txval < 0:
                result.error(f"{item_pfx}: 'txval' cannot be negative ({txval})")
            if iamt < 0 or camt < 0 or samt < 0 or csamt < 0:
                result.error(f"{item_pfx}: tax amounts cannot be negative (iamt={iamt}, camt={camt}, samt={samt}, csamt={csamt})")
            if float(rt) not in VALID_RATES:
                result.error(f"{item_pfx}: Invalid GST rate '{rt}%'. Allowed rates: {sorted(list(VALID_RATES))}")

            # Inter-state vs Intra-state tax allocation check
            if is_interstate:
                if camt > 0 or samt > 0:
                    result.error(f"{item_pfx}: Inter-state supply (Supplier {supplier_state} != POS {pos}) cannot have CGST ({camt}) or SGST ({samt}). Must charge IGST.")
                from scripts.utils import round_cur as _rc

                expected_iamt = _rc((txval * rt) / 100.0)
                if abs(expected_iamt - iamt) > 1.0:
                    result.warn(f"{item_pfx}: IGST ₹{iamt} deviates from calculated ₹{expected_iamt} (txval ₹{txval} @ {rt}%)")
            else:
                if iamt > 0:
                    result.error(f"{item_pfx}: Intra-state supply (Supplier {supplier_state} == POS {pos}) cannot have IGST ({iamt}). Must charge CGST + SGST.")
                from scripts.utils import round_cur as _rc2

                expected_half = _rc2((txval * rt) / 200.0)
                if abs(expected_half - camt) > 1.0:
                    result.warn(f"{item_pfx}: CGST ₹{camt} deviates from calculated ₹{expected_half} (txval ₹{txval} @ {rt}/2%)")
                if abs(expected_half - samt) > 1.0:
                    result.warn(f"{item_pfx}: SGST ₹{samt} deviates from calculated ₹{expected_half} (txval ₹{txval} @ {rt}/2%)")

            # HSN code check — error (portal rejects)
            hsn = itm.get("hsn_sc")
            if hsn:
                hsn_str = str(hsn).strip()
                if not (len(hsn_str) in [4, 6, 8] and hsn_str.isdigit()):
                    result.error(f"{item_pfx}: HSN/SAC '{hsn_str}' must be 4, 6, or 8 digits")

            calc_inv_val += (txval + iamt + camt + samt + csamt)

        inv_val = inv.get("val")
        if inv_val is not None:
            if abs(inv_val - calc_inv_val) > 2.0:
                result.warn(f"{prefix}: Total invoice value ₹{inv_val} deviates from sum of items ₹{round(calc_inv_val, 2)}")

        # B2CL threshold check
        if not is_b2b and is_interstate:
            effective_val = inv_val if inv_val is not None else calc_inv_val
            if effective_val > B2CL_THRESHOLD:
                if not pos:
                    result.error(f"{prefix}: B2CL large invoice (₹{effective_val:,.2f} > ₹1 Lakh) requires explicit Place of Supply (POS)")
                if not inum:
                    result.error(f"{prefix}: B2CL large invoice requires explicit invoice number for Table 5 reporting")
            else:
                if effective_val <= 0:
                    result.error(f"{prefix}: B2C invoice value must be greater than 0")

    return result


def validate_gstr3b_input(data: Dict[str, Any]) -> ValidationResult:
    """Validates canonical GSTR-3B input JSON."""
    result = ValidationResult()

    if "gstin" not in data:
        result.error("Missing required field: 'gstin'")
    else:
        valid_gstin, err = is_valid_gstin(data["gstin"])
        if not valid_gstin:
            result.error(err or "Invalid GSTIN")

    if "ret_period" not in data:
        result.error("Missing required field: 'ret_period'")
    elif not isinstance(data["ret_period"], str) or not PERIOD_REGEX.match(data["ret_period"]):
        result.error(f"Invalid 'ret_period' format: '{data.get('ret_period')}'. Expected MMYYYY.")

    # Dates — calendar validation extra
    for dt_field in ["due_date", "filing_date"]:
        if dt_field in data and data[dt_field]:
            if not DATE_REGEX.match(data[dt_field]):
                result.error(f"Invalid '{dt_field}' date '{data[dt_field]}'. Expected DD-MM-YYYY.")
            else:
                try:
                    from datetime import datetime

                    datetime.strptime(data[dt_field], "%d-%m-%Y")
                except ValueError:
                    result.error(f"Invalid calendar date for '{dt_field}': '{data[dt_field]}'")

    # Outward liability checks
    outward = data.get("outward_supplies", {})
    if outward:
        for section, vals in outward.items():
            if isinstance(vals, dict):
                for k, v in vals.items():
                    if isinstance(v, (int, float)) and v < 0:
                        result.error(f"Outward supplies '{section}.{k}' cannot be negative ({v})")

    # ITC Checks
    itc = data.get("itc", {})
    if itc:
        for section, vals in itc.items():
            if isinstance(vals, dict):
                for cat, cat_vals in vals.items():
                    if isinstance(cat_vals, dict):
                        for k, v in cat_vals.items():
                            if isinstance(v, (int, float)) and v < 0:
                                result.error(f"ITC '{section}.{cat}.{k}' cannot be negative ({v})")

    # Opening ledgers non-negativity
    for ledger in ["opening_credit_ledger", "opening_cash_ledger"]:
        led_data = data.get(ledger, {})
        if isinstance(led_data, dict):
            for k, v in led_data.items():
                if isinstance(v, (int, float)) and v < 0:
                    result.error(f"Ledger balance '{ledger}.{k}' cannot be negative ({v})")

    return result


def validate_file(file_path: str) -> ValidationResult:
    """Detects return type and runs validation."""
    if not os.path.exists(file_path):
        res = ValidationResult()
        res.error(f"File not found: '{file_path}'")
        return res

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        res = ValidationResult()
        res.error(f"JSON Parse Error in '{file_path}': {str(e)}")
        return res

    if not isinstance(data, dict):
        res = ValidationResult()
        res.error(f"Root element must be a JSON object in '{file_path}'")
        return res

    # Check for accidental credential leaks — recursive key scan
    def _collect_keys(obj, out):
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.append(str(k))
                _collect_keys(v, out)
        elif isinstance(obj, list):
            for it in obj:
                _collect_keys(it, out)

    _keys: list[str] = []
    _collect_keys(data, _keys)

    _keys_lower = [k.lower() for k in _keys]
    blocked_substrings = ["password", "passwd", "pwd", "secret", "otp", "auth_token", "app_key", "api_key", "private_key"]
    for k in _keys_lower:
        for blk in blocked_substrings:
            if blk in k:
                res = ValidationResult()
                res.error(f"Security Alert: Sensitive field '{k}' contains blocked substring '{blk}'. Remove credentials before validation.")
                return res

    if "invoices" in data or "fp" in data:
        return validate_gstr1_input(data)
    elif "ret_period" in data or "outward_supplies" in data or "itc" in data:
        return validate_gstr3b_input(data)
    else:
        res = ValidationResult()
        res.error("Unrecognized GST input format. Must contain either 'invoices' (GSTR-1) or 'outward_supplies' / 'itc' (GSTR-3B).")
        return res


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_gst_input.py <input.json> [--json]")
        sys.exit(1)

    file_path = sys.argv[1]
    json_output = "--json" in sys.argv

    result = validate_file(file_path)

    if json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.is_valid:
            print(f"PASS: '{file_path}' is valid.")
            if result.warnings:
                print(f"\n{len(result.warnings)} Warning(s):")
                for w in result.warnings:
                    print(f"  [!] {w}")
        else:
            print(f"FAIL: '{file_path}' has {len(result.errors)} error(s):")
            for e in result.errors:
                print(f"  [X] {e}")
            if result.warnings:
                print(f"\n{len(result.warnings)} Warning(s):")
                for w in result.warnings:
                    print(f"  [!] {w}")

    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
