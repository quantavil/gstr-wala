"""Regression tests for audit remediations (Table 6.1 cash separation, blocked HSNs, POS normalization, HSN rt field, Section 16(4) cutoff, statutory dues wiring, value-mismatch ITC hold)."""

import json
import subprocess
import sys

import pytest

from scripts.bridge_gstr1_to_gstr3b import bridge_gstr1_and_2b_to_3b, populate_statutory_dues
from scripts.constants import reload_manifest
from scripts.generate_gstr1_json import GSTR1_PORTAL_VERSION, generate_portal_gstr1
from scripts.generate_gstr3b_json import GSTR3B_PORTAL_VERSION, generate_portal_gstr3b
from scripts.models import GSTR1Invoice
from scripts.reconcile_gstr2b import reconcile
from scripts.utils import round_cur
from scripts.validate_gst_input import validate_gstr1_input


def test_table_6_1_cash_payment_separation():
    """Verify that Table 6.1 paid_cash strictly reflects tax liability paid in cash and does not conflate interest."""
    g3b_input = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {"txval": 100000.0, "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
        },
        "itc": {
            "available": {
                "import_goods": {"iamt": 0.0, "csamt": 0.0},
                "import_services": {"iamt": 0.0, "csamt": 0.0},
                "rcm_inward": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "isd": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "all_other": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            }
        },
        "interest_details": {"iamt": 1000.0}
    }
    portal_g3b = generate_portal_gstr3b(g3b_input)
    tx_entry = portal_g3b["tx_pmt"]["tx_py"][0]

    # Liability is 18,000; paid_itc is 0; paid_cash for TAX must be exactly 18,000, NOT 19,000
    assert tx_entry["iamt"] == 18000.0
    assert tx_entry["paid_itc"]["iamt"] == 0.0
    assert tx_entry["paid_cash"]["iamt"] == 18000.0
    assert tx_entry["tx_pmt_cash"]["iamt"] == 18000.0


def test_blocked_hsn_list_alignment():
    """Verify that HSNs 8704, 9966, 9967 are blocked during reconciliation."""
    purchases = [
        {
            "ctin": "27AAAAA0000A1Z2",
            "inum": "TRUCK-01",
            "idt": "15-04-2026",
            "hsn_sc": "8704",
            "txval": 500000.0,
            "iamt": 90000.0,
            "camt": 0.0,
            "samt": 0.0,
            "csamt": 0.0
        },
        {
            "ctin": "27AAAAA0000A1Z2",
            "inum": "RENT-01",
            "idt": "15-04-2026",
            "hsn_sc": "9966",
            "txval": 20000.0,
            "iamt": 3600.0,
            "camt": 0.0,
            "samt": 0.0,
            "csamt": 0.0
        }
    ]
    g2b = {
        "data": {
            "docdata": {
                "b2b": [
                    {
                        "ctin": "27AAAAA0000A1Z2",
                        "inv": [
                            {
                                "inum": "TRUCK-01",
                                "idt": "15-04-2026",
                                "val": 590000.0,
                                "pos": "27",
                                "itms": [{"num": 1, "itm_det": {"txval": 500000.0, "rt": 18.0, "iamt": 90000.0}}]
                            },
                            {
                                "inum": "RENT-01",
                                "idt": "15-04-2026",
                                "val": 23600.0,
                                "pos": "27",
                                "itms": [{"num": 1, "itm_det": {"txval": 20000.0, "rt": 18.0, "iamt": 3600.0}}]
                            }
                        ]
                    }
                ]
            }
        }
    }
    res = reconcile(purchases, g2b)
    assert res["summary"]["blocked_17_5_count"] == 2
    assert res["gstr3b_table_4_auto_population"]["table_4_b_1_permanent_reversals_17_5"]["total"] == 93600.0


def test_pos_normalization_single_digit():
    """Verify that single-digit POS ('7' for Delhi) is normalized to '07' and accepted."""
    inv = GSTR1Invoice(
        inum="INV-DELHI-1",
        idt="01-04-2026",
        pos="7",
        val=1180.0,
        items=[{"txval": 1000.0, "rt": 18.0, "iamt": 180.0}]
    )
    assert inv.pos == "07"

    val_res = validate_gstr1_input({
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-DELHI-1",
                "idt": "01-04-2026",
                "pos": "7",
                "val": 1180.0,
                "items": [{"txval": 1000.0, "rt": 18.0, "iamt": 180.0}]
            }
        ]
    })
    assert val_res.is_valid


def test_gstr1_table_12_hsn_rt_emission():
    """Verify that Table 12 HSN summary in GSTR-1 offline JSON includes the rt field."""
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-01",
                "idt": "10-04-2026",
                "pos": "27",
                "ctin": "27BBBBB0000B1Z1",
                "items": [{"txval": 1000.0, "rt": 18.0, "camt": 90.0, "samt": 90.0, "hsn_sc": "8471", "desc": "Laptops"}]
            }
        ]
    }
    portal_g1 = generate_portal_gstr1(g1_data)
    hsn_rows = portal_g1["hsn"]["data"]
    assert len(hsn_rows) >= 1
    assert "rt" in hsn_rows[0]
    assert hsn_rows[0]["rt"] == 18.0


def test_bridge_cli_positional_with_preexisting_out_file(tmp_path):
    """Verify that bridge CLI correctly identifies output path when output file already exists."""
    g1_path = tmp_path / "gstr1.json"
    out_path = tmp_path / "custom_output.json"

    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": []
    }
    g1_path.write_text(json.dumps(g1_data), encoding="utf-8")
    out_path.write_text("{}", encoding="utf-8")  # Pre-existing file

    cmd = [sys.executable, "scripts/bridge_gstr1_to_gstr3b.py", str(g1_path), str(out_path)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0
    assert "SUCCESS" in res.stdout

    out_data = json.loads(out_path.read_text(encoding="utf-8"))
    assert out_data["gstin"] == "27AAAAA0000A1Z2"


def test_manifest_reload_dynamic():
    """Verify reload_manifest refreshes global constants from the manifest on disk."""
    from scripts import constants

    original_path = constants._MANIFEST_PATH
    tmp_manifest = original_path + ".reload_test"
    try:
        modified = json.loads(open(original_path, encoding="utf-8").read())
        modified["statutory_rules"]["b2cl_threshold"]["value"] = 250000.0
        with open(tmp_manifest, "w", encoding="utf-8") as f:
            json.dump(modified, f)

        constants._MANIFEST_PATH = tmp_manifest
        reload_manifest()
        assert constants.B2CL_THRESHOLD == 250000.0
    finally:
        import os

        constants._MANIFEST_PATH = original_path
        reload_manifest()
        if os.path.exists(tmp_manifest):
            os.unlink(tmp_manifest)
    assert constants.B2CL_THRESHOLD == 100000.0


def test_statutory_dues_wired_on_late_filing():
    """Bridge must auto-populate Sec 50 interest and Sec 47 late fee when filing is delayed.

    Scenario: liability ₹18,000 (no ITC), due 20-05-2026, filed 04-07-2026 (45 days).
      - Sec 50(1) interest = round_half_up(18000 * 0.18/365 * 45) = ₹399.45
      - Sec 47 late fee    = min(cap ₹1,000/head, 45 x ₹25) = ₹1,000 CGST + ₹1,000 SGST
      - PMT-06 challan     = 18,000 + 399.45 + 2,000 = ₹20,399.45
      - Table 6.1 paid_cash stays tax-only (₹18,000).
    """
    from scripts.constants import get_interest_rate_50_1
    from scripts.itc_optimizer import optimize_from_input_dict

    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {"inum": "I1", "idt": "05-04-2026", "pos": "30", "items": [{"txval": 100000.0, "rt": 18.0, "iamt": 18000.0}]}
        ],
    }
    g3b = bridge_gstr1_and_2b_to_3b(g1_data, None, due_date="20-05-2026", filing_date="04-07-2026")

    # Expected values derived from the live manifest rate (compliance patches may change it).
    rate = get_interest_rate_50_1()
    expected_interest = round_cur(18000.0 * (rate / 365.0) * 45)
    assert g3b["interest_details"]["interest_amount"] == pytest.approx(expected_interest)
    assert g3b["late_fee_details"] == {"camt": 1000.0, "samt": 1000.0}

    tx_entry = generate_portal_gstr3b(g3b)["tx_pmt"]["tx_py"][0]
    assert tx_entry["paid_cash"]["iamt"] == 18000.0  # tax-only cash in Table 6.1

    opt = optimize_from_input_dict(g3b)
    assert opt["challan_pmt06"]["total_challan_amount"] == pytest.approx(18000.0 + expected_interest + 2000.0)


def test_user_provided_statutory_dues_not_overwritten():
    """User-supplied interest_details / late_fee_details must survive the bridge untouched."""
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {"inum": "I1", "idt": "05-04-2026", "pos": "30", "items": [{"txval": 100000.0, "rt": 18.0, "iamt": 18000.0}]}
        ],
    }
    g3b_manual = bridge_gstr1_and_2b_to_3b(
        g1_data,
        None,
        due_date="20-05-2026",
        filing_date="04-07-2026",
    )
    # Simulate user-provided values arriving before population runs.
    g3b_manual["interest_details"] = {"iamt": 500.0}
    g3b_manual["late_fee_details"] = {"camt": 10.0, "samt": 10.0}
    populated = populate_statutory_dues(g3b_manual)

    assert populated["interest_details"] == {"iamt": 500.0}
    assert populated["late_fee_details"] == {"camt": 10.0, "samt": 10.0}


def test_value_mismatch_itc_held_not_auto_claimed():
    """Value mismatches must NOT flow into Table 4(A)(5); they are held for review."""
    ctin = "27AAAAA0000A1Z2"
    pr = [{"ctin": ctin, "inum": "B-1", "idt": "01-04-2026", "txval": 10000.0, "iamt": 1800.0}]
    g2b = {
        "fp": "042026",
        "data": {
            "docdata": {
                "b2b": [
                    {
                        "ctin": ctin,
                        "inv": [
                            {
                                "inum": "B-1",
                                "dt": "01-04-2026",
                                "itms": [{"itm_det": {"txval": 9000.0, "iamt": 1620.0}}]
                            }
                        ]
                    }
                ]
            }
        },
    }
    res = reconcile(pr, g2b)
    t4 = res["gstr3b_table_4_auto_population"]

    assert res["summary"]["value_mismatch_count"] == 1
    assert t4["table_4_a_5_all_other_itc"]["iamt"] == 0.0          # nothing auto-claimed
    assert t4["table_4_a_5_value_mismatch_hold"]["iamt"] == 1620.0  # held at min(books, 2B)
    assert t4["table_4_c_net_itc"]["iamt"] == 0.0                   # 4(C) excludes held ITC
    assert res["summary"]["value_mismatch_itc_held_total"] == 1620.0


def test_section_16_4_cutoff_from_docdata_fp_is_deterministic():
    """fp nested inside docdata must drive the 16(4) evaluation date — no wall-clock fallback."""
    ctin = "27AAAAA0000A1Z2"

    def _g2b(idt: str) -> dict:
        return {
            "data": {
                "docdata": {
                    "fp": "042026",
                    "b2b": [
                        {"ctin": ctin, "inv": [
                            {"inum": "OLD-1" if idt.startswith("01-05-2023") else "NEW-1", "dt": idt,
                             "itms": [{"itm_det": {"txval": 5000.0, "iamt": 900.0}}]}
                        ]}
                    ],
                }
            }
        }

    pr_old = [{"ctin": ctin, "inum": "OLD-1", "idt": "01-05-2023", "txval": 5000.0, "iamt": 900.0}]
    pr_new = [{"ctin": ctin, "inum": "NEW-1", "idt": "01-05-2026", "txval": 5000.0, "iamt": 900.0}]

    # Derived from docdata.fp (20-05-2026): May-2023 invoice expired, May-2026 invoice fine.
    res_old = reconcile(pr_old, _g2b("01-05-2023"))
    res_new = reconcile(pr_new, _g2b("01-05-2026"))
    assert res_old["summary"]["ineligible_2b_count"] == 1
    assert res_new["summary"]["ineligible_2b_count"] == 0

    # Explicit cutoff must reproduce the derived result exactly (determinism).
    res_explicit = reconcile(pr_old, _g2b("01-05-2023"), _16_4_cutoff="20-05-2026")
    assert res_explicit["summary"] == res_old["summary"]


def test_derive_taxes_use_statutory_half_up_rounding():
    """derive_taxes and invoice val must use Decimal HALF_UP (round_cur), not banker's round()."""
    from scripts.parse_sales_register import parse_rows_sales

    rows_inter = [
        {"invoice_number": "X1", "invoice_date": "05-04-2026", "pos": "30", "taxable_value": "0.25", "gst_rate": "18"}
    ]
    out_inter = parse_rows_sales(rows_inter, "27AAAAA0000A1Z2", "042026", derive_taxes=True)
    item = out_inter["invoices"][0]["items"][0]
    assert item["iamt"] == 0.05  # HALF_UP of 0.045; banker's round() would give 0.04 on some values
    assert out_inter["invoices"][0]["val"] == 0.30

    rows_intra = [
        {"invoice_number": "X2", "invoice_date": "05-04-2026", "taxable_value": "0.25", "gst_rate": "18"}
    ]
    out_intra = parse_rows_sales(rows_intra, "27AAAAA0000A1Z2", "042026", derive_taxes=True)
    item_intra = out_intra["invoices"][0]["items"][0]
    assert item_intra["camt"] == 0.02 and item_intra["samt"] == 0.02


def test_portal_version_markers_are_overridable():
    """Version tags are gstr-wala provenance markers and can be overridden per upload requirements."""
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {"inum": "I1", "idt": "05-04-2026", "pos": "27", "items": [{"txval": 1000.0, "rt": 18.0, "iamt": 180.0}]}
        ],
    }
    default_json = generate_portal_gstr1(g1_data)
    assert default_json["version"] == GSTR1_PORTAL_VERSION

    custom = generate_portal_gstr1(g1_data, portal_version="CUSTOM-TOKEN")
    assert custom["version"] == "CUSTOM-TOKEN"

    g3b_default = generate_portal_gstr3b({"gstin": "27AAAAA0000A1Z2", "ret_period": "042026"})
    assert g3b_default["version"] == GSTR3B_PORTAL_VERSION
