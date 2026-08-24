"""Pytest suite for Pydantic v2 models and unified CLI / Filing pack generator."""

import os
import pytest
from scripts.models import GSTR1Input, GSTR3BInput
from scripts.generate_filing_pack import generate_gstr1_filing_pack, generate_gstr3b_filing_pack


def test_pydantic_gstr1_model():
    valid_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-01",
                "idt": "10-04-2026",
                "pos": "27",
                "items": [{"txval": 1000.0, "rt": 18.0, "camt": 90.0, "samt": 90.0}]
            }
        ]
    }
    model = GSTR1Input(**valid_data)
    assert model.gstin == "27AAAAA0000A1Z2"
    assert model.fp == "042026"
    assert len(model.invoices) == 1
    assert model.invoices[0].items[0].txval == 1000.0


def test_pydantic_invalid_gstin_raises():
    invalid_data = {
        "gstin": "INVALID_GSTIN_123",
        "fp": "042026",
        "invoices": []
    }
    with pytest.raises(Exception):
        GSTR1Input(**invalid_data)


def test_generate_filing_pack_markdown(tmp_path):
    g1_data = {
        "gstin": "27AAAAA0000A1Z2",
        "fp": "042026",
        "invoices": [
            {
                "inum": "INV-01",
                "idt": "10-04-2026",
                "pos": "27",
                "items": [{"txval": 1000.0, "rt": 18.0, "camt": 90.0, "samt": 90.0}]
            }
        ]
    }
    g3b_data = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {"txval": 1000.0, "camt": 90.0, "samt": 90.0}
        }
    }
    out_g1 = str(tmp_path / "gstr1.md")
    out_g3b = str(tmp_path / "gstr3b.md")

    generate_gstr1_filing_pack(g1_data, out_g1)
    generate_gstr3b_filing_pack(g3b_data, out_g3b)

    assert os.path.exists(out_g1)
    assert os.path.exists(out_g3b)
    with open(out_g1, "r") as f:
        content = f.read()
        assert "GSTR-1 Filing Pack" in content


def test_parse_csv_sales_and_purchases():
    """Verify that sample CSV sales and purchase registers parse accurately."""
    from scripts.parse_sales_register import parse_csv_sales
    from scripts.parse_purchase_register import parse_csv_purchases

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sales_csv = os.path.join(repo_root, "examples", "sample_sales_register.csv")
    purch_csv = os.path.join(repo_root, "examples", "sample_purchase_register.csv")

    sales_result = parse_csv_sales(sales_csv, "27AAAAA0000A1Z2", "042026")
    assert sales_result["gstin"] == "27AAAAA0000A1Z2"
    assert len(sales_result["invoices"]) == 4

    purch_result = parse_csv_purchases(purch_csv)
    assert len(purch_result) == 3
    assert purch_result[0]["inum"] == "PUR-001"
