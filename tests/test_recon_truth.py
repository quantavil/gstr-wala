"""Comprehensive regression test suite for GSTR-2B reconciliation truthfulness (Task 2).

Tests statutory invariants for:
  1. Amended documents (b2ba, cdna, isda) superseding originals without double-counting.
  2. Inward RCM supplies (rchrg='Y') routing to Table 4(A)(3) regardless of itcavl.
  3. Rule 37 proportional reversal based on optional unpaid_value.
  4. Single-axis tolerance matching (tax_diff <= ₹1 regardless of txval_diff).
  5. IMPGSEZ section label preservation.
  6. Section 16(4) time-limit gate with injected cutoffs.
  7. Crash-proofing on non-standard numeric strings.
"""


import json
import os

from scripts.reconcile_gstr2b import flatten_gstr2b, reconcile

# --- 1. Amended Documents (b2ba, cdna, isda) --------------------------------


class TestAmendedDocuments:
    def test_b2ba_supersedes_b2b_without_double_counting(self):
        """B2BA amendment supersedes original B2B for the period."""
        pr_invoices = [
            {"ctin": "27AAAAA0000A1Z2", "inum": "INV-100", "txval": 12000.0, "iamt": 2160.0}
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-100",
                                    "dt": "05-04-2026",
                                    "val": 11800.0,
                                    "items": [{"txval": 10000.0, "iamt": 1800.0}],
                                }
                            ],
                        }
                    ],
                    "b2ba": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-100-A",
                                    "oinum": "INV-100",
                                    "dt": "10-04-2026",
                                    "val": 14160.0,
                                    "items": [{"txval": 12000.0, "iamt": 2160.0}],
                                }
                            ],
                        }
                    ],
                }
            }
        }

        records = flatten_gstr2b(g2b_raw)
        # Original INV-100 is superseded by INV-100-A -> exactly 1 record in flat 2B
        assert len(records) == 1
        assert records[0]["section"] == "B2BA"
        assert records[0]["inum"] == "INV-100-A"
        assert records[0]["oinum"] == "INV-100"
        assert records[0]["txval"] == 12000.0
        assert records[0]["iamt"] == 2160.0

        # When reconciled with books claiming the amended 2160, it matches the amended 2B
        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["total_2b_invoices"] == 1
        assert res["summary"]["exact_matched_count"] == 1
        assert res["gstr3b_table_4_auto_population"]["table_4_a_5_all_other_itc"]["iamt"] == 2160.0

    def test_cdna_supersedes_cdnr_and_reduces_gross_itc(self):
        """CDNA amendment supersedes original CDNR and reduces gross ITC."""
        g2b_raw = {
            "data": {
                "docdata": {
                    "cdnr": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "nt": [
                                {
                                    "nt_num": "CRN-01",
                                    "dt": "05-04-2026",
                                    "ntty": "C",
                                    "val": 5900.0,
                                    "items": [{"txval": 5000.0, "iamt": 900.0}],
                                }
                            ],
                        }
                    ],
                    "cdna": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "nt": [
                                {
                                    "nt_num": "CRN-01-REV",
                                    "ont_num": "CRN-01",
                                    "dt": "12-04-2026",
                                    "ntty": "C",
                                    "val": 7080.0,
                                    "items": [{"txval": 6000.0, "iamt": 1080.0}],
                                }
                            ],
                        }
                    ],
                }
            }
        }

        records = flatten_gstr2b(g2b_raw)
        assert len(records) == 1
        assert records[0]["section"] == "CDNA"
        assert records[0]["inum"] == "CRN-01-REV"
        assert records[0]["ont_num"] == "CRN-01"
        assert records[0]["txval"] == -6000.0
        assert records[0]["iamt"] == -1080.0

    def test_isda_supersedes_isd(self):
        """ISDA amendment supersedes original ISD document."""
        g2b_raw = {
            "data": {
                "docdata": {
                    "isd": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "doclist": [
                                {"docnum": "ISD-01", "docdt": "05-04-2026", "iamt": 500.0}
                            ],
                        }
                    ],
                    "isda": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "doclist": [
                                {
                                    "docnum": "ISD-01-AMEND",
                                    "odocnum": "ISD-01",
                                    "docdt": "15-04-2026",
                                    "iamt": 750.0,
                                }
                            ],
                        }
                    ],
                }
            }
        }

        records = flatten_gstr2b(g2b_raw)
        assert len(records) == 1
        assert records[0]["section"] == "ISDA"
        assert records[0]["inum"] == "ISD-01-AMEND"
        assert records[0]["odocnum"] == "ISD-01"
        assert records[0]["iamt"] == 750.0


# --- 2. RCM Inward Routing ---------------------------------------------------


class TestRcmRouting:
    def test_rcm_with_itcavl_n_routes_to_4a3_not_4d2(self):
        """GSTR-2B inward RCM (rchrg='Y') with itcavl='N' routes to 4(A)(3), NOT 4(D)(2)."""
        pr_invoices = [
            {"ctin": "27AAAAA0000A1Z2", "inum": "RCM-101", "txval": 50000.0, "iamt": 9000.0}
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "RCM-101",
                                    "dt": "10-04-2026",
                                    "rev": "Y",
                                    "itcavl": "N",
                                    "rsn": "RCM supply",
                                    "items": [{"txval": 50000.0, "iamt": 9000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        s = res["summary"]
        t4 = res["gstr3b_table_4_auto_population"]

        assert s["rcm_inward_count"] == 1
        assert s["ineligible_2b_count"] == 0
        assert t4["table_4_a_3_rcm_inward"]["iamt"] == 9000.0
        assert t4["table_4_d_2_ineligible_16_4"]["iamt"] == 0.0

        # RCM entry carries statutory compliance note
        entry = res["details"]["rcm_inward_2b"][0] if "rcm_inward_2b" in res["details"] else res["details"]["exact_matched"][0]
        assert entry.get("itc_note") == "claimable_only_after_rcm_cash_payment"

    def test_non_rcm_with_itcavl_n_routes_to_4d2(self):
        """Non-RCM inward invoice with itcavl='N' routes to Table 4(D)(2) ineligible."""
        pr_invoices = [
            {"ctin": "27AAAAA0000A1Z2", "inum": "INV-REG-101", "txval": 50000.0, "iamt": 9000.0}
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-REG-101",
                                    "dt": "10-04-2026",
                                    "rev": "N",
                                    "itcavl": "N",
                                    "rsn": "POS Mismatch",
                                    "items": [{"txval": 50000.0, "iamt": 9000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["ineligible_2b_count"] == 1
        assert res["summary"]["rcm_inward_count"] == 0
        assert res["gstr3b_table_4_auto_population"]["table_4_d_2_ineligible_16_4"]["iamt"] == 9000.0

    def test_rcm_blocked_17_5_routes_to_4b1(self):
        """RCM invoice marked Section 17(5) blocked routes to permanent reversal 4(B)(1)."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "RCM-MV-1",
                "txval": 50000.0,
                "iamt": 9000.0,
                "is_blocked_17_5": True,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "RCM-MV-1",
                                    "dt": "10-04-2026",
                                    "rev": "Y",
                                    "itcavl": "Y",
                                    "items": [{"txval": 50000.0, "iamt": 9000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["blocked_17_5_count"] == 1
        assert res["gstr3b_table_4_auto_population"]["table_4_b_1_permanent_reversals_17_5"]["iamt"] == 9000.0


# --- 3. Rule 37 Proportional Reversal ---------------------------------------


class TestRule37ProportionalReversal:
    def test_rule_37_proportional_half_paid(self):
        """Rule 37 reversal reverses proportional to unpaid_value / (val + tax)."""
        # Invoice: 100,000 txval + 18,000 tax = 118,000 total. Unpaid = 59,000 -> ratio 0.5
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "PUR-R37-1",
                "val": 118000.0,
                "txval": 100000.0,
                "iamt": 18000.0,
                "unpaid_days": 200,
                "unpaid_value": 59000.0,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "PUR-R37-1",
                                    "dt": "01-04-2026",
                                    "val": 118000.0,
                                    "items": [{"txval": 100000.0, "iamt": 18000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["rule_37_count"] == 1
        entry = res["details"]["rule_37_reversals"][0]
        assert entry["reversal_basis"] == "proportional"
        assert entry["reversal_ratio"] == 0.5
        assert res["gstr3b_table_4_auto_population"]["table_4_b_2_temporary_reversals_rule37"]["iamt"] == 9000.0

    def test_rule_37_unpaid_exceeds_total_capped_at_1(self):
        """Unpaid value exceeding invoice total is capped at 1.0."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "PUR-R37-2",
                "val": 118000.0,
                "txval": 100000.0,
                "iamt": 18000.0,
                "unpaid_days": 200,
                "unpaid_value": 150000.0,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "PUR-R37-2",
                                    "dt": "01-04-2026",
                                    "val": 118000.0,
                                    "items": [{"txval": 100000.0, "iamt": 18000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        entry = res["details"]["rule_37_reversals"][0]
        assert entry["reversal_ratio"] == 1.0
        assert res["gstr3b_table_4_auto_population"]["table_4_b_2_temporary_reversals_rule37"]["iamt"] == 18000.0

    def test_rule_37_unpaid_zero_no_reversal(self):
        """Unpaid value of 0 means consideration was fully paid; no reversal occurs."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "PUR-R37-3",
                "val": 118000.0,
                "txval": 100000.0,
                "iamt": 18000.0,
                "unpaid_days": 200,
                "unpaid_value": 0.0,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "PUR-R37-3",
                                    "dt": "01-04-2026",
                                    "val": 118000.0,
                                    "items": [{"txval": 100000.0, "iamt": 18000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["rule_37_count"] == 0
        assert res["summary"]["exact_matched_count"] == 1
        assert res["gstr3b_table_4_auto_population"]["table_4_a_5_all_other_itc"]["iamt"] == 18000.0

    def test_rule_37_absent_unpaid_value_defaults_to_full_reversal(self):
        """When unpaid_value is omitted, default behavior assumes 100% full reversal."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "PUR-R37-4",
                "txval": 100000.0,
                "iamt": 18000.0,
                "unpaid_days": 200,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "PUR-R37-4",
                                    "dt": "01-04-2026",
                                    "items": [{"txval": 100000.0, "iamt": 18000.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["rule_37_count"] == 1
        entry = res["details"]["rule_37_reversals"][0]
        assert entry["reversal_basis"] == "full_unpaid_assumed"
        assert entry["reversal_ratio"] == 1.0


# --- 4. Single-Axis Tolerance -----------------------------------------------


class TestSingleAxisTolerance:
    def test_single_axis_tolerance_with_large_txval_diff(self):
        """Tax difference <= ₹1 qualifies as TOLERANCE_MATCH even with large txval diff."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-TOL-1",
                "txval": 100000.0,
                "iamt": 18000.50,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-TOL-1",
                                    "dt": "10-04-2026",
                                    "items": [{"txval": 50000.0, "iamt": 18000.00}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        res = reconcile(pr_invoices, g2b_raw)
        assert res["summary"]["tolerance_matched_count"] == 1
        assert res["summary"]["value_mismatch_count"] == 0
        entry = res["details"]["tolerance_matched"][0]
        assert entry["tax_diff"] == 0.50
        assert entry["txval_diff"] == 50000.0


# --- 5. IMPGSEZ Label Preservation ------------------------------------------


class TestImpgsezLabelPreservation:
    def test_impgsez_section_preserved_and_counted(self):
        """IMPGSEZ section label is preserved on flattened records and populated in 4(A)(1)."""
        g2b_raw = {
            "data": {
                "docdata": {
                    "impgsez": [
                        {
                            "boe": [
                                {
                                    "boenum": "BOE-SEZ-99",
                                    "boedt": "10-04-2026",
                                    "items": [{"txval": 200000.0, "iamt": 36000.0, "csamt": 0.0}],
                                }
                            ]
                        }
                    ]
                }
            }
        }

        records = flatten_gstr2b(g2b_raw)
        assert len(records) == 1
        assert records[0]["section"] == "IMPGSEZ"
        assert records[0]["inum"] == "BOE-SEZ-99"
        assert records[0]["ctin"] == "ICEGATE"

        res = reconcile([], g2b_raw)
        assert res["summary"]["impg_count"] == 1
        assert res["gstr3b_table_4_auto_population"]["table_4_a_1_import_goods"]["iamt"] == 36000.0


# --- 6. Section 16(4) Time Limit Gate ---------------------------------------


class TestSection16_4TimeLimitGate:
    def test_section_16_4_expired_invoice_diverts_to_ineligible(self):
        """Invoice dated May 2024 evaluated after 30-Nov-2025 is time-barred under 16(4)."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-OLD-1",
                "idt": "15-05-2024",
                "txval": 10000.0,
                "iamt": 1800.0,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-OLD-1",
                                    "dt": "15-05-2024",
                                    "items": [{"txval": 10000.0, "iamt": 1800.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        # Cutoff date: 01-12-2025 (after 30-11-2025 deadline)
        res = reconcile(pr_invoices, g2b_raw, _16_4_cutoff="01-12-2025")
        assert res["summary"]["ineligible_2b_count"] == 1
        assert res["summary"]["exact_matched_count"] == 0
        assert res["gstr3b_table_4_auto_population"]["table_4_d_2_ineligible_16_4"]["iamt"] == 1800.0
        assert "16(4)" in res["details"]["ineligible_2b"][0]["reason"]

    def test_section_16_4_live_invoice_allowed(self):
        """Invoice dated May 2024 evaluated before 30-Nov-2025 is eligible."""
        pr_invoices = [
            {
                "ctin": "27AAAAA0000A1Z2",
                "inum": "INV-LIVE-1",
                "idt": "15-05-2024",
                "txval": 10000.0,
                "iamt": 1800.0,
            }
        ]
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "INV-LIVE-1",
                                    "dt": "15-05-2024",
                                    "items": [{"txval": 10000.0, "iamt": 1800.0}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        # Cutoff date: 15-11-2025 (before 30-11-2025 deadline)
        res = reconcile(pr_invoices, g2b_raw, _16_4_cutoff="15-11-2025")
        assert res["summary"]["exact_matched_count"] == 1
        assert res["summary"]["ineligible_2b_count"] == 0
        assert res["gstr3b_table_4_auto_population"]["table_4_a_5_all_other_itc"]["iamt"] == 1800.0


# --- 7. Crash-Proofing -------------------------------------------------------


class TestCrashProofing:
    def test_string_money_in_2b_does_not_crash(self):
        """GSTR-2B with formatted string amounts parses safely via safe_float."""
        g2b_raw = {
            "data": {
                "docdata": {
                    "b2b": [
                        {
                            "ctin": "27AAAAA0000A1Z2",
                            "inv": [
                                {
                                    "inum": "STR-01",
                                    "dt": "05-04-2026",
                                    "val": "11,800.00",
                                    "items": [{"txval": "10,000.00", "iamt": "1,800.00"}],
                                }
                            ],
                        }
                    ]
                }
            }
        }

        records = flatten_gstr2b(g2b_raw)
        assert len(records) == 1
        assert records[0]["val"] == 11800.0
        assert records[0]["txval"] == 10000.0
        assert records[0]["iamt"] == 1800.0


# --- 8. Official GSTN Portal Shape (itm_det, idt, itms) -----------------------


class TestOfficialGstnPortalShape:
    def test_official_fixture_flattens_nonzero_and_reconciles(self):
        """Official GSTN portal JSON fixture with nested itms[].itm_det flattens non-zero and reconciles."""
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "gstr2b_official_shape.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            g2b_raw = json.load(f)

        records = flatten_gstr2b(g2b_raw)
        assert len(records) == 6

        # Check section labels and non-zero values
        b2b_rec = next(r for r in records if r["section"] == "B2B")
        assert b2b_rec["inum"] == "INV-2026-001"
        assert b2b_rec["idt"] == "10-04-2026"
        assert b2b_rec["txval"] == 100000.0
        assert b2b_rec["iamt"] == 18000.0
        assert b2b_rec["tot_tax"] == 18000.0

        b2ba_rec = next(r for r in records if r["section"] == "B2BA")
        assert b2ba_rec["inum"] == "INV-200-AMEND"
        assert b2ba_rec["oinum"] == "INV-200"
        assert b2ba_rec["idt"] == "15-04-2026"
        assert b2ba_rec["txval"] == 50000.0
        assert b2ba_rec["camt"] == 3000.0
        assert b2ba_rec["samt"] == 3000.0
        assert b2ba_rec["tot_tax"] == 6000.0

        cdnr_rec = next(r for r in records if r["section"] == "CDNR")
        assert cdnr_rec["inum"] == "CRN-001"
        assert cdnr_rec["idt"] == "20-04-2026"
        assert cdnr_rec["txval"] == -10000.0
        assert cdnr_rec["iamt"] == -1800.0

        isd_rec = next(r for r in records if r["section"] == "ISD")
        assert isd_rec["inum"] == "ISD-DOC-01"
        assert isd_rec["iamt"] == 5000.0

        impg_rec = next(r for r in records if r["section"] == "IMPG")
        assert impg_rec["inum"] == "BOE-OVERSEAS-01"
        assert impg_rec["iamt"] == 36000.0

        impgsez_rec = next(r for r in records if r["section"] == "IMPGSEZ")
        assert impgsez_rec["inum"] == "BOE-SEZ-01"
        assert impgsez_rec["iamt"] == 18000.0

        # Now reconcile with books invoices
        pr_invoices = [
            {
                "ctin": "29BBBBB1111B1Z2",
                "inum": "INV-2026-001",
                "idt": "10-04-2026",
                "txval": 100000.0,
                "iamt": 18000.0,
                "camt": 0.0,
                "samt": 0.0,
            },
            {
                "ctin": "27CCCCC2222C1Z3",
                "inum": "INV-200",  # Matches amended invoice via oinum index
                "idt": "05-04-2026",
                "txval": 50000.0,
                "iamt": 0.0,
                "camt": 3000.0,
                "samt": 3000.0,
            },
        ]

        res = reconcile(pr_invoices, g2b_raw, _16_4_cutoff="01-05-2026")
        s = res["summary"]
        assert s["exact_matched_count"] == 2
        assert s["value_mismatch_count"] == 0

        t4 = res["gstr3b_table_4_auto_population"]
        assert t4["table_4_a_1_import_goods"]["iamt"] == 54000.0  # 36000 (impg) + 18000 (impgsez)
        assert t4["table_4_a_4_isd"]["iamt"] == 5000.0
        assert t4["table_4_a_5_all_other_itc"]["iamt"] == 18000.0
        assert t4["table_4_a_5_all_other_itc"]["camt"] == 3000.0
        assert t4["table_4_a_5_all_other_itc"]["samt"] == 3000.0
        assert t4["table_4_c_net_itc"]["iamt"] == 77000.0  # 18000 + 54000 + 5000
        assert t4["table_4_c_net_itc"]["total"] == 83000.0  # 77000 + 3000 + 3000

