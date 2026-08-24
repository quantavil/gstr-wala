"""Truthful parsing regressions: money, dates, and loud failures over silent fabrication.

Covers the audit defect class where bad input was silently coerced into plausible
numbers (fabricated dates, invented taxes, ".0"-poisoned invoice numbers,
European decimal-comma mis-parsing).
"""

import datetime
import json
import os
from pathlib import Path

import pytest

from scripts.parse_purchase_register import parse_csv_purchases
from scripts.parse_sales_register import parse_csv_sales, parse_rows_sales
from scripts.utils import (
    excel_cell_to_str,
    normalize_date_str,
    safe_float,
    safe_float_strict,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# 1. safe_float / safe_float_strict: truthful money parsing
# ---------------------------------------------------------------------------


class TestSafeFloatAccountingNegatives:
    def test_parenthesised_negative(self):
        assert safe_float("(1,234.56)") == -1234.56

    def test_strict_parenthesised_negative(self):
        assert safe_float_strict("(1,234.56)") == -1234.56

    def test_plain_leading_minus(self):
        assert safe_float("-500.25") == -500.25

    def test_currency_then_parens(self):
        assert safe_float("(₹1,000.00)") == -1000.0


class TestSafeFloatCurrencySymbols:
    def test_rupee_symbol(self):
        assert safe_float("₹1,000") == 1000.0

    def test_rs_prefix(self):
        assert safe_float("Rs. 1,000") == 1000.0

    def test_inr_prefix(self):
        assert safe_float("INR 1000") == 1000.0

    def test_strict_currency(self):
        assert safe_float_strict("₹ 2,50,000.75") == 250000.75


class TestSafeFloatIndianGrouping:
    def test_indian_lakh_grouping(self):
        assert safe_float("1,23,456.78") == 123456.78

    def test_indian_crore_grouping(self):
        assert safe_float("12,34,56,789") == 123456789.0

    def test_us_style_grouping(self):
        assert safe_float("1,234,567.89") == 1234567.89


class TestEuropeanDecimalCommaRejected:
    """`1.234,56` must never silently become 1.23456."""

    def test_lenient_returns_default_never_misparses(self):
        assert safe_float("1.234,56", default=0.0) == 0.0

    def test_strict_raises(self):
        with pytest.raises(ValueError):
            safe_float_strict("1.234,56")

    def test_comma_only_two_digit_tail_is_european_not_indian(self):
        # "1234,56" is European decimal style; Indian grouping always ends in a
        # 3-digit group. Must not become 123456.
        assert safe_float("1234,56") == 0.0
        with pytest.raises(ValueError):
            safe_float_strict("1234,56")


class TestStrictRaisesOnGarbage:
    def test_abc_raises(self):
        with pytest.raises(ValueError):
            safe_float_strict("abc")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            safe_float_strict("")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            safe_float_strict(None)

    def test_lenient_garbage_still_returns_default(self):
        assert safe_float("abc") == 0.0
        assert safe_float(None) == 0.0
        assert safe_float("") == 0.0

    def test_backward_compat_numbers_and_commas(self):
        assert safe_float(14400.0) == 14400.0
        assert safe_float("80000.00") == 80000.0
        assert safe_float("80,000.00") == 80000.0


class TestMalformedGroupingShapesRejected:
    """Live-verified mis-parses that must be refused, not coerced."""

    @pytest.mark.parametrize("bad", ["1,2345", "1000,", "--5", "+-5"])
    def test_malformed_shape_rejected(self, bad):
        assert safe_float(bad) == 0.0  # lenient: default, never a wrong number
        with pytest.raises(ValueError):
            safe_float_strict(bad)

    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("1,23,456.78", 123456.78),
            ("12,34,56,789", 123456789.0),
            ("1,234,567.89", 1234567.89),
            ("(1,234.56)", -1234.56),
            ("₹ 2,50,000.75", 250000.75),
            ("Rs. 1,000", 1000.0),
            ("1234.56", 1234.56),
            (".5", 0.5),
            ("500-", -500.0),
        ],
    )
    def test_valid_forms_still_parse(self, raw, want):
        assert safe_float_strict(raw) == want


# ---------------------------------------------------------------------------
# 2. excel_cell_to_str: kills ".0"-poisoning at every Excel entry point
# ---------------------------------------------------------------------------


class TestExcelCellToStr:
    def test_integer_valued_float_becomes_int_string(self):
        assert excel_cell_to_str(1001.0) == "1001"

    def test_non_integer_float_preserved(self):
        assert excel_cell_to_str(1234.56) == "1234.56"

    def test_int_passthrough(self):
        assert excel_cell_to_str(1001) == "1001"

    def test_none_becomes_empty(self):
        assert excel_cell_to_str(None) == ""

    def test_datetime_becomes_ddmmyyyy(self):
        assert excel_cell_to_str(datetime.datetime(2026, 4, 5)) == "05-04-2026"

    def test_date_becomes_ddmmyyyy(self):
        assert excel_cell_to_str(datetime.date(2026, 12, 31)) == "31-12-2026"

    def test_string_stripped(self):
        assert excel_cell_to_str(" INV-001 ") == "INV-001"


# ---------------------------------------------------------------------------
# 3. normalize_date_str: explicit DD-MM / YYYY-MM-DD parsing, no separator hack
# ---------------------------------------------------------------------------


class TestNormalizeDateStr:
    def test_dashes_passthrough_canonical(self):
        assert normalize_date_str("05-04-2026") == "05-04-2026"

    def test_slashes_normalized(self):
        assert normalize_date_str("05/04/2026") == "05-04-2026"

    def test_iso_normalized_to_indian(self):
        assert normalize_date_str("2026-04-05") == "05-04-2026"

    def test_us_looking_date_interpreted_as_ddmm(self):
        # 04-05-2026 must be 4 May (DD-MM), not April 5th (US MM-DD)
        assert normalize_date_str("04-05-2026") == "04-05-2026"
        d = datetime.datetime.strptime(normalize_date_str("04-05-2026"), "%d-%m-%Y")
        assert d.day == 4 and d.month == 5

    def test_calendar_invalid_rejected(self):
        with pytest.raises(ValueError):
            normalize_date_str("31-02-2026")
        with pytest.raises(ValueError):
            normalize_date_str("2026-02-30")

    def test_unparseable_rejected(self):
        with pytest.raises(ValueError):
            normalize_date_str("April 5")

    def test_blank_rejected_with_context(self):
        with pytest.raises(ValueError) as exc:
            normalize_date_str("", context="Row 3 column 'invoice_date'")
        assert "Row 3" in str(exc.value)

    def test_excel_datetime_object_accepted(self):
        assert normalize_date_str(datetime.datetime(2026, 4, 5)) == "05-04-2026"


# ---------------------------------------------------------------------------
# 4. Sales register parser: no fabricated defaults, loud failures
# ---------------------------------------------------------------------------

GSTIN = "27AAAAA0000A1Z2"
FP = "042026"


def _sales_rows(*rows):
    header = ["invoice_number", "invoice_date", "customer_gstin", "pos",
              "taxable_value", "gst_rate", "igst", "cgst", "sgst"]
    return [dict(zip(header, r, strict=False)) for r in rows]


class TestSalesRegisterTruthfulness:
    def test_missing_invoice_date_raises_naming_row(self):
        rows = _sales_rows(["INV-1", "", GSTIN, "27", "10000", "18", "", "900", "900"])
        with pytest.raises(ValueError) as exc:
            parse_rows_sales(rows, GSTIN, FP)
        msg = str(exc.value)
        assert "invoice_date" in msg or "date" in msg.lower()
        assert "Row 1" in msg or "row 1" in msg.lower()
        assert "01-04-2026" not in msg  # must not reveal a fabricated fallback

    def test_missing_invoice_number_raises_even_for_short_rows(self):
        # Regression: short CSV row made DictReader emit None -> str "None"
        # passed as a real invoice number.
        raw_rows = [
            {"invoice_number": None, "invoice_date": "05-04-2026",
             "taxable_value": "100", "gst_rate": "18"},
        ]
        with pytest.raises(ValueError):
            parse_rows_sales(raw_rows, GSTIN, FP)

    def test_short_row_values_are_empty_not_none_strings(self):
        rows = [{
            "invoice_number": "INV-9",
            "invoice_date": "05-04-2026",
            "taxable_value": "1000",
            "gst_rate": "0",
            "description": None,   # simulates DictReader short-row None
            "hsn": None,
        }]
        result = parse_rows_sales(rows, GSTIN, FP)
        item = result["invoices"][0]["items"][0]
        assert item["desc"] == ""
        assert item["hsn_sc"] == ""
        assert item["uqc"] == ""
        assert item["qty"] is None

    def test_hsn_qty_uqc_never_invented(self):
        rows = _sales_rows(["INV-2", "06-04-2026", GSTIN, "27", "5000", "0", "", "", ""])
        result = parse_rows_sales(rows, GSTIN, FP)
        item = result["invoices"][0]["items"][0]
        assert item["hsn_sc"] != "9999"
        assert item["qty"] != 1.0 or item["qty"] is None
        assert item["uqc"] != "NOS" or item["uqc"] == ""
        assert item["qty"] is None
        assert item["uqc"] == ""

    def test_conflicting_ctin_same_inum_raises(self):
        rows = _sales_rows(
            ["INV-DUP", "05-04-2026", "29AAAAA0000A1ZY", "29", "10000", "18", "1800", "", ""],
            ["INV-DUP", "05-04-2026", "27BBBBB1111B1ZN", "27", "20000", "18", "", "1800", "1800"],
        )
        with pytest.raises(ValueError) as exc:
            parse_rows_sales(rows, GSTIN, FP)
        assert "INV-DUP" in str(exc.value)

    def test_blank_ctin_first_then_conflicting_row_raises(self):
        # First occurrence has a blank GSTIN; the conflict must fire once a
        # later row supplies one and a third row contradicts it.
        rows = _sales_rows(
            ["INV-BLANKCTIN", "05-04-2026", "", "27", "10000", "18", "1800", "", ""],
            ["INV-BLANKCTIN", "05-04-2026", "29AAAAA0000A1ZY", "29", "20000", "18", "3600", "", ""],
            ["INV-BLANKCTIN", "05-04-2026", "27BBBBB1111B1ZN", "27", "30000", "18", "", "5400", "5400"],
        )
        with pytest.raises(ValueError) as exc:
            parse_rows_sales(rows, GSTIN, FP)
        msg = str(exc.value)
        assert "INV-BLANKCTIN" in msg
        assert "29AAAAA0000A1ZY" in msg and "27BBBBB1111B1ZN" in msg

    def test_blank_ctin_backfilled_consistently_still_merges(self):
        rows = _sales_rows(
            ["INV-FILL", "05-04-2026", "", "27", "10000", "18", "1800", "", ""],
            ["INV-FILL", "05-04-2026", "29AAAAA0000A1ZY", "29", "20000", "18", "3600", "", ""],
        )
        result = parse_rows_sales(rows, GSTIN, FP)
        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["ctin"] == "29AAAAA0000A1ZY"
        assert len(result["invoices"][0]["items"]) == 2

    def test_same_ctin_same_inum_merges_as_line_items(self):
        rows = _sales_rows(
            ["INV-MERGE", "05-04-2026", "29AAAAA0000A1ZY", "29", "10000", "18", "1800", "", ""],
            ["INV-MERGE", "05-04-2026", "29AAAAA0000A1ZY", "29", "20000", "18", "3600", "", ""],
        )
        result = parse_rows_sales(rows, GSTIN, FP)
        assert len(result["invoices"]) == 1
        assert len(result["invoices"][0]["items"]) == 2

    def test_derive_taxes_default_off_raises_listing_aliases(self):
        rows = _sales_rows(["INV-T", "07-04-2026", GSTIN, "27", "10000", "18"])
        with pytest.raises(ValueError) as exc:
            parse_rows_sales(rows, GSTIN, FP)
        msg = str(exc.value)
        for alias in ("igst", "cgst", "sgst"):
            assert alias in msg

    def test_derive_taxes_true_preserves_old_derivation(self):
        rows = _sales_rows(["INV-T2", "07-04-2026", GSTIN, "27", "10000", "18"])
        result = parse_rows_sales(rows, GSTIN, FP, derive_taxes=True)
        item = result["invoices"][0]["items"][0]
        assert item["camt"] == 900.0 and item["samt"] == 900.0 and item["iamt"] == 0.0


class TestExplicitZeroTaxCellsVsAbsentColumns:
    """Tax columns PRESENT with explicit/blank zeros are user data — respect
    them (warn only); tax columns ABSENT is missing data — fail loudly."""

    def _zero_tax_row(self, igst="", cgst="", sgst=""):
        return ["INV-Z", "10-04-2026", GSTIN, "27", "10000", "18", igst, cgst, sgst]

    def test_blank_cells_in_present_columns_parse_with_stderr_warning(self, capsys):
        result = parse_rows_sales(_sales_rows(self._zero_tax_row()), GSTIN, FP)
        item = result["invoices"][0]["items"][0]
        assert item["iamt"] == 0.0 and item["camt"] == 0.0 and item["samt"] == 0.0
        err = capsys.readouterr().err
        assert "INV-Z" in err
        assert "zero tax" in err.lower()

    def test_explicit_zero_cells_also_warn_but_are_respected(self, capsys):
        result = parse_rows_sales(
            _sales_rows(self._zero_tax_row("0.00", "0.00", "0.00")), GSTIN, FP
        )
        item = result["invoices"][0]["items"][0]
        assert item["iamt"] == 0.0 and item["camt"] == 0.0 and item["samt"] == 0.0
        assert "zero tax" in capsys.readouterr().err.lower()

    def test_derive_taxes_true_never_overwrites_populated_zero_cells(self):
        result = parse_rows_sales(
            _sales_rows(self._zero_tax_row("0.00", "0.00", "0.00")), GSTIN, FP, derive_taxes=True
        )
        item = result["invoices"][0]["items"][0]
        assert item["iamt"] == 0.0 and item["camt"] == 0.0 and item["samt"] == 0.0

    def test_derive_taxes_true_ignores_blanks_when_columns_present(self):
        result = parse_rows_sales(_sales_rows(self._zero_tax_row()), GSTIN, FP, derive_taxes=True)
        item = result["invoices"][0]["items"][0]
        assert item["iamt"] == 0.0 and item["camt"] == 0.0 and item["samt"] == 0.0

    def test_no_warning_when_taxes_nonzero_or_rate_zero_or_export(self, capsys):
        ok_rows = [
            ["INV-NZ", "10-04-2026", GSTIN, "27", "10000", "18", "1800", "", ""],
            ["INV-R0", "11-04-2026", GSTIN, "27", "10000", "0", "", "", ""],
            ["INV-WOPAY", "12-04-2026", GSTIN, "97", "10000", "0", "", "", ""],
        ]
        parse_rows_sales(_sales_rows(*ok_rows), GSTIN, FP)
        assert "zero tax" not in capsys.readouterr().err.lower()

    def test_absent_tax_columns_still_raise_hard(self):
        rows = [["INV-T", "07-04-2026", GSTIN, "27", "10000", "18"]]
        with pytest.raises(ValueError) as exc:
            parse_rows_sales(_sales_rows(*rows), GSTIN, FP)
        for alias in ("igst", "cgst", "sgst"):
            assert alias in str(exc.value)

    def test_excel_path_shares_the_same_logic(self, capsys):
        # Same typed-cell shape as calamine output; exercises shared code path.
        raw_rows = [{
            "invoice_number": "INV-XL", "invoice_date": datetime.datetime(2026, 4, 10),
            "customer_gstin": GSTIN, "pos": "27",
            "taxable_value": 10000.0, "gst_rate": 18.0,
            "igst": None, "cgst": None, "sgst": None,
        }]
        result = parse_rows_sales(raw_rows, GSTIN, FP)
        item = result["invoices"][0]["items"][0]
        assert item["camt"] == 0.0 and item["samt"] == 0.0
        assert "zero tax" in capsys.readouterr().err.lower()

    def test_explicit_tax_columns_parse_without_flag(self):
        rows = _sales_rows(["INV-OK", "08-04-2026", "29AAAAA0000A1ZY", "29", "10000", "18", "1800", "", ""])
        result = parse_rows_sales(rows, GSTIN, FP)
        assert result["invoices"][0]["items"][0]["iamt"] == 1800.0

    def test_bad_money_garbage_raises(self):
        rows = _sales_rows(["INV-BAD", "09-04-2026", GSTIN, "27", "10O00", "18", "", "900", "900"])
        with pytest.raises(ValueError):
            parse_rows_sales(rows, GSTIN, FP)

    def test_accounting_negative_taxable_value_parses_truthfully(self):
        rows = _sales_rows(["INV-NEG", "09-04-2026", GSTIN, "27", "(1,234.56)", "0", "", "", ""])
        result = parse_rows_sales(rows, GSTIN, FP)
        assert result["invoices"][0]["items"][0]["txval"] == -1234.56

    def test_excel_float_poisoning_killed_at_parser_level(self):
        # Simulates calamine-typed cells reaching the row normalizer.
        rows = [{"invoice_number": 1001.0, "invoice_date": datetime.datetime(2026, 4, 5),
                 "customer_gstin": GSTIN, "pos": "27", "taxable_value": 5000.0,
                 "gst_rate": 0.0}]
        result = parse_rows_sales(rows, GSTIN, FP)
        inv = result["invoices"][0]
        assert inv["inum"] == "1001"          # not "1001.0"
        assert inv["idt"] == "05-04-2026"     # not "2026-04-05 00:00:00"

    def test_empty_register_raises_no_data_rows(self):
        with pytest.raises(ValueError, match="no data rows"):
            parse_rows_sales([], GSTIN, FP)


class TestSalesRegisterEntryPoints:
    def test_sample_fixture_parses_identically(self):
        result = parse_csv_sales(
            os.path.join(REPO_ROOT, "examples", "sample_sales_register.csv"), GSTIN, FP
        )
        assert len(result["invoices"]) == 4
        first = result["invoices"][0]
        assert first["inum"] == "INV-2026-001"
        assert first["idt"] == "05-04-2026"
        assert first["val"] == 118000.0
        item = first["items"][0]
        assert item["txval"] == 100000.0 and item["iamt"] == 18000.0
        assert item["hsn_sc"] == "8471" and item["qty"] == 5.0 and item["uqc"] == "NOS"

    def test_main_cli_roundtrip_matches_committed_golden(self, tmp_path, monkeypatch):
        out = tmp_path / "out.json"
        monkeypatch.setattr(
            "sys.argv",
            ["parse_sales_register.py",
             os.path.join(REPO_ROOT, "examples", "sample_sales_register.csv"),
             GSTIN, FP, str(out)],
        )
        from scripts.parse_sales_register import main as sales_main
        sales_main()
        generated = json.loads(out.read_text(encoding="utf-8"))
        # Unconditional regression: any parser behavior change on the sample
        # register must be a deliberate, reviewed fixture update.
        golden_path = os.path.join(REPO_ROOT, "tests", "fixtures", "golden_sales.json")
        golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
        assert generated == golden

    def test_main_rejects_empty_csv(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty.csv"
        empty.write_text("invoice_number,invoice_date,taxable_value\n", encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv", ["parse_sales_register.py", str(empty), GSTIN, FP, str(tmp_path / "o.json")]
        )
        from scripts.parse_sales_register import main as sales_main
        with pytest.raises(SystemExit):
            sales_main()

    def _no_tax_cols_csv(self, tmp_path):
        csv = tmp_path / "notax.csv"
        csv.write_text(
            "invoice_number,invoice_date,customer_gstin,pos,taxable_value,gst_rate\n"
            f"INV-DT,05-04-2026,{GSTIN},27,10000,18\n",
            encoding="utf-8",
        )
        return csv

    def test_main_derive_taxes_flag_enables_derivation(self, tmp_path, monkeypatch):
        out = tmp_path / "out.json"
        monkeypatch.setattr(
            "sys.argv",
            ["parse_sales_register.py", str(self._no_tax_cols_csv(tmp_path)),
             GSTIN, FP, str(out), "--derive-taxes"],
        )
        from scripts.parse_sales_register import main as sales_main
        sales_main()
        data = json.loads(out.read_text(encoding="utf-8"))
        item = data["invoices"][0]["items"][0]
        assert item["camt"] == 900.0 and item["samt"] == 900.0 and item["iamt"] == 0.0

    def test_main_without_flag_exits_cleanly_naming_the_flag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            ["parse_sales_register.py", str(self._no_tax_cols_csv(tmp_path)), GSTIN, FP,
             str(tmp_path / "o.json")],
        )
        from scripts.parse_sales_register import main as sales_main
        with pytest.raises(SystemExit) as ei:
            sales_main()
        assert "derive_taxes=True" in str(ei.value.code)


# ---------------------------------------------------------------------------
# 5. Purchase register parser mirrors the same rules
# ---------------------------------------------------------------------------


class TestPurchaseRegisterTruthfulness:
    def test_missing_date_raises(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,invoice_date,supplier_gstin,taxable_value\nPUR-1,,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            parse_csv_purchases(str(p))
        assert "invoice_date" in str(exc.value) or "date" in str(exc.value).lower()

    def test_date_error_names_supplying_alias(self, tmp_path):
        # Value came from the generic 'date' column — the calendar-invalid
        # error must name that alias, not a hardcoded 'invoice_date'.
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,date,supplier_gstin,taxable_value\nPUR-9,31-02-2026,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            parse_csv_purchases(str(p))
        assert "column 'date'" in str(exc.value)
        assert "column 'invoice_date'" not in str(exc.value)

    def test_date_error_for_idt_alias_names_idt(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,idt,supplier_gstin,taxable_value\nPUR-9,31-02-2026,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            parse_csv_purchases(str(p))
        assert "column 'idt'" in str(exc.value)

    def test_fabricated_default_date_gone(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,supplier_gstin,taxable_value\nPUR-1,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            parse_csv_purchases(str(p))

    def test_empty_file_raises_no_data_rows(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text("invoice_number,invoice_date,supplier_gstin\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no data rows"):
            parse_csv_purchases(str(p))

    def test_short_row_none_string_fixed(self, tmp_path):
        p = tmp_path / "pr.csv"
        # unpaid_days column present but row truncated -> DictReader yields None
        p.write_text(
            "invoice_number,invoice_date,supplier_gstin,pos,taxable_value,unpaid_days\n"
            "PUR-1,05-04-2026,29AAAAA0000A1ZY,27,500\n",
            encoding="utf-8",
        )
        purchases = parse_csv_purchases(str(p))
        assert purchases[0]["unpaid_days"] == 0
        assert purchases[0]["pos"] == "27"

    def test_dates_validated_and_canonicalized(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,invoice_date,supplier_gstin,taxable_value\n"
            "PUR-1,2026-04-05,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        purchases = parse_csv_purchases(str(p))
        assert purchases[0]["idt"] == "05-04-2026"
        p.write_text(
            "invoice_number,invoice_date,supplier_gstin,taxable_value\n"
            "PUR-1,31-02-2026,29AAAAA0000A1ZY,500\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            parse_csv_purchases(str(p))

    def test_accounting_negatives_parsed(self, tmp_path):
        p = tmp_path / "pr.csv"
        p.write_text(
            "invoice_number,invoice_date,supplier_gstin,taxable_value,cgst\n"
            "PUR-2,05-04-2026,29AAAAA0000A1ZY,\"(1,000.00)\",(90.00)\n",
            encoding="utf-8",
        )
        purchases = parse_csv_purchases(str(p))
        assert purchases[0]["txval"] == -1000.0
        assert purchases[0]["camt"] == -90.0

    def test_sample_fixture_parses_identically(self):
        purchases = parse_csv_purchases(
            os.path.join(REPO_ROOT, "examples", "sample_purchase_register.csv")
        )
        assert len(purchases) == 3
        assert purchases[0]["inum"] == "PUR-001"
        assert purchases[0]["idt"] == "04-04-2026"
        assert purchases[0]["txval"] == 80000.0 and purchases[0]["iamt"] == 14400.0

    def test_main_extension_check_case_insensitive(self, tmp_path, monkeypatch):
        src = os.path.join(REPO_ROOT, "examples", "sample_purchase_register.csv")
        upper = tmp_path / "REGISTER.CSV"
        upper.write_bytes(Path(src).read_bytes())
        out = tmp_path / "purchases.json"
        monkeypatch.setattr(
            "sys.argv", ["parse_purchase_register.py", str(upper), str(out)]
        )
        from scripts.parse_purchase_register import main as pr_main
        pr_main()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["purchases"]) == 3

    def test_main_golden_output_matches_committed_golden(self, tmp_path, monkeypatch):
        out = tmp_path / "purchases.json"
        monkeypatch.setattr(
            "sys.argv",
            ["parse_purchase_register.py",
             os.path.join(REPO_ROOT, "examples", "sample_purchase_register.json"),
             str(out)],
        )
        from scripts.parse_purchase_register import main as pr_main
        pr_main()
        generated = json.loads(out.read_text(encoding="utf-8"))
        # Unconditional regression: locks the canonical {"purchases": [...]}
        # shape (no double-wrapping) and every parsed field of the sample.
        golden_path = os.path.join(REPO_ROOT, "tests", "fixtures", "golden_purchase.json")
        golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
        assert generated == golden


# ---------------------------------------------------------------------------
# 6. GSTR-2B summary robustness (parse side only; flatten untouched)
# ---------------------------------------------------------------------------


class TestGstr2bSummaryRobustness:
    def test_summary_sums_survive_null_and_comma_strings(self, tmp_path, monkeypatch, capsys):
        import scripts.parse_gstr2b as pg

        fake_records = [
            {"txval": "1,000.00", "iamt": None, "camt": "90.00", "samt": "90.00", "csamt": None},
            {"txval": 2000.0, "iamt": 360.0, "camt": None, "samt": None, "csamt": 10.0},
        ]
        monkeypatch.setattr(pg, "flatten_gstr2b", lambda data: fake_records)
        g2b_file = tmp_path / "g2b.json"
        g2b_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["parse_gstr2b.py", str(g2b_file)])
        pg.main()
        out = capsys.readouterr().out
        assert "3,000.00" in out  # txval total: "1,000.00" + 2000
        assert "550.00" in out    # total ITC: 360 IGST + 90 CGST + 90 SGST + 10 Cess
