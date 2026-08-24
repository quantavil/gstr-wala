# File & Artifact Naming Standardization Guide

This reference defines the canonical naming conventions for all source code, test suites, schemas, reference documentation, and generated output artifacts across the `gstr-wala` repository.

---

## 1. Core Principles

1. **Symmetrical Tax Return Prefixes:** Always use the full canonical identifier (`gstr1`, `gstr2b`, `gstr3b`) uniformly. Never mix truncated prefixes (e.g. `2b` or `3b`) with full prefixes.
2. **Case Consistency per Directory:** 
   - Python code & JSON schemas: **`snake_case`**
   - Reference documentation: **`kebab-case.md`**
   - Generated outputs: **lowercase `snake_case`** (`gstr1_portal.json`, `gstr1_filing_pack.md`, `gstr3b_statement.pdf`).
3. **Descriptive, Action-Oriented Script Names:** Scripts must clearly express their domain responsibility (`parse_*`, `validate_*`, `reconcile_*`, `generate_*`).

---

## 2. Directory-by-Directory Specifications

### A. Python Source Engines (`scripts/`)
Format: `snake_case.py`

| Script File | Purpose |
| :--- | :--- |
| `scripts/parse_sales_register.py` | Converts CSV/Excel sales ledgers to canonical GSTR-1 input |
| `scripts/parse_purchase_register.py` | Converts CSV/Excel purchase registers to canonical purchases JSON |
| `scripts/parse_gstr2b.py` | Parses official GST portal auto-drafted GSTR-2B JSON |
| `scripts/validate_gst_input.py` | Mod-36 checksum, POS, rate, and credential security validation |
| `scripts/gst_engine.py` | Outward tax aggregation, Section 50 interest, Section 47 late fees |
| `scripts/itc_optimizer.py` | Rule 88A linear set-off optimization & Challan PMT-06 calculation |
| `scripts/reconcile_gstr2b.py` | GSTR-2B 2-way matcher with CDNR, ISD, and IMPG processing |
| `scripts/reconcile_fast.py` | Polars + RapidFuzz high-volume engine (100k+ invoices) |
| `scripts/bridge_gstr1_to_gstr3b.py` | Outward + ITC bridge & DRC-01B/DRC-01C pre-emptive risk checks |
| `scripts/generate_gstr1_json.py` | Official GST portal GSTR-1 offline utility JSON serializer |
| `scripts/generate_gstr3b_json.py` | Official GST portal GSTR-3B offline utility JSON serializer |
| `scripts/generate_filing_pack.py` | Audit-ready Markdown CA filing pack generator |
| `scripts/generate_pdf_statement.py` | Certified CA PDF tax statement generator (Jinja2 + WeasyPrint) |
| `scripts/ingest_pdf_vision.py` | Multi-page PDF to PNG rasterizer with smart digital vs scanned detection |
| `scripts/discover_statutory_rules.py` | Live CBIC & GSTN public advisory radar |
| `scripts/compliance_radar.py` | Self-updating rule engine with staged test verification |

| `scripts/fuzz_gst_engine.py` | Invariant fuzzer for tax engine integrity |
| `scripts/models.py` | Pydantic v2 data models & TypedDicts |
| `scripts/constants.py` | Statutory rates, state codes, and regex constants |
| `scripts/utils.py` | Number rounding, date parsing, and string formatting helpers |
| `scripts/cli.py` | Typer interactive CLI application |

---

### B. Generated Outputs (`output/`)
Format: lowercase `snake_case`

| Output File | Content |
| :--- | :--- |
| `output/gstr1_portal.json` | Official GST Portal uploadable GSTR-1 offline JSON |
| `output/gstr3b_portal.json` | Official GST Portal uploadable GSTR-3B offline JSON |
| `output/gstr1_filing_pack.md` | Line-by-line GSTR-1 audit summary (Tables 4, 5, 6, 7, 8, 12, 13) |
| `output/gstr3b_filing_pack.md` | GSTR-3B computation & Rule 88A set-off filing pack |
| `output/gstr3b_statement.pdf` | Printable certified CA statement for client sign-off |

---

### C. Workspace Intermediate Files (`work/`)
Format: `snake_case.json` / `snake_case.md`

| Intermediate File | Purpose |
| :--- | :--- |
| `work/gstr1_input.json` | Validated sales register data |
| `work/purchase_register.json` | Validated purchase ledger data |
| `work/gstr3b_input.json` | Aggregated outward liability + eligible ITC inputs |
| `work/reconciliation_result.json` | Match results (`EXACT_MATCH`, `TOLERANCE_MATCH`, `BLOCKED_17_5`, etc.) |
| `work/images/image_manifest.json` | Multi-page PDF visual image index and strategy metadata |
| `work/progress.md` | Active session filing checklist and ARN tracking |

---

### D. JSON Schemas (`schemas/`)
Format: `snake_case.json`

| Schema File | Validates |
| :--- | :--- |
| `schemas/gstr1_input_schema.json` | User input sales register schema |
| `schemas/gstr3b_input_schema.json` | User input GSTR-3B aggregation schema |
| `schemas/gstr1_portal_schema.json` | Official GSTN offline portal upload format |
| `schemas/gstr3b_portal_schema.json` | Official GSTN offline portal upload format |
| `schemas/gstr2b_schema.json` | Official GSTN GSTR-2B download format |

---

### E. Pytest Test Suites (`tests/`)
Format: `test_<target_script_or_domain>.py`

| Test File | Target Under Test |
| :--- | :--- |
| `tests/test_validate_gst_input.py` | Input validation, checksums, POS rules |
| `tests/test_gst_engine.py` | Outward tax calculation, Sec 50 interest, Sec 47 late fees |
| `tests/test_itc_optimizer.py` | Rule 88A linear solver & 100% cash RCM rule |
| `tests/test_reconcile_gstr2b.py` | 2-way 2B reconciliation & vendor matching |
| `tests/test_reconcile_fast.py` | 100,000 invoice scale benchmark (Polars + RapidFuzz) |
| `tests/test_portal_generators.py` | GSTR-1, GSTR-3B portal JSON serializers & filing packs |
| `tests/test_ingest_pdf_vision.py` | PyMuPDF multi-page rendering & digital vs scanned detection |

| `tests/test_fuzz_gst_engine.py` | Invariant fuzzer |
| `tests/test_property_invariants.py` | Hypothesis property testing |
| `tests/test_models.py` | Pydantic v2 data models |
| `tests/test_cli_commands.py` | Typer CLI runner integration |
| `tests/test_compliance_radar.py` | Statutory manifest self-updating engine |
| `tests/test_business_scenarios.py` | End-to-end industry filing scenarios (Manufacturing, SaaS, Retail) |
| `tests/test_official_gstn_compliance.py` | Portal schema contract roundtrips |

---

### F. Reference Guides (`references/`)
Format: `kebab-case.md`

- `references/gstr1-table-guide.md`
- `references/gstr3b-table-guide.md`
- `references/gstr2b-reconciliation-guide.md`
- `references/itc-rules-and-setoff.md`
- `references/rates-and-hsn-rules.md`
- `references/interest-and-late-fees.md`
- `references/drc-mismatch-audit-guide.md`
- `references/portal-walkthrough.md`
- `references/file-naming-standard.md`
