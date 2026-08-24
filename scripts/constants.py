"""Centralized statutory rules, thresholds, and regex patterns for Indian GST compliance.

Note:
  - `section_50_3_wrong_avail_utilized_p_a` (24% p.a.) is DECLARED-BUT-UNUSED in current
    statutory calculators; Section 50(1) (18% p.a.) on net cash tax liability is enforced.
"""

import json
import os
import re
import warnings
from typing import Any

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "rules_manifest.json")


def _load_manifest() -> dict[str, Any]:
    try:
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        warnings.warn(
            f"Could not load statutory rules manifest from {_MANIFEST_PATH}: {e}. "
            "Falling back to embedded statutory defaults.",
            UserWarning,
            stacklevel=2,
        )
        return {}


_m = _load_manifest()
_stat = _m.get("statutory_rules", {})

# Statutory Thresholds — single source from rules_manifest.json with fallback
B2CL_THRESHOLD: float = float(_stat.get("b2cl_threshold", {}).get("value", 100000.0))
VALID_RATES = set(_stat.get("statutory_gst_rates", [0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0]))
DRC_01B_PCT: float = float(
    _stat.get("drc_surveillance_thresholds", {}).get("drc_01b_rule_88c", {}).get("percentage_threshold", 20.0)
)
DRC_01B_AMT: float = float(
    _stat.get("drc_surveillance_thresholds", {}).get("drc_01b_rule_88c", {}).get("amount_threshold", 2500000.0)
)
DRC_01C_PCT: float = float(
    _stat.get("drc_surveillance_thresholds", {}).get("drc_01c_rule_88d", {}).get("percentage_threshold", 10.0)
)
DRC_01C_AMT: float = float(
    _stat.get("drc_surveillance_thresholds", {}).get("drc_01c_rule_88d", {}).get("amount_threshold", 100000.0)
)


def reload_manifest() -> None:
    """Reloads manifest dynamically and refreshes statutory thresholds."""
    global _m, _stat, B2CL_THRESHOLD, VALID_RATES, DRC_01B_PCT, DRC_01B_AMT, DRC_01C_PCT, DRC_01C_AMT
    _m = _load_manifest()
    _stat = _m.get("statutory_rules", {})
    B2CL_THRESHOLD = float(_stat.get("b2cl_threshold", {}).get("value", 100000.0))
    VALID_RATES = set(_stat.get("statutory_gst_rates", [0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0]))
    DRC_01B_PCT = float(
        _stat.get("drc_surveillance_thresholds", {}).get("drc_01b_rule_88c", {}).get("percentage_threshold", 20.0)
    )
    DRC_01B_AMT = float(
        _stat.get("drc_surveillance_thresholds", {}).get("drc_01b_rule_88c", {}).get("amount_threshold", 2500000.0)
    )
    DRC_01C_PCT = float(
        _stat.get("drc_surveillance_thresholds", {}).get("drc_01c_rule_88d", {}).get("percentage_threshold", 10.0)
    )
    DRC_01C_AMT = float(
        _stat.get("drc_surveillance_thresholds", {}).get("drc_01c_rule_88d", {}).get("amount_threshold", 100000.0)
    )


BLOCKED_HSNS = {"8702", "8703", "8704", "9963", "9965", "9966", "9967"}

# Valid Indian State / Union Territory codes (01-38, 97)
# Note: 25 merged into 26 (DNH & DD) in 2020; 28 (Old AP) deprecated to 37.
STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand",
    "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory"
}

# Regular Expression Patterns
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
DATE_REGEX = re.compile(r"^(0[1-9]|[12][0-9]|3[01])-(0[1-9]|1[0-2])-20[2-9][0-9]$")
PERIOD_REGEX = re.compile(r"^(0[1-9]|1[0-2])20[2-9][0-9]$")

# Base-36 Character set for Mod-36 GSTIN Checksum
CHAR_SET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def compute_gstin_checksum(gstin14: str) -> str:
    """Computes the 15th check digit for a 14-character GSTIN string using Mod-36."""
    factor = 1
    total = 0
    for char in gstin14:
        if char not in CHAR_SET:
            raise ValueError(f"Invalid character {char!r} in GSTIN '{gstin14}': not in CHAR_SET")
        code_point = CHAR_SET.index(char)
        addend = factor * code_point
        factor = 1 if factor == 2 else 2
        addend = (addend // 36) + (addend % 36)
        total += addend
    remainder = total % 36
    check_code = (36 - remainder) % 36
    return CHAR_SET[check_code]


def detect_return_type(data: dict[str, Any]) -> str:
    """Determines whether a payload is GSTR-1 or GSTR-3B using explicit key or structural inference."""
    if not isinstance(data, dict):
        raise TypeError("Payload must be a dictionary")
    if "return_type" in data:
        rt = str(data["return_type"]).strip().upper()
        if rt in ("GSTR-1", "GSTR1"):
            return "GSTR-1"
        if rt in ("GSTR-3B", "GSTR3B"):
            return "GSTR-3B"
        raise ValueError(f"Invalid return_type: {data['return_type']!r}. Expected 'GSTR-1' or 'GSTR-3B'.")

    has_gstr1 = "invoices" in data or "fp" in data
    has_gstr3b = "ret_period" in data or "outward_supplies" in data

    if has_gstr1 and has_gstr3b:
        raise ValueError("ambiguous payload: contains both GSTR-1 and GSTR-3B keys; set return_type explicitly")
    if has_gstr1:
        return "GSTR-1"
    if has_gstr3b:
        return "GSTR-3B"
    raise ValueError("Unable to determine return type: payload matches neither GSTR-1 nor GSTR-3B structure.")


def get_interest_rate_50_1() -> float:
    """Returns Section 50(1) annual interest rate on net cash liability (e.g. 0.18 for 18% p.a.)."""
    m = _load_manifest()
    return float(m.get("statutory_rules", {}).get("interest_rates", {}).get("section_50_1_net_cash_p_a", 0.18))


def get_late_fee_caps() -> dict[str, float]:
    """Returns Section 47 statutory late fee rates and caps dictionary."""
    m = _load_manifest()
    caps = m.get("statutory_rules", {}).get("late_fee_caps", {})
    return {
        "nil_return_daily_cgst": float(caps.get("nil_return_daily_cgst", 10.0)),
        "nil_return_daily_sgst": float(caps.get("nil_return_daily_sgst", 10.0)),
        "nil_return_max_cap_total": float(caps.get("nil_return_max_cap_total", 500.0)),
        "upto_1.5cr_daily_cgst": float(caps.get("upto_1.5cr_daily_cgst", 25.0)),
        "upto_1.5cr_daily_sgst": float(caps.get("upto_1.5cr_daily_sgst", 25.0)),
        "upto_1.5cr_max_cap_total": float(caps.get("upto_1.5cr_max_cap_total", 2000.0)),
        "slab_1.5cr_to_5cr_max_cap_total": float(caps.get("slab_1.5cr_to_5cr_max_cap_total", 5000.0)),
        "above_5cr_max_cap_total": float(caps.get("above_5cr_max_cap_total", 10000.0)),
    }
