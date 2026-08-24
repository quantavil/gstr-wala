"""Comprehensive regression test suite for Fast Engine Honesty & Robustness (Task 3).

Tests statutory invariants for:
  1. Value-gated fuzzy matching (§3.1): ₹13.73 vs ₹1.78L repro lands in value_mismatches.
  2. Deterministic tie-breaking (§3.2): order-invariant candidate selection by (score DESC, tax_diff ASC, g2b_id ASC).
  3. Loud parity warning (§3.3): classification_performed=False and explicit warning string.
  4. Robustness parity (§3.4): string money parsing and Excel header validation.
"""

import pytest
from python_calamine import CalamineWorkbook
from rapidfuzz import fuzz

from scripts.reconcile_fast import (
    PARITY_WARNING,
    read_excel_calamine,
    reconcile_polars_rapidfuzz,
)


class TestFuzzyValueGate:
    def test_repro_audit_finding_13_vs_1_78l_diverts_to_value_mismatch(self):
        """Audit finding repro: INV07770 (₹13.73) vs INV0777X (₹1,78,200.00).

        Token sort ratio score is 87.5 (passes 85 cutoff), but massive tax difference
        must NOT match. Must divert to value_mismatch bucket.
        """
        books = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV07770",
                "txval": 76.28,
                "iamt": 13.73,
                "camt": 0.0,
                "samt": 0.0,
            }
        ]
        g2b = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV0777X",
                "txval": 990000.0,
                "iamt": 178200.0,
                "camt": 0.0,
                "samt": 0.0,
            }
        ]

        # Verify raw token sort ratio score passes 85 cutoff
        score = fuzz.token_sort_ratio("INV07770", "INV0777X")
        assert score >= 85.0

        res = reconcile_polars_rapidfuzz(books, g2b, fuzzy_cutoff=85.0)

        # Must NOT be counted as fuzzy matched
        assert res["fuzzy_matched_count"] == 0
        assert len(res["fuzzy_matches"]) == 0

        # Must land in value_mismatches
        assert res["value_mismatch_count"] == 1
        assert len(res["value_mismatches"]) == 1

        vm = res["value_mismatches"][0]
        assert vm["books_invoice"]["inum"] == "INV07770"
        assert vm["best_candidate_2b"]["inum"] == "INV0777X"
        assert vm["tax_diff"] == pytest.approx(178186.27, 0.01)
        assert vm["reason"] == "Tax difference exceeds value tolerance gate"

        # Missing in 2B count excludes value_mismatches
        assert res["missing_in_2b_count"] == 0
        assert res["unmatched_2b_count"] == 1

    def test_fuzzy_match_accepted_within_value_tolerance(self):
        """Fuzzy match with slight typo within 1% relative tolerance is accepted."""
        books = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-2026-001",
                "txval": 100000.0,
                "iamt": 18000.0,
                "camt": 0.0,
                "samt": 0.0,
            }
        ]
        g2b = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-2026-001X",
                "txval": 100050.0,
                "iamt": 18009.0,  # ₹9 diff on ₹18,000 tax (0.05% < 1% tolerance)
                "camt": 0.0,
                "samt": 0.0,
            }
        ]

        res = reconcile_polars_rapidfuzz(books, g2b, fuzzy_cutoff=85.0)
        assert res["fuzzy_matched_count"] == 1
        assert res["value_mismatch_count"] == 0
        assert res["missing_in_2b_count"] == 0
        assert res["unmatched_2b_count"] == 0


class TestDeterministicTieBreaking:
    def test_candidates_order_invariance(self):
        """Permutation of candidate list order produces deterministic match."""
        books = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-100",
                "txval": 10000.0,
                "iamt": 1800.0,
            }
        ]
        cand_a = {
            "ctin": "27AAAAA0000A1Z2",
            "inum": "INV-100A",
            "txval": 10000.0,
            "iamt": 1800.0,  # tax diff 0
        }
        cand_b = {
            "ctin": "27AAAAA0000A1Z2",
            "inum": "INV-100B",
            "txval": 10000.0,
            "iamt": 1801.0,  # tax diff 1.0
        }

        # Order 1: cand_b first, cand_a second
        res1 = reconcile_polars_rapidfuzz(books, [cand_b, cand_a], fuzzy_cutoff=80.0)
        # Order 2: cand_a first, cand_b second
        res2 = reconcile_polars_rapidfuzz(books, [cand_a, cand_b], fuzzy_cutoff=80.0)

        # In both cases, cand_a must win because its tax_diff (0.0) is lower than cand_b (1.0)
        assert res1["fuzzy_matches"][0]["gstr2b_invoice"]["inum"] == "INV-100A"
        assert res2["fuzzy_matches"][0]["gstr2b_invoice"]["inum"] == "INV-100A"


class TestLoudParityWarning:
    def test_parity_warning_and_classification_flag(self):
        """Result dict explicitly flags that fast engine skips statutory classification."""
        res = reconcile_polars_rapidfuzz([], [])
        assert res["classification_performed"] is False
        assert res["parity_warning"] == PARITY_WARNING
        assert "skips 17(5)/Rule 37/RCM/16(4)" in res["parity_warning"]

        books = [{"ctin": "27AAAAA0000A1Z2", "inum": "INV-1", "txval": 100.0, "iamt": 18.0}]
        g2b = [{"ctin": "27AAAAA0000A1Z2", "inum": "INV-1", "txval": 100.0, "iamt": 18.0}]
        res_matched = reconcile_polars_rapidfuzz(books, g2b)
        assert res_matched["classification_performed"] is False
        assert res_matched["parity_warning"] == PARITY_WARNING


class TestRobustnessParity:
    def test_string_money_parsing_no_crash(self):
        """String formatted currency ('1,800.00') does not crash fast engine."""
        books = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-101",
                "txval": "10,000.00",
                "iamt": "1,800.00",
            }
        ]
        g2b = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-101",
                "txval": "10,000.00",
                "iamt": "1,800.00",
            }
        ]

        res = reconcile_polars_rapidfuzz(books, g2b)
        assert res["exact_join_count"] == 1
        assert res["missing_in_2b_count"] == 0

    def test_excel_calamine_duplicate_headers_raises_value_error(self, monkeypatch):
        """Duplicate column headers in Excel sheet raise descriptive ValueError."""
        class MockSheet:
            def to_python(self):
                return [
                    ["inum", "inum", "val"],
                    ["INV-01", "INV-01", 100.0]
                ]

        class MockWorkbook:
            sheet_names = ("Sheet1",)

            def get_sheet_by_name(self, name):
                return MockSheet()

        monkeypatch.setattr(CalamineWorkbook, "from_path", lambda path: MockWorkbook())

        with pytest.raises(ValueError, match="Duplicate headers detected"):
            read_excel_calamine("dummy.xlsx")

    def test_excel_calamine_blank_headers_raises_value_error(self, monkeypatch):
        """Blank column headers in Excel sheet raise descriptive ValueError."""
        class MockSheet:
            def to_python(self):
                return [
                    ["inum", "", "val"],
                    ["INV-01", "some_data", 100.0]
                ]

        class MockWorkbook:
            sheet_names = ("Sheet1",)

            def get_sheet_by_name(self, name):
                return MockSheet()

        monkeypatch.setattr(CalamineWorkbook, "from_path", lambda path: MockWorkbook())

        with pytest.raises(ValueError, match="Blank headers detected"):
            read_excel_calamine("dummy.xlsx")
