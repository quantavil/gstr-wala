"""Tests for scripts/generate_sales_register.py and sales-register CLI command."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from python_calamine import CalamineWorkbook
from typer.testing import CliRunner

from scripts.cli import app
from scripts.generate_sales_register import (
    build_sales_register_excel,
    clean_num,
    extract_invoices_from_pdf_dir,
)

runner = CliRunner()


def test_clean_num_truthfulness() -> None:
    """Tests monetary and numeric string cleaning."""
    assert clean_num("₹ 1,23,456.78") == 123456.78
    assert clean_num("$3,750.00") == 3750.0
    assert clean_num("(1,000.50)") == 0.0  # bad or invalid chars fallback
    assert clean_num("-") == 0.0
    assert clean_num("--") == 0.0
    assert clean_num(None) == 0.0
    assert clean_num(4500.25) == 4500.25
    assert clean_num("0.00") == 0.0


def test_build_sales_register_excel_structure(tmp_path: Path) -> None:
    """Verifies that the generated Excel workbook contains all 4 sheets, formulas, and data."""
    taxpayer_info: dict[str, Any] = {
        "trade_name": "Test Logistics Pvt Ltd",
        "gstin": "09ABCDE1234F1Z5",
        "fp": "082026",
        "state_code": "09",
        "state_name": "Uttar Pradesh",
    }

    mock_invoices = [
        {
            "inum": "101",
            "idt": "05/08/2026",
            "buyer": "Alpha Traders",
            "ctin": "09XYZAB5678C1ZD",
            "pos": "09",
            "pos_state": "Uttar Pradesh",
            "supply_type": "Intra-State (CGST+SGST)",
            "is_igst": False,
            "rchrg": "N",
            "inv_typ": "R",
            "taxable": 10000.0,
            "cgst": 900.0,
            "sgst": 900.0,
            "igst": 0.0,
            "total_tax": 1800.0,
            "round_off": 0.0,
            "doc_total": 11800.0,
            "items": [
                {
                    "sl": "1",
                    "desc": "Freight Handling",
                    "hsn": "996511",
                    "qty": 1.0,
                    "uqc": "NOS",
                    "currency": "INR",
                    "rate": 10000.0,
                    "taxable": 10000.0,
                    "tax_rate": 18.0,
                    "cgst_pct": 9.0,
                    "cgst": 900.0,
                    "sgst_pct": 9.0,
                    "sgst": 900.0,
                    "igst_pct": 0.0,
                    "igst": 0.0,
                    "total_tax": 1800.0,
                }
            ],
        },
        {
            "inum": "102",
            "idt": "10/08/2026",
            "buyer": "Beta Global Exports",
            "ctin": "07DEFGH9999K1Z1",
            "pos": "07",
            "pos_state": "Delhi",
            "supply_type": "Inter-State (IGST)",
            "is_igst": True,
            "rchrg": "N",
            "inv_typ": "R",
            "taxable": 20000.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "igst": 3600.0,
            "total_tax": 3600.0,
            "round_off": 0.0,
            "doc_total": 23600.0,
            "items": [
                {
                    "sl": "1",
                    "desc": "Customs Clearance",
                    "hsn": "996712",
                    "qty": 2.0,
                    "uqc": "SB",
                    "currency": "INR",
                    "rate": 10000.0,
                    "taxable": 20000.0,
                    "tax_rate": 18.0,
                    "cgst_pct": 0.0,
                    "cgst": 0.0,
                    "sgst_pct": 0.0,
                    "sgst": 0.0,
                    "igst_pct": 18.0,
                    "igst": 3600.0,
                    "total_tax": 3600.0,
                }
            ],
        },
    ]

    out_xlsx = tmp_path / "test_sales_register.xlsx"
    res_path = build_sales_register_excel(taxpayer_info, mock_invoices, out_xlsx)
    assert os.path.exists(res_path)

    # Validate workbook with Calamine
    wb = CalamineWorkbook.from_path(str(out_xlsx))
    assert wb.sheet_names == [
        "Executive Dashboard",
        "Sales Register",
        "Itemized Details",
        "HSN-SAC Summary",
    ]

    # Verify Sales Register sheet
    inv_rows = wb.get_sheet_by_name("Sales Register").to_python()
    assert len(inv_rows) == 5  # Title, Header, Inv 101, Inv 102, Total
    assert inv_rows[2][1] == "101"
    assert inv_rows[2][3] == "Alpha Traders"
    assert inv_rows[2][9] == 10000.0

    assert inv_rows[3][1] == "102"
    assert inv_rows[3][3] == "Beta Global Exports"
    assert inv_rows[3][9] == 20000.0

    # Verify Itemized Details sheet
    item_rows = wb.get_sheet_by_name("Itemized Details").to_python()
    assert len(item_rows) == 5  # Title, Header, Item 1, Item 2, Total
    assert item_rows[2][5] == "Freight Handling"
    assert item_rows[3][5] == "Customs Clearance"

    # Verify HSN sheet
    hsn_rows = wb.get_sheet_by_name("HSN-SAC Summary").to_python()
    assert len(hsn_rows) == 5  # Title, Header, 996511, 996712, Total


def test_extract_invoices_from_pdf_dir_invalid_path() -> None:
    """Rejects directories with no PDF invoices."""
    with pytest.raises(ValueError, match="No PDF invoices found"):
        extract_invoices_from_pdf_dir("/tmp/non_existent_folder_xyz123")


def test_cli_sales_register_command(tmp_path: Path) -> None:
    """Verifies that cli sales-register command runs cleanly."""
    invoices_dir = Path("/home/quantavil/Documents/Invoices/2026-08/invoices")
    if not invoices_dir.exists():
        pytest.skip("Invoices test directory not found")

    out_xlsx = tmp_path / "cli_sales_register.xlsx"
    result = runner.invoke(
        app,
        [
            "sales-register",
            str(invoices_dir),
            "--output",
            str(out_xlsx),
        ],
    )
    assert result.exit_code == 0
    assert "Generated 4-sheet Sales Register workbook" in result.stdout
    assert out_xlsx.exists()


def test_cli_sales_register_with_export_gstr1(tmp_path: Path) -> None:
    """Verifies that sales-register with --export-gstr1 generates clean uploadable JSON without intermediate bloat."""
    invoices_dir = Path("/home/quantavil/Documents/Invoices/2026-08/invoices")
    if not invoices_dir.exists():
        pytest.skip("Invoices test directory not found")

    out_xlsx = tmp_path / "cli_sales_register.xlsx"
    out_g1 = tmp_path / "gstr1_portal.json"
    result = runner.invoke(
        app,
        [
            "sales-register",
            str(invoices_dir),
            "--output",
            str(out_xlsx),
            "--export-gstr1",
            str(out_g1),
        ],
    )
    assert result.exit_code == 0
    assert out_xlsx.exists()
    assert out_g1.exists()
    g1_data = json.loads(out_g1.read_text())
    assert g1_data["version"] == "GST3.2.4"
    assert "b2b" in g1_data
    assert "b2cl" not in g1_data

