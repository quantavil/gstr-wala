"""Centralized statutory rules, thresholds, and regex patterns for Indian GST compliance."""

import re

# Statutory Thresholds
B2CL_THRESHOLD: float = 100000.0  # ₹1 Lakh effective August 1, 2024 (Notification No. 12/2024-CT)

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

# Standard GST Tax Rates
VALID_RATES = {0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 6.0, 12.0, 18.0, 28.0}

# Regular Expression Patterns
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
DATE_REGEX = re.compile(r"^(0[1-9]|[12][0-9]|3[01])-(0[1-9]|1[0-2])-20[2-9][0-9]$")
PERIOD_REGEX = re.compile(r"^(0[1-9]|1[0-2])20[2-9][0-9]$")

# Base-36 Character set for Mod-36 GSTIN Checksum
CHAR_SET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
