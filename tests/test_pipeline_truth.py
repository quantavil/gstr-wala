import json
import os
import sys
import urllib.request

import pytest
from typer.testing import CliRunner

from scripts.bridge_gstr1_to_gstr3b import (
    check_drc_mismatch_risks,
)
from scripts.cli import app
from scripts.compliance_radar import (
    _validate_numeric_map,
    apply_compliance_patch,
    load_rules_manifest,
    save_rules_manifest,
)
from scripts.constants import get_interest_rate_50_1
from scripts.discover_statutory_rules import fetch_portal_advisories
from scripts.generate_filing_pack import (
    generate_gstr1_filing_pack,
    generate_gstr3b_filing_pack,
    generate_reconciliation_report,
    validate_against_schema,
)
from scripts.generate_gstr1_json import generate_portal_gstr1
from scripts.generate_gstr3b_json import generate_portal_gstr3b
from scripts.generate_pdf_statement import generate_pdf
from scripts.gst_engine import compute_statutory_interest

pytestmark = pytest.mark.skipif(
    os.environ.get("GSTR_WALA_SELF_VERIFY") == "1",
    reason="Radar self-verification running in child process",
)

runner = CliRunner()
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
G1_SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas", "gstr1_portal_schema.json")
G3B_SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas", "gstr3b_portal_schema.json")


class TestSchemaEnforcement:
    def test_gstr1_portal_json_validates_cleanly(self):
        sales_path = os.path.join(REPO_ROOT, "examples", "sample_sales_register.json")
        with open(sales_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        portal_payload = generate_portal_gstr1(data)
        assert portal_payload.get("version") == "gstr-wala-gstr1-1.0"
        errs = validate_against_schema(portal_payload, G1_SCHEMA_PATH)
        assert errs == [], f"GSTR-1 schema errors: {errs}"

    def test_gstr3b_portal_json_validates_cleanly(self):
        g3b_path = os.path.join(REPO_ROOT, "examples", "sample_gstr3b_portal.json")
        with open(g3b_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Generate canonical 3B and portal JSON
        portal_payload = generate_portal_gstr3b(data)
        assert portal_payload.get("version") == "gstr-wala-gstr3b-1.0"
        errs = validate_against_schema(portal_payload, G3B_SCHEMA_PATH)
        assert errs == [], f"GSTR-3B schema errors: {errs}"

    def test_gstr3b_schema_allows_import_goods_services_without_cgst_sgst(self):
        payload = {
            "version": "gstr-wala-gstr3b-1.0",
            "gstin": "27AAAAA0000A1Z2",
            "ret_period": "042026",
            "sup_details": {
                "osup_det": {"txval": 1000.0, "iamt": 180.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "osup_zero": {"txval": 0.0, "iamt": 0.0, "csamt": 0.0},
                "osup_nil_exmp": {"txval": 0.0},
                "isup_rev": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "osup_nongst": {"txval": 0.0},
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "iamt": 5000.0, "csamt": 0.0},
                    {"ty": "IMPS", "iamt": 3000.0, "csamt": 0.0},
                ],
                "itc_rev": [{"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}],
                "itc_net": {"iamt": 8000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "itc_inelg": [{"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}],
            },
            "inward_sup": {"isup_details": []},
            "tx_pmt": {"tx_py": []},
        }
        errs = validate_against_schema(payload, G3B_SCHEMA_PATH)
        assert errs == [], f"IMPG/IMPS rows without camt/samt must be valid: {errs}"

    def test_validate_against_schema_returns_descriptive_errors_without_throw(self):
        bad_payload = {"invalid_field": 123}
        errs = validate_against_schema(bad_payload, G1_SCHEMA_PATH)
        assert len(errs) > 0
        assert any("gstin" in e for e in errs)
        assert any("fp" in e for e in errs)
        assert any("version" in e for e in errs)


class TestPdfHonesty:
    def test_missing_dates_render_em_dash_not_fabricated_fallback(self, tmp_path):
        payload = {
            "gstin": "27AAAAA0000A1Z2",
            "ret_period": "042026",
            "outward_supplies": {"taxable": {"txval": 10000.0, "iamt": 1800.0}},
        }
        out_pdf = str(tmp_path / "test_statement.pdf")
        generate_pdf(payload, out_pdf)
        html_file = out_pdf.replace(".pdf", ".html")
        assert os.path.exists(html_file)
        with open(html_file, "r", encoding="utf-8") as f:
            html = f.read()
        assert "20-05-2026" not in html
        assert "—" in html

    def test_bare_filename_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = {
            "gstin": "27AAAAA0000A1Z2",
            "ret_period": "042026",
            "outward_supplies": {"taxable": {"txval": 1000.0, "iamt": 180.0}},
        }
        # bare filename without directory component
        generate_pdf(payload, "bare_output.pdf")
        assert os.path.exists("bare_output.html")


class TestBridgeAndDrcChecks:
    def test_bridge_main_argparse(self, tmp_path):
        g1_path = os.path.join(REPO_ROOT, "examples", "sample_sales_register.json")
        out_3b = str(tmp_path / "bridged_3b.json")
        # Run bridge via python command line using argparse positional arguments
        cmd = [sys.executable, "scripts/bridge_gstr1_to_gstr3b.py", g1_path, out_3b]
        import subprocess
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        assert res.returncode == 0
        assert os.path.exists(out_3b)
        assert "SUCCESS: Auto-populated GSTR-3B input" in res.stdout
        assert "Total ITC: ₹" in res.stdout
        assert "{'iamt'" not in res.stdout

    def test_drc_01c_denominator_sums_all_2b_categories(self):
        # 2B with large import goods and RCM inward, small all_other
        recon_data = {
            "gstr3b_table_4_auto_population": {
                "table_4_a_1_import_goods": {"total": 500000.0, "iamt": 500000.0, "csamt": 0.0},
                "table_4_a_3_rcm_inward": {"total": 50000.0, "iamt": 50000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "table_4_a_4_isd": {"total": 20000.0, "iamt": 20000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                "table_4_a_5_all_other_itc": {"total": 30000.0, "iamt": 30000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            }
        }
        t4_pop = recon_data["gstr3b_table_4_auto_population"]
        tot_2b = sum(t4_pop[k]["total"] for k in t4_pop)
        assert tot_2b == 600000.0

        g3b_data = {
            "outward_supplies": {"taxable": {"iamt": 100000.0}},
            "itc": {
                "available": {
                    "import_goods": {"iamt": 500000.0, "csamt": 0.0},
                    "rcm_inward": {"iamt": 50000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    "isd": {"iamt": 20000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    "all_other": {"iamt": 30000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                },
                "reversed": {},
            },
        }
        res = check_drc_mismatch_risks(
            gstr1_summary={"total_tax": 100000.0},
            gstr3b_data=g3b_data,
            gstr2b_total_itc=tot_2b,
        )
        # Claimed is exactly 600,000 against 2B 600,000 -> NO RISK
        assert res["drc_01c_itc_mismatch"]["risk_flag"] is False
        assert res["drc_01c_itc_mismatch"]["excess_claimed"] == 0.0


class TestComplianceRadarAndDiscoveryHonesty:
    def test_numeric_map_validation_helper(self):
        bounds = {"val_a": (0.0, 100.0), "val_b": (10.0, 50.0)}
        assert _validate_numeric_map("test", {"val_a": 50.0, "val_b": 25.0}, bounds) is True
        assert _validate_numeric_map("test", {"val_a": 150.0}, bounds) is False
        assert _validate_numeric_map("test", {"val_a": "string"}, bounds) is False
        assert _validate_numeric_map("test", {"unknown_key": 10.0}, bounds) is False
        assert _validate_numeric_map("test", "not_a_dict", bounds) is False

    def test_discovery_offline_zero_network_calls(self, monkeypatch):
        # Monkeypatch urlopen to raise error if called
        def explode_urlopen(*args, **kwargs):
            raise AssertionError("Network was accessed during offline discovery!")

        monkeypatch.setattr(urllib.request, "urlopen", explode_urlopen)

        advisories, mode = fetch_portal_advisories(live=False)
        assert mode == "bundled_snapshot"
        assert len(advisories) > 0
        assert all(adv.get("source_of_truth") == "bundled_snapshot" for adv in advisories)

    def test_radar_patch_updates_manifest_and_engine_computes_with_new_rate(self, tmp_path):
        current = load_rules_manifest()
        backup = json.loads(json.dumps(current))
        try:
            # Craft patch changing interest rate from 18% to 19% (0.19)
            patch = {
                "patch_id": "TEST_RATE_19",
                "authority": "CBIC Test Notification",
                "statutory_rules": {
                    "interest_rates": {
                        "section_50_1_net_cash_p_a": 0.19,
                    }
                }
            }
            patch_file = tmp_path / "patch_19.json"
            patch_file.write_text(json.dumps(patch))

            # Apply patch
            success = apply_compliance_patch(str(patch_file))
            assert success is True

            # Verify that get_interest_rate_50_1() now returns 0.19
            assert get_interest_rate_50_1() == 0.19

            # Verify that engine computation actually reflects 19%
            # ₹1,00,000 net cash for 365 days @ 19% = ₹19,000.00
            res = compute_statutory_interest(
                100000.0,
                "20-04-2026",
                "20-04-2027",
            )
            assert res["interest_amount"] == 19000.0
            assert res["annual_rate"] == 0.19
        finally:
            # Always restore manifest
            save_rules_manifest(backup)


class TestFilingPackConsistency:
    def test_filing_pack_writers_create_directories(self, tmp_path):
        nested_dir = tmp_path / "nested" / "output"
        g1_data = {
            "gstin": "27AAAAA0000A1Z2",
            "fp": "042026",
            "invoices": [
                {
                    "inum": "INV-1",
                    "idt": "10-04-2026",
                    "pos": "27",
                    "items": [{"txval": 10000.0, "rt": 18.0, "camt": 900.0, "samt": 900.0}],
                }
            ],
        }
        g3b_data = {
            "gstin": "27AAAAA0000A1Z2",
            "ret_period": "042026",
            "outward_supplies": {"taxable": {"txval": 10000.0, "camt": 900.0, "samt": 900.0}},
            "itc": {
                "available": {
                    "rcm_inward": {"iamt": 100.0, "camt": 50.0, "samt": 50.0, "csamt": 0.0},
                    "all_other": {"iamt": 500.0, "camt": 200.0, "samt": 200.0, "csamt": 0.0},
                }
            },
        }
        recon_data = {
            "summary": {
                "exact_matched_count": 1,
                "tolerance_matched_count": 0,
                "value_mismatch_count": 0,
                "in_books_only_count": 0,
                "in_2b_only_count": 0,
                "blocked_17_5_count": 0,
                "rule_37_count": 0,
            },
            "details": {},
        }

        g1_pack = str(nested_dir / "gstr1.md")
        g3b_pack = str(nested_dir / "gstr3b.md")
        recon_pack = str(nested_dir / "recon.md")

        generate_gstr1_filing_pack(g1_data, g1_pack)
        generate_gstr3b_filing_pack(g3b_data, g3b_pack)
        generate_reconciliation_report(recon_data, recon_pack)

        assert os.path.exists(g1_pack)
        assert os.path.exists(g3b_pack)
        assert os.path.exists(recon_pack)

        # Check Table 4(A)(3) in GSTR-3B pack
        with open(g3b_pack, "r", encoding="utf-8") as f:
            g3b_text = f.read()
        assert "4(A)(3) Inward Supplies (RCM)" in g3b_text

        # Check single-axis description in Recon report
        with open(recon_pack, "r", encoding="utf-8") as f:
            recon_text = f.read()
        assert "single-axis +/- ₹1.00 tax tolerance" in recon_text


class TestCliEndToEnd:
    def test_pipeline_produces_valid_artifacts_and_honest_table(self, tmp_path):
        sales = os.path.join(REPO_ROOT, "examples", "sample_sales_register.json")
        purchases = os.path.join(REPO_ROOT, "examples", "sample_purchase_register.json")
        gstr2b = os.path.join(REPO_ROOT, "examples", "sample_gstr2b.json")
        out_dir = str(tmp_path / "pipe_out")

        result = runner.invoke(app, [
            "pipeline",
            "--sales", sales,
            "--purchases", purchases,
            "--gstr2b", gstr2b,
            "--output-dir", out_dir,
            "--no-pdf",
        ])
        assert result.exit_code == 0, f"Pipeline output: {result.stdout}"
        assert "CA Signed PDF Statement" not in result.stdout

        # Verify artifacts
        g1_portal = os.path.join(out_dir, "gstr1_portal.json")
        g3b_portal = os.path.join(out_dir, "gstr3b_portal.json")
        with open(g1_portal, "r", encoding="utf-8") as f:
            g1_p = json.load(f)
        with open(g3b_portal, "r", encoding="utf-8") as f:
            g3b_p = json.load(f)

        assert validate_against_schema(g1_p, G1_SCHEMA_PATH) == []
        assert validate_against_schema(g3b_p, G3B_SCHEMA_PATH) == []
