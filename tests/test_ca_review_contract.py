"""Independent cases for the CA-reviewed preparation contract."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts.bridge_gstr1_to_gstr3b import bridge_gstr1_and_2b_to_3b, check_drc_mismatch_risks
from scripts.cli import app
from scripts.itc_optimizer import optimize_from_input_dict
from scripts.reconcile_gstr2b import reconcile
from scripts.validate_gst_input import validate_gstr1_input
from scripts.workflow import approve_run, purchase_records, validate_2b, verify_run

ROOT = Path(__file__).resolve().parents[1]


def invoice():
    return {"ctin": "29AAAAA0000A1ZY", "inum": "INV-1", "idt": "01-04-2026",
            "txval": 1000, "iamt": 180, "camt": 0, "samt": 0, "csamt": 0}


def statement(book=None):
    book = book or invoice()
    return {"gstin": "27AAAAA0000A1Z2", "fp": "042026", "data": {"docdata": {"b2b": [
        {"ctin": book["ctin"], "inv": [{"inum": book["inum"], "dt": book["idt"], "items": [
            {key: book[key] for key in ("txval", "iamt", "camt", "samt", "csamt")}]}]}
    ]}}}


def test_blocked_credit_gross_minus_reversal_is_zero():
    result = reconcile([dict(invoice(), is_blocked_17_5=True)], statement())
    table = result["gstr3b_table_4_auto_population"]
    assert table["table_4_a_5_all_other_itc"]["iamt"] == 180
    assert table["table_4_b_1_permanent_reversals_17_5"]["iamt"] == 180
    assert table["table_4_c_net_itc"]["iamt"] == 0


def test_partly_unpaid_credit_retains_paid_portion():
    result = reconcile([dict(invoice(), unpaid_days=200, unpaid_value=590)], statement())
    table = result["gstr3b_table_4_auto_population"]
    assert table["table_4_a_5_all_other_itc"]["iamt"] == 180
    assert table["table_4_b_2_temporary_reversals_rule37"]["iamt"] == 90
    assert table["table_4_c_net_itc"]["iamt"] == 90


@pytest.mark.parametrize("change", [
    {"iamt": 0, "camt": 90, "samt": 90}, {"txval": 99999}, {"inum": "OTHER-1"},
    {"idt": "02-04-2026"}, {"idt": ""}, {"previously_claimed": True},
])
def test_uncertain_or_previously_claimed_documents_are_not_claimed(change):
    result = reconcile([dict(invoice(), **change)], statement())
    assert result["gstr3b_table_4_auto_population"]["table_4_a_5_all_other_itc"]["total"] == 0
    assert result["details"]["review_required"] or result["details"]["value_mismatches"]


@pytest.mark.parametrize("available", ["Y", "N"])
def test_unmatched_import_never_auto_claimed(available):
    data = {"fp": "042026", "docdata": {"impg": [{"boe": [
        {"boenum": "1001", "boedt": "01-04-2026", "port_code": "INNSA1",
         "txval": 1000, "iamt": 180, "itcavl": available}]}]}}
    result = reconcile([], data)
    assert result["gstr3b_table_4_auto_population"]["table_4_a_1_import_goods"]["iamt"] == 0
    assert result["details"]["review_required"]


def test_matched_import_is_routed_once_to_import_bucket():
    data = {"fp": "042026", "docdata": {"impg": [{"boe": [
        {"boenum": "1001", "boedt": "01-04-2026", "port_code": "INNSA1",
         "txval": 1000, "iamt": 180}]}]}}
    book = dict(invoice(), ctin="ICEGATE", inum="1001", port_code="INNSA1")
    table = reconcile([book], data)["gstr3b_table_4_auto_population"]
    assert table["table_4_a_1_import_goods"]["iamt"] == 180
    assert table["table_4_a_5_all_other_itc"]["iamt"] == 0
    assert table["table_4_c_net_itc"]["iamt"] == 180


@pytest.mark.parametrize("paid,blocked,credit", [(False, False, 0), (True, False, 180), (True, True, 0)])
def test_rcm_liability_survives_credit_decision(paid, blocked, credit):
    data = statement()
    data["data"]["docdata"]["b2b"][0]["inv"][0]["rev"] = "Y"
    result = reconcile([dict(invoice(), rcm_paid=paid, is_blocked_17_5=blocked)], data)
    assert result["rcm_liability"]["iamt"] == 180
    assert result["gstr3b_table_4_auto_population"]["table_4_c_net_itc"]["iamt"] == credit
    sales = {"gstin": data["gstin"], "fp": data["fp"], "invoices": []}
    draft = bridge_gstr1_and_2b_to_3b(sales, result)
    assert draft["outward_supplies"]["rcm_inward"]["iamt"] == 180


def test_books_rcm_missing_from_2b_still_creates_cash_liability():
    result = reconcile([dict(invoice(), rchrg="Y")], {"fp": "042026", "docdata": {"b2b": []}})
    assert result["rcm_liability"]["iamt"] == 180


def test_hsn_alone_does_not_block_goods_vehicle():
    result = reconcile([dict(invoice(), hsn_sc="8704", is_blocked_17_5=False)], statement())
    assert result["summary"]["blocked_17_5_count"] == 0
    assert result["gstr3b_table_4_auto_population"]["table_4_c_net_itc"]["iamt"] == 180


def test_hsn_without_decision_is_held():
    result = reconcile([dict(invoice(), hsn_sc="870400")], statement())
    assert result["gstr3b_table_4_auto_population"]["table_4_c_net_itc"]["iamt"] == 0
    assert result["details"]["review_required"]


@pytest.mark.parametrize("bad", [{"foreign": []}, [3], [dict(invoice(), idt="")],
                             [dict(invoice(), iamt="garbage")], [dict(invoice(), rcm_paid="false")]])
def test_invalid_purchase_data_fails_loudly(bad):
    with pytest.raises(ValueError):
        purchase_records(bad)


def test_2b_taxpayer_and_period_boundaries():
    with pytest.raises(ValueError, match="does not match"):
        validate_2b(statement(), gstin="DIFFERENT", period="042026")
    with pytest.raises(ValueError, match="does not match"):
        validate_2b(statement(), gstin=statement()["gstin"], period="052026")


def test_rate_40_is_effective_dated():
    data = json.loads((ROOT / "examples/sample_sales_register.json").read_text())
    data["invoices"][0]["items"][0]["rt"] = 40
    assert not any("Invalid GST rate" in e for e in validate_gstr1_input(data).errors)
    data["invoices"][0]["idt"] = "01-09-2025"
    assert any("before 22-09-2025" in e for e in validate_gstr1_input(data).errors)


def test_outward_recipient_paid_tax_is_not_supplier_liability():
    sales = json.loads((ROOT / "examples/sample_sales_register.json").read_text())
    sales["invoices"] = [sales["invoices"][0]]
    sales["invoices"][0]["rchrg"] = "Y"
    assert bridge_gstr1_and_2b_to_3b(sales)["outward_supplies"]["taxable"]["iamt"] == 0


def test_zero_2b_baseline_is_review_not_safe():
    result = check_drc_mismatch_risks({}, {"itc": {"available": {"all_other": {"iamt": 180}}}}, 0)
    assert result["drc_01c_itc_mismatch"]["risk_flag"]
    assert result["drc_01c_itc_mismatch"]["excess_percentage"] is None


def test_negative_credit_not_silently_discarded():
    with pytest.raises(ValueError, match="negative"):
        optimize_from_input_dict({"itc": {"reversed": {"temporary_others": {"iamt": 180}}}})


def test_pipeline_publication_and_reproducibility(tmp_path):
    runner = CliRunner()
    output = tmp_path / "run"
    args = ["pipeline", "--sales", str(ROOT / "examples/sample_sales_register.json"),
            "--purchases", str(ROOT / "examples/sample_purchase_register.json"),
            "--gstr2b", str(ROOT / "examples/sample_gstr2b.json"),
            "--output-dir", str(output), "--no-pdf"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.exception
    manifest = json.loads((output / "review_manifest.json").read_text())
    assert len(manifest["sources"]["sales"]["sha256"]) == 64
    assert (output / "ca_review.md").exists()
    decisions = {issue["id"]: "Reviewed source records; accept current draft treatment" for issue in manifest["issues"]}
    approve_run(str(output), "Test reviewer", decisions)
    assert (output / "review_approval.json").exists()
    assert verify_run(str(output)) == "REVIEWED_DRAFT_NOT_FILED"
    with pytest.raises(FileExistsError):
        approve_run(str(output), "Test reviewer", decisions)
    before = (output / "gstr3b_portal.json").read_bytes()
    assert runner.invoke(app, args).exit_code != 0
    assert (output / "gstr3b_portal.json").read_bytes() == before
    (output / "gstr3b_portal.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        approve_run(str(output), "Test reviewer", decisions)
    with pytest.raises(ValueError, match="changed"):
        verify_run(str(output))


def test_earlier_annual_return_stops_fresh_claim():
    result = reconcile([dict(invoice(), annual_return_filed_on="10-05-2026")],
                       statement(), _16_4_cutoff="20-05-2026")
    assert result["summary"]["ineligible_2b_count"] == 1
    assert result["gstr3b_table_4_auto_population"]["table_4_a_5_all_other_itc"]["iamt"] == 0


def test_fast_exact_identity_does_not_hide_tax_head_mismatch():
    from scripts.reconcile_fast import reconcile_polars_rapidfuzz
    result = reconcile_polars_rapidfuzz([invoice()], [dict(invoice(), iamt=0, camt=90, samt=90)])
    assert result["exact_join_count"] == 0
    assert result["value_mismatch_count"] == 1


def test_unknown_2b_section_is_not_silently_dropped():
    data = statement()
    data["data"]["docdata"]["future_section"] = [{"inum": "1"}]
    with pytest.raises(ValueError, match="Unsupported"):
        validate_2b(data)


def test_ambiguity_can_be_resolved_by_date():
    data = statement()
    duplicate = deepcopy(data["data"]["docdata"]["b2b"][0]["inv"][0])
    duplicate["dt"] = "01-04-2025"
    data["data"]["docdata"]["b2b"][0]["inv"].append(duplicate)
    result = reconcile([invoice()], data)
    assert result["summary"]["exact_matched_count"] == 1


def test_nested_advances_reach_bridge():
    sales = {"gstin": "27AAAAA0000A1Z2", "fp": "042026", "invoices": [],
             "advances_received": [{"pos": "29", "items": [{"txval": 1000, "iamt": 180, "rt": 18}]}]}
    assert bridge_gstr1_and_2b_to_3b(sales)["outward_supplies"]["taxable"]["iamt"] == 180


def test_historical_b2cl_threshold():
    from scripts.gst_engine import compute_gstr1_tables

    sales = {"gstin": "27AAAAA0000A1Z2", "fp": "072024", "invoices": [
        {"inum": "HIST-1", "idt": "01-07-2024", "pos": "29", "val": 118000,
         "items": [{"txval": 100000, "iamt": 18000, "rt": 18}]}]}
    assert compute_gstr1_tables(sales)["summary"]["b2cl_count"] == 0
    sales["fp"] = "082024"
    assert compute_gstr1_tables(sales)["summary"]["b2cl_count"] == 1


def test_failed_pipeline_does_not_publish_partial_return(tmp_path):
    bad = deepcopy(statement())
    bad["gstin"] = "WRONG"
    source = tmp_path / "2b.json"
    source.write_text(json.dumps(bad))
    output = tmp_path / "run"
    result = CliRunner().invoke(app, ["pipeline",
        "--sales", str(ROOT / "examples/sample_sales_register.json"),
        "--purchases", str(ROOT / "examples/sample_purchase_register.json"),
        "--gstr2b", str(source), "--output-dir", str(output), "--no-pdf"])
    assert result.exit_code != 0
    assert not output.exists()
