"""Pytest suite verifying all Typer CLI commands via CliRunner."""

import os
import pytest
from typer.testing import CliRunner
from scripts.cli import app

runner = CliRunner()
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_cli_validate_command():
    result = runner.invoke(app, ["validate", os.path.join(FIXTURES_DIR, "official_gstn_gstr1.json")])
    assert result.exit_code == 0
    assert "Validation PASSED" in result.stdout


def test_cli_reconcile_command():
    pr_file = os.path.join(REPO_ROOT, "examples", "sample_purchase_register.json")
    g2b_file = os.path.join(REPO_ROOT, "examples", "sample_gstr2b.json")
    result = runner.invoke(app, ["reconcile-cmd", pr_file, g2b_file, "--fast"])
    assert result.exit_code == 0
    assert "polars+rapidfuzz" in result.stdout


def test_cli_pdf_to_images_command(tmp_path):
    # Create a test PDF first
    pytest.importorskip("weasyprint")
    from scripts.generate_pdf_statement import generate_pdf
    pdf_dir = tmp_path / "pdf_in"
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = str(pdf_dir / "statement.pdf")
    sample_g3b = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {"taxable": {"txval": 10000.0, "iamt": 1800.0}}
    }
    generate_pdf(sample_g3b, pdf_path)

    out_dir = str(tmp_path / "img_out")
    result = runner.invoke(app, ["ingest-pdf", str(pdf_dir), "--output-dir", out_dir, "--dpi", "150", "--force-image"])
    assert result.exit_code == 0
    assert os.path.exists(os.path.join(out_dir, "image_manifest.json"))


def test_cli_pipeline_command(tmp_path):
    sales = os.path.join(REPO_ROOT, "examples", "sample_sales_register.json")
    purchases = os.path.join(REPO_ROOT, "examples", "sample_purchase_register.json")
    gstr2b = os.path.join(REPO_ROOT, "examples", "sample_gstr2b.json")
    out_dir = str(tmp_path / "pipe_out")

    result = runner.invoke(app, [
        "pipeline",
        "--sales", sales,
        "--purchases", purchases,
        "--gstr2b", gstr2b,
        "--output-dir", out_dir
    ])
    assert result.exit_code == 0
    assert os.path.exists(os.path.join(out_dir, "gstr1_portal.json"))
    assert os.path.exists(os.path.join(out_dir, "gstr3b_portal.json"))
    assert os.path.exists(os.path.join(out_dir, "gstr1_filing_pack.md"))
    assert os.path.exists(os.path.join(out_dir, "gstr3b_filing_pack.md"))
    assert os.path.exists(os.path.join(out_dir, "reconciliation_report.md"))

