"""Pytest suite for Real-World SME Business Scenarios."""

import os
import pytest
from scripts.parse_sales_register import parse_csv_sales
from scripts.parse_purchase_register import parse_csv_purchases
from scripts.gst_engine import compute_gstr1_tables, compute_statutory_interest, compute_statutory_late_fee
from scripts.itc_optimizer import optimize_setoff
from scripts.reconcile_gstr2b import reconcile
from scripts.bridge_gstr1_to_gstr3b import bridge_gstr1_and_2b_to_3b, check_drc_mismatch_risks

from scripts.generate_gstr1_json import generate_portal_gstr1
from scripts.generate_gstr3b_json import generate_portal_gstr3b


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_scenario_a_manufacturing_multirate():
    """Scenario A: Multi-rate manufacturer with Cess and B2CL thresholding."""
    csv_file = os.path.join(FIXTURES_DIR, "erpnext_manufacturing_sales.csv")
    sales_input = parse_csv_sales(csv_file, "27AAAAA0000A1Z2", "042026")

    res = compute_gstr1_tables(sales_input)
    s = res["summary"]

    # Invoices: 3 B2B (INV 1, 2, 3), 1 B2CL > 1L (INV 4: ₹1.5L to POS 29), 1 B2CS (INV 5: ₹30k to POS 27)
    assert len(res["table_4_b2b"]) == 3
    assert len(res["table_5_b2cl"]) == 1
    assert res["table_5_b2cl"][0]["inum"] == "INV/MFG/2026/04"
    assert len(res["table_7_b2cs"]) == 1
    assert res["table_7_b2cs"][0]["pos"] == "27"

    # Cess is strictly tracked
    assert s["total_cess"] == 5000.0


def test_scenario_b_saas_export_lut_rcm():
    """Scenario B: IT SaaS company with Zero-rated exports under LUT and Inward RCM."""
    csv_file = os.path.join(FIXTURES_DIR, "erpnext_saas_export.csv")
    sales_input = parse_csv_sales(csv_file, "27AAAAA0000A1Z2", "042026")

    # Inward RCM liability under Section 9(3) (e.g. AWS / Legal fees)
    rcm_liabilities = {"iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
    # Available Export Accumulated ITC
    available_itc = {"iamt": 200000.0, "camt": 50000.0, "samt": 50000.0, "csamt": 0.0}

    # Domestic outward liability from sales
    comp = compute_gstr1_tables(sales_input)
    outward_liabilities = {
        "iamt": comp["summary"]["total_igst"],
        "camt": comp["summary"]["total_cgst"],
        "samt": comp["summary"]["total_sgst"],
        "csamt": 0.0
    }

    opt = optimize_setoff(
        liabilities=outward_liabilities,
        rcm_liabilities=rcm_liabilities,
        available_itc=available_itc,
        opening_cash={}
    )

    # Invariant: RCM Liability MUST be paid 100% in CASH
    assert opt["rcm_cash_liability"]["total"] == 18000.0
    # Domestic liability offset 100% via export accumulated ITC -> Regular cash payable is 0.0
    assert opt["net_cash_required"]["iamt"] == 18000.0  # ONLY RCM cash
    assert opt["setoff_matrix"]["igst_liability"]["paid_by_cash"] == 0.0
    assert opt["setoff_matrix"]["cgst_liability"]["paid_by_cash"] == 0.0
    assert opt["setoff_matrix"]["sgst_liability"]["paid_by_cash"] == 0.0


def test_scenario_c_retail_b2cl_threshold():
    """Scenario C: Retailer strictly separating B2CS vs B2CL (> ₹1,00,000 threshold)."""
    csv_file = os.path.join(FIXTURES_DIR, "retail_b2cs_b2cl.csv")
    sales_input = parse_csv_sales(csv_file, "27AAAAA0000A1Z2", "042026")

    res = compute_gstr1_tables(sales_input)

    # RET 1 (₹5k, POS 27) -> B2CS
    # RET 2 (₹12k, POS 27) -> B2CS
    # RET 3 (₹80k, POS 29) -> Interstate <= 1L -> B2CS
    # RET 4 (₹1.5L, POS 29) -> Interstate > 1L -> Table 5 B2CL
    # RET 5 (₹1.8L, POS 33) -> Interstate > 1L -> Table 5 B2CL
    assert len(res["table_5_b2cl"]) == 2
    b2cl_inums = {inv["inum"] for inv in res["table_5_b2cl"]}
    assert b2cl_inums == {"RET/2026/004", "RET/2026/005"}


def test_scenario_d_vendor_defaults_and_reversals():
    """Scenario D: Purchase register with Missing 2B (Rule 36(4)), 180-Day unpaid (Rule 37), and 17(5)."""
    pr_csv = os.path.join(FIXTURES_DIR, "purchase_register_with_reversals.csv")
    purchases = parse_csv_purchases(pr_csv)

    # Synthetic GSTR-2B reflecting PUR 01, PUR 03, PUR 04
    g2b_raw = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "data": {
            "docdata": {
                "b2b": [
                    {
                        "ctin": "29AAAAA0000A1ZY",
                        "inv": [{"inum": "PUR/2026/01", "dt": "03-04-2026", "val": 118000.0, "pos": "27", "rev": "N", "itcavl": "Y", "items": [{"txval": 100000.0, "rt": 18.0, "iamt": 18000.0}]}]
                    },
                    {
                        "ctin": "27BBBBB1111B1ZN",
                        "inv": [{"inum": "PUR/2026/03", "dt": "12-04-2026", "val": 224000.0, "pos": "27", "rev": "N", "itcavl": "Y", "items": [{"txval": 200000.0, "rt": 12.0, "camt": 12000.0, "samt": 12000.0}]}]
                    },
                    {
                        "ctin": "27CCCCC2222C1Z8",
                        "inv": [{"inum": "PUR/2026/04", "dt": "15-04-2026", "val": 59000.0, "pos": "27", "rev": "N", "itcavl": "Y", "items": [{"txval": 50000.0, "rt": 18.0, "camt": 4500.0, "samt": 4500.0}]}]
                    }
                ]
            }
        }
    }

    recon = reconcile(purchases, g2b_raw)
    s = recon["summary"]

    assert s["total_books_invoices"] == 6
    assert s["exact_matched_count"] == 2  # PUR 01, PUR 03
    assert s["blocked_17_5_count"] == 1   # PUR 04 (Section 17(5) motor vehicle/catering)
    assert s["in_books_only_count"] == 3  # PUR 02, PUR 05, PUR 06 missing in 2B


def test_scenario_e_belated_filing_interest_and_late_fees():
    """Scenario E: Belated return 45 days late with Section 50 interest on Net Cash and Section 47 caps."""
    # Net cash liability of ₹1,00,000 paid 45 days late (Due 20-05-2026, Filed 04-07-2026)
    intr = compute_statutory_interest(net_cash_liability=100000.0, due_date_str="20-05-2026", filing_date_str="04-07-2026")
    # Expected: 100000 * (0.18 / 365) * 45 = 2219.18
    assert intr["delay_days"] == 45
    assert intr["interest_amount"] == 2219.18

    # Turnover <= 1.5 Cr: ₹50/day capped at ₹2,000
    lf = compute_statutory_late_fee(is_nil_return=False, turnover_slab="upto_1.5cr", due_date_str="20-05-2026", filing_date_str="04-07-2026")
    assert lf["delay_days"] == 45
    assert lf["cgst_late_fee"] == 1000.0
    assert lf["sgst_late_fee"] == 1000.0
    assert lf["total_late_fee"] == 2000.0
