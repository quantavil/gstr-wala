"""Centralized statutory rules, thresholds, and regex patterns for Indian GST compliance."""

import json
import os
import re

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "rules_manifest.json")


def _load_manifest():
    try:
        with open(_MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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
