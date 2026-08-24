"""Pytest test suite for GSTR-1 & GSTR-3B JSON generators and Bridge."""

from scripts.bridge_gstr1_to_gstr3b import (
    bridge_gstr1_and_2b_to_3b,
    check_drc_mismatch_risks,
)
from scripts.generate_gstr1_json import generate_portal_gstr1
from scripts.generate_gstr3b_json import generate_portal_gstr3b


def test_generate_gstr1_portal_schema():
    data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "gt": 10000000.0,
        "cur_gt": 2500000.0,
        "invoices": [
            {
                "inum": "INV-001",
                "idt": "10-04-2026",
                "pos": "29",
                "ctin": "29BBBBB1111B1Z2",
                "val": 118000.0,
                "items": [{"txval": 100000.0, "rt": 18.0, "iamt": 18000.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 10}]
            },
            {
                "inum": "INV-002",
                "idt": "12-04-2026",
                "pos": "29",
                "val": 177000.0,
                "items": [{"txval": 150000.0, "rt": 18.0, "iamt": 27000.0, "hsn_sc": "8471", "uqc": "NOS", "qty": 15}]
            }
        ]
    }

    portal_json = generate_portal_gstr1(data)
    assert portal_json["gstin"] == "27AAAAA0000A1Z2"
    assert portal_json["fp"] == "042026"
    assert len(portal_json["b2b"]) == 1
    assert len(portal_json["b2cl"]) == 1
    assert len(portal_json["hsn"]["data"]) == 2


def test_generate_gstr3b_portal_schema():
    data = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {
                "txval": 250000.0,
                "iamt": 45000.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0
            }
        },
        "itc": {
            "available": {
                "all_other": {
                    "iamt": 30000.0,
                    "camt": 0.0,
                    "samt": 0.0,
                    "csamt": 0.0
                }
            }
        }
    }

    portal_json = generate_portal_gstr3b(data)
    assert portal_json["gstin"] == "27AAAAA0000A1Z2"
    assert portal_json["ret_period"] == "042026"
    assert portal_json["sup_details"]["osup_det"]["txval"] == 250000.0
    assert portal_json["sup_details"]["osup_det"]["iamt"] == 45000.0
    # ITC offset 30,000 against 45,000 -> 15,000 paid in cash
    assert portal_json["tx_pmt"]["tx_py"][0]["paid_itc"]["iamt"] == 30000.0
    assert portal_json["tx_pmt"]["tx_py"][0]["paid_cash"]["iamt"] == 15000.0


def test_bridge_and_drc_checks():
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-001",
                "idt": "10-04-2026",
                "pos": "27",
                "items": [{"txval": 100000.0, "rt": 18.0, "camt": 9000.0, "samt": 9000.0}]
            }
        ]
    }

    recon_data = {
        "gstr3b_table_4_auto_population": {
            "table_4_a_5_all_other_itc": {"iamt": 5000.0, "camt": 2000.0, "samt": 2000.0, "csamt": 0.0},
            "table_4_b_1_permanent_reversals_17_5": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "table_4_b_2_temporary_reversals_rule37": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "table_4_d_2_ineligible_16_4": {"iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
        }
    }

    g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_data)
    assert g3b_input["outward_supplies"]["taxable"]["camt"] == 9000.0
    assert g3b_input["outward_supplies"]["taxable"]["samt"] == 9000.0
    assert g3b_input["itc"]["available"]["all_other"]["iamt"] == 5000.0

    drc_res = check_drc_mismatch_risks(
        gstr1_summary={"total_tax": 18000.0},
        gstr3b_data=g3b_input,
        gstr2b_total_itc=9000.0
    )
    assert drc_res["drc_01b_liability_mismatch"]["risk_flag"] is False
    assert drc_res["drc_01c_itc_mismatch"]["risk_flag"] is False


def test_gstr3b_canonical_contract_roundtrip_all_schedules():
    """F3 Contract Test: Asserts that all canonical GSTR-3B fields survive portal JSON serialization."""
    canonical_data = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {"txval": 500000.0, "iamt": 90000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "zero_rated": {"txval": 100000.0, "iamt": 18000.0, "csamt": 0.0},
            "nil_exempt": {"txval": 20000.0},
            "rcm_inward": {"txval": 30000.0, "iamt": 5400.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "non_gst": {"txval": 10000.0}
        },
        "eco_supplies": {
            "eco_pays_tax": {"txval": 40000.0, "iamt": 7200.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "registered_through_eco": {"txval": 25000.0}
        },
        "inter_state_supplies": [
            {"pos": "29", "supply_type": "unregistered", "txval": 50000.0, "iamt": 9000.0},
            {"pos": "29", "supply_type": "composition", "txval": 30000.0, "iamt": 5400.0},
            {"pos": "29", "supply_type": "uin", "txval": 20000.0, "iamt": 3600.0}
        ],
        "itc": {
            "available": {
                "import_goods": {"iamt": 12000.0, "csamt": 0.0},
                "import_services": {"iamt": 6000.0, "csamt": 0.0},
                "rcm_inward": {"iamt": 5400.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "isd": {"iamt": 4000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "all_other": {"iamt": 45000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            },
            "reversed": {
                "permanent_17_5_rules": {"iamt": 3000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "temporary_others": {"iamt": 2000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            },
            "other_details": {
                "reclaimed": {"iamt": 1500.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "ineligible_16_4_pos": {"iamt": 2500.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
            }
        },
        "inward_exempt_nil_non_gst": {
            "from_composition_exempt": {"inter": 8000.0, "intra": 12000.0},
            "non_gst": {"inter": 4000.0, "intra": 6000.0}
        }
    }

    portal_json = generate_portal_gstr3b(canonical_data)

    # 1. Assert Table 3.1.1 ECO survived
    assert portal_json["eco_dtls"]["eco_m_sup"]["txval"] == 40000.0
    assert portal_json["eco_dtls"]["eco_m_sup"]["iamt"] == 7200.0
    assert portal_json["eco_dtls"]["eco_sup"]["txval"] == 25000.0

    # 2. Assert Table 3.2 UIN details survived
    assert len(portal_json["inter_sup"]["uin_details"]) == 1
    assert portal_json["inter_sup"]["uin_details"][0]["txval"] == 20000.0
    assert portal_json["inter_sup"]["uin_details"][0]["iamt"] == 3600.0

    # 3. Assert Table 4(D) Ineligible & Reclaimed ITC survived
    assert portal_json["itc_elg"]["itc_inelg"][0]["iamt"] == 1500.0  # 4(D)(1)
    assert portal_json["itc_elg"]["itc_inelg"][1]["iamt"] == 2500.0  # 4(D)(2)

    # 4. Assert Table 5 Inward Exempt survived
    assert portal_json["inward_sup"]["isup_details"][0]["inter"] == 8000.0
    assert portal_json["inward_sup"]["isup_details"][0]["intra"] == 12000.0
    assert portal_json["inward_sup"]["isup_details"][1]["inter"] == 4000.0
    assert portal_json["inward_sup"]["isup_details"][1]["intra"] == 6000.0


def test_gstr1_table_8_nested_structure():
    """Asserts that GSTR-1 Table 8 is properly nested into official GSTN schema."""
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [],
        "nil_exempt_non_gst": {
            "nil_inter_reg": 1000.0,
            "nil_inter_unreg": 2000.0,
            "nil_intra_reg": 3000.0,
            "nil_intra_unreg": 4000.0,
            "expt_inter_reg": 5000.0,
            "expt_inter_unreg": 6000.0,
            "expt_intra_reg": 7000.0,
            "expt_intra_unreg": 8000.0,
            "ngsup_inter_reg": 9000.0,
            "ngsup_inter_unreg": 10000.0,
            "ngsup_intra_reg": 11000.0,
            "ngsup_intra_unreg": 12000.0
        }
    }

    portal_g1 = generate_portal_gstr1(g1_data)
    exemp = portal_g1["exemp"]
    assert "nil_supplies" in exemp
    assert "exptd_supplies" in exemp
    assert "ngsupplies" in exemp
    assert exemp["nil_supplies"]["inter_reg"] == 1000.0
    assert exemp["exptd_supplies"]["intra_unreg"] == 8000.0
    assert exemp["ngsupplies"]["intra_reg"] == 11000.0


def test_pdf_escapes_html_in_gstin(tmp_path):
    from scripts.generate_pdf_statement import generate_pdf
    data = {"gstin":"<script>alert(1)</script>","ret_period":"042026","due_date":"20-05-2026","filing_date":"20-05-2026","outward_supplies":{"taxable":{"txval":0.0,"iamt":0.0,"camt":0.0,"samt":0.0,"csamt":0.0},"zero_rated":{},"rcm_inward":{}},"itc":{"available":{"all_other":{}},"reversed":{"permanent_17_5_rules":{}}},"opening_credit_ledger":{},"opening_cash_ledger":{}}
    out=str(tmp_path/"s.pdf")
    generate_pdf(data, out)
    html=(tmp_path/"s.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
