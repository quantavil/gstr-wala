"""Comprehensive regression test suite for Core Engine Truth (Task 4).

Tests statutory invariants for:
  1. Date error propagation (§4.1): malformed dates raise ValueError; empty dates produce zero delay.
  2. Unified return type dispatch (§4.2): dual-keyset ambiguity raises ValueError in engine and validator.
  3. CDNR and Advances netting (§4.3): credit/debit notes and advances properly net into summary totals.
  4. Model validation hardening (§4.4 & §4.5): POS validation, calendar date checks, and Mod-36 checksum.
  5. Manifest-driven rates (§4.6): rates and fee schedules are sourced from rules_manifest.json.
  6. Table 5 B2CL statutory rule: interstate B2C > ₹1L for goods and services.
"""

import pytest
from pydantic import ValidationError

from scripts.constants import (
    compute_gstin_checksum,
    detect_return_type,
    get_interest_rate_50_1,
    get_late_fee_caps,
)
from scripts.gst_engine import (
    compute,
    compute_gstr1_tables,
    compute_statutory_interest,
    compute_statutory_late_fee,
    parse_date,
)
from scripts.models import GSTR1Invoice, GSTR3BInput
from scripts.validate_gst_input import validate_gst_payload

# --- 1. Date Error Propagation (§4.1) ----------------------------------------


class TestDateErrorPropagation:
    def test_malformed_slash_date_raises_value_error(self):
        """Malformed slash date '20/05/2026' raises ValueError naming the offending string."""
        with pytest.raises(ValueError, match="Malformed date string"):
            parse_date("20/05/2026")

        with pytest.raises(ValueError, match="Malformed date string"):
            compute_statutory_interest(100000.0, "20-04-2026", "20/05/2026")

        with pytest.raises(ValueError, match="Malformed date string"):
            compute_statutory_late_fee(False, "upto_1.5cr", "invalid-date", "20-05-2026")

    def test_absent_or_empty_date_returns_zero_delay(self):
        """Empty string or None date returns zero delay result."""
        assert parse_date(None) is None
        assert parse_date("") is None
        assert parse_date("   ") is None

        res_interest = compute_statutory_interest(100000.0, "", "")
        assert res_interest["delay_days"] == 0
        assert res_interest["interest_amount"] == 0.0

        res_fee = compute_statutory_late_fee(False, "upto_1.5cr", None, None)
        assert res_fee["delay_days"] == 0
        assert res_fee["total_late_fee"] == 0.0

    def test_valid_date_pair_computes_exact_statutory_interest(self):
        """15 days delay on ₹1,00,000 net cash liability computes exact statutory interest."""
        rate = get_interest_rate_50_1()
        expected = round(100000.0 * (rate / 365.0) * 15, 2)
        res = compute_statutory_interest(100000.0, "20-04-2026", "05-05-2026")
        assert res["delay_days"] == 15
        assert res["interest_amount"] == expected


# --- 2. Unified Return Type Dispatch (§4.2) -----------------------------------


class TestUnifiedReturnDispatch:
    def test_explicit_return_type_wins(self):
        assert detect_return_type({"return_type": "GSTR-1"}) == "GSTR-1"
        assert detect_return_type({"return_type": "gstr-3b"}) == "GSTR-3B"

    def test_inferred_return_types(self):
        assert detect_return_type({"invoices": [], "fp": "042026"}) == "GSTR-1"
        assert detect_return_type({"ret_period": "042026", "outward_supplies": {}}) == "GSTR-3B"

    def test_dual_keyset_ambiguity_raises_in_both_engine_and_validator(self):
        """Ambiguous payload containing both GSTR-1 and GSTR-3B keys raises ValueError."""
        ambiguous_payload = {
            "gstin": "27AAAAA0000A1Z2",
            "fp": "042026",
            "invoices": [],
            "ret_period": "042026",
            "outward_supplies": {"taxable": {"txval": 10000.0}},
        }

        with pytest.raises(ValueError, match="ambiguous payload"):
            detect_return_type(ambiguous_payload)

        with pytest.raises(ValueError, match="ambiguous payload"):
            compute(ambiguous_payload)

        val_res = validate_gst_payload(ambiguous_payload)
        assert not val_res.is_valid
        assert any("ambiguous payload" in e for e in val_res.errors)

    def test_unrecognized_payload_raises(self):
        with pytest.raises(ValueError, match="Unable to determine return type"):
            detect_return_type({"random_key": 123})


# --- 3. CDNR and Advances Netting into Summary (§4.3) -------------------------


class TestCDNRAndAdvancesNetting:
    def test_credit_note_reduces_summary_totals(self):
        """Invoice of ₹50,000 / ₹4,500 CGST+SGST and Credit Note of ₹10,000 / ₹900 CGST+SGST nets to ₹40,000 / ₹3,600."""
        payload = {
            "gstin": "27AAAAA0000A1Z2",
            "fp": "042026",
            "invoices": [
                {
                    "inum": "INV-01",
                    "idt": "10-04-2026",
                    "pos": "27",
                    "val": 59000.0,
                    "ctin": "27BBBBB1111B1Z2",
                    "items": [{"txval": 50000.0, "rt": 18.0, "camt": 4500.0, "samt": 4500.0}],
                }
            ],
            "credit_debit_notes": [
                {
                    "nt_num": "CRN-01",
                    "nt_dt": "15-04-2026",
                    "ntty": "C",
                    "inum": "INV-01",
                    "idt": "10-04-2026",
                    "pos": "27",
                    "val": 11800.0,
                    "ctin": "27BBBBB1111B1Z2",
                    "items": [{"txval": 10000.0, "rt": 18.0, "camt": 900.0, "samt": 900.0}],
                }
            ],
        }

        res = compute_gstr1_tables(payload)
        s = res["summary"]

        assert s["total_taxable"] == 40000.0
        assert s["total_cgst"] == 3600.0
        assert s["total_sgst"] == 3600.0
        assert s["total_tax"] == 7200.0

        # Raw passthrough tables remain intact
        assert len(res["table_4_b2b"]) == 1
        assert len(res["table_9_cdnr"]) == 1

    def test_advances_received_and_adjusted_net_into_summary(self):
        """Advances received add to liability, advances adjusted subtract from liability."""
        payload = {
            "gstin": "27AAAAA0000A1Z2",
            "fp": "042026",
            "invoices": [],
            "advances_received": [
                {"pos": "27", "items": [{"txval": 20000.0, "rt": 18.0, "camt": 1800.0, "samt": 1800.0}]}
            ],
            "advances_adjusted": [
                {"pos": "27", "items": [{"txval": 5000.0, "rt": 18.0, "camt": 450.0, "samt": 450.0}]}
            ],
        }

        res = compute_gstr1_tables(payload)
        s = res["summary"]
        assert s["total_taxable"] == 15000.0
        assert s["total_cgst"] == 1350.0
        assert s["total_sgst"] == 1350.0
        assert s["total_tax"] == 2700.0


# --- 4. Model Validation Hardening (§4.4 & §4.5) -----------------------------


class TestModelValidationHardening:
    def test_invalid_calendar_date_raises_in_models(self):
        """Invalid date 31-02-2026 fails calendar validation in Pydantic models."""
        with pytest.raises(ValidationError, match="Invalid calendar date"):
            GSTR1Invoice(
                inum="INV-1",
                idt="31-02-2026",
                pos="27",
                items=[{"txval": 100.0, "rt": 18.0, "camt": 9.0, "samt": 9.0}],
            )

        with pytest.raises(ValidationError, match="Invalid calendar date"):
            GSTR3BInput(
                gstin="27AAAAA0000A1Z2",
                ret_period="042026",
                due_date="31-02-2026",
            )

    def test_invalid_pos_raises_in_models(self):
        """Non-existent State Code '99' raises ValidationError for pos."""
        with pytest.raises(ValidationError, match="Invalid Place of Supply State Code"):
            GSTR1Invoice(
                inum="INV-1",
                idt="10-04-2026",
                pos="99",
                items=[{"txval": 100.0, "rt": 18.0, "iamt": 18.0}],
            )

    def test_single_gstin_checksum_source_and_error_guard(self):
        """Checksum calculation raises descriptive ValueError on non-charset characters."""
        with pytest.raises(ValueError, match="not in CHAR_SET"):
            compute_gstin_checksum("27AAAAA0000A1Z$")

        # Valid GSTIN checksum check
        assert compute_gstin_checksum("27AAAAA0000A1Z") == "2"


# --- 5. Manifest-Driven Rates (§4.6) -----------------------------------------


class TestManifestDrivenRates:
    def test_constants_expose_manifest_accessors(self):
        """Manifest accessors return expected statutory numbers from config/rules_manifest.json."""
        rate = get_interest_rate_50_1()
        assert 0.0 < rate <= 0.30

        caps = get_late_fee_caps()
        assert caps["nil_return_daily_cgst"] == 10.0
        assert caps["nil_return_max_cap_total"] == 500.0
        assert caps["upto_1.5cr_max_cap_total"] == 2000.0
        assert caps["slab_1.5cr_to_5cr_max_cap_total"] == 5000.0
        assert caps["above_5cr_max_cap_total"] == 10000.0


# --- 6. Table 5 B2CL Classification (Services & Goods > ₹1L) ------------------


class TestTable5B2CLClassification:
    def test_services_over_1l_interstate_unregistered_classify_as_b2cl(self):
        """Interstate unregistered services invoice with value > ₹1L routes to Table 5 B2CL."""
        payload = {
            "gstin": "27AAAAA0000A1Z2",  # Maharashtra
            "fp": "042026",
            "invoices": [
                {
                    "inum": "INV-SRV-01",
                    "idt": "10-04-2026",
                    "pos": "29",  # Karnataka (Inter-state)
                    "val": 118000.0,  # > ₹1,00,000
                    "ctin": None,  # Unregistered (B2C)
                    "items": [
                        {
                            "hsn_sc": "998311",  # SAC Code (Services)
                            "txval": 100000.0,
                            "rt": 18.0,
                            "iamt": 18000.0,
                        }
                    ],
                }
            ],
        }

        res = compute_gstr1_tables(payload)
        assert len(res["table_5_b2cl"]) == 1
        assert len(res["table_7_b2cs"]) == 0
        assert res["table_5_b2cl"][0]["inum"] == "INV-SRV-01"
