"""Pytest test suite for validate_gst_input.py."""

import pytest
from scripts.validate_gst_input import (
    compute_gstin_checksum,
    is_valid_gstin,
    validate_gstr1_input,
    validate_gstr3b_input,
)


def test_gstin_checksum_valid():
    valid, err = is_valid_gstin("27AAAAA0000A1Z2")
    assert valid is True
    assert err is None

    valid, err = is_valid_gstin("29AAAAA0000A1ZY")
    assert valid is True


def test_gstin_invalid_checksum():
    valid, err = is_valid_gstin("27AAAAA0000A1Z9")
    assert valid is False
    assert "checksum mismatch" in err


def test_gstin_invalid_state():
    valid, err = is_valid_gstin("99AAAAA0000A1Z5")
    assert valid is False
    assert "Invalid State Code" in err


def test_gstin_obsolete_state_codes_rejected():
    # State 25 (Daman & Diu) merged to 26
    valid_25, err_25 = is_valid_gstin("25AAAAA0000A1Z6")
    assert valid_25 is False
    assert "Invalid State Code '25'" in err_25

    # State 28 (Andhra Pradesh Old) deprecated to 37
    valid_28, err_28 = is_valid_gstin("28AAAAA0000A1Z0")
    assert valid_28 is False
    assert "Invalid State Code '28'" in err_28

    # State 26 (Merged DNH & DD) must be valid
    valid_26, err_26 = is_valid_gstin(f"26AAAAA0000A1Z{compute_gstin_checksum('26AAAAA0000A1Z')}")
    assert valid_26 is True


def test_gstr1_valid_b2b_interstate():
    valid_ctin = f"29BBBBB1111B1Z{compute_gstin_checksum('29BBBBB1111B1Z')}"
    data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-001",
                "idt": "15-04-2026",
                "pos": "29",
                "ctin": valid_ctin,
                "val": 118000.0,
                "items": [
                    {
                        "txval": 100000.0,
                        "rt": 18.0,
                        "iamt": 18000.0,
                        "camt": 0.0,
                        "samt": 0.0,
                        "csamt": 0.0,
                        "hsn_sc": "8471"
                    }
                ]
            }
        ]
    }
    res = validate_gstr1_input(data)
    assert res.is_valid is True, f"Errors: {res.errors}"


def test_gstr1_interstate_cannot_have_cgst_sgst():
    valid_ctin = f"29BBBBB1111B1Z{compute_gstin_checksum('29BBBBB1111B1Z')}"
    data = {
        "gstin": "27AAAAA0000A1Z2",  # Maharashtra
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-001",
                "idt": "15-04-2026",
                "pos": "29",  # Karnataka (Inter-state)
                "ctin": valid_ctin,
                "items": [
                    {
                        "txval": 100000.0,
                        "rt": 18.0,
                        "iamt": 0.0,
                        "camt": 9000.0,  # Invalid: Inter-state cannot have CGST
                        "samt": 9000.0
                    }
                ]
            }
        ]
    }
    res = validate_gstr1_input(data)
    assert res.is_valid is False
    assert any("Inter-state supply" in e and "cannot have CGST" in e for e in res.errors)


def test_gstr1_intrastate_cannot_have_igst():
    data = {
        "gstin": "27AAAAA0000A1Z2",  # Maharashtra
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-002",
                "idt": "16-04-2026",
                "pos": "27",  # Maharashtra (Intra-state)
                "items": [
                    {
                        "txval": 50000.0,
                        "rt": 18.0,
                        "iamt": 9000.0,  # Invalid: Intra-state cannot have IGST
                        "camt": 0.0,
                        "samt": 0.0
                    }
                ]
            }
        ]
    }
    res = validate_gstr1_input(data)
    assert res.is_valid is False
    assert any("Intra-state supply" in e and "cannot have IGST" in e for e in res.errors)


def test_gstr1_negative_txval_rejected():
    data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-003",
                "idt": "16-04-2026",
                "pos": "27",
                "items": [
                    {
                        "txval": -5000.0,
                        "rt": 18.0,
                        "camt": 0.0,
                        "samt": 0.0
                    }
                ]
            }
        ]
    }
    res = validate_gstr1_input(data)
    assert res.is_valid is False
    assert any("cannot be negative" in e for e in res.errors)


def test_gstr3b_valid_input():
    data = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "due_date": "20-05-2026",
        "filing_date": "20-05-2026",
        "outward_supplies": {
            "taxable": {
                "txval": 200000.0,
                "iamt": 18000.0,
                "camt": 9000.0,
                "samt": 9000.0,
                "csamt": 0.0
            }
        },
        "itc": {
            "available": {
                "all_other": {
                    "iamt": 12000.0,
                    "camt": 5000.0,
                    "samt": 5000.0
                }
            }
        }
    }
    res = validate_gstr3b_input(data)
    assert res.is_valid is True, f"Errors: {res.errors}"
