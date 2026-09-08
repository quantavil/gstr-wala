# AGENT.md - Guidelines for AI Agents Working on gstr-wala

## Repository Purpose
`gstr-wala` is a self-contained AI Agent Skill (`SKILL.md`) and deterministic Python engine suite for Indian Goods and Services Tax (GST) filing (GSTR-1, GSTR-3B, GSTR-2B reconciliation, Rule 88A set-off optimization, multi-page PDF vision rasterization, and live statutory discovery).

## Iron Rules
1. **Never do tax arithmetic yourself.** All turnover, tax, interest, late fees, and credit allocations must be calculated by tested Python scripts in `scripts/`.
2. **Strict user data isolation (Zero Outbound Data Leaks).** All user financial data, client sales/purchase registers, Rule 88A calculations, reconciliation, and GST filings are processed 100% locally. Never transmit, export, or send any user or client financial data to remote endpoints. Inbound internet access is fully permitted to retrieve public information (official CBIC notifications, GSTN portal advisories, tax rate lookups, HSN codes, and documentation).
3. **No credentials.** Never ask for, read, or store user GST portal passwords, OTPs, or bank logins.
4. **User performs final acts.** User uploads offline JSON, pays PMT-06 challan, clicks Submit, and verifies with EVC OTP.


## Blunder Log (Root Cause + Fix)
- **2026-09-08:** XlsxWriter formula value caching: Omitting value parameter in write_formula() causes external readers and Calamine to see 0.0; always pass pre-computed value argument.
- **2026-09-08:** Invoice round-off regex parsing: Parenthesized signs like `(+) 0.20` or `(-) 0.38` fail standard `[+-]?` regex; use `(?:\(([+\-])\)|([+\-]))?\s*([\d\.]+)` with explicit sign handling.
- **2026-09-08:** PyMuPDF text block order: Unsorted get_text() in PDF layout extraction can cause party names to transpose with labels; strictly use get_text('text', sort=True) or table extraction.
- **2026-09-08:** GST Portal offline upload validation root cause: Portal validator strictly requires `"version": "GST3.2.4"` and `"hash": "hash"`, and rejects portal-download fields (`filing_typ`, `cfs`, `flag`, `updby`, `cflag`, `chksum`).
- **2026-09-08:** Official `GST Offline Tool.exe` reverse-engineering: App unpacked via `innoextract` is Electron/Node; `readXML` assumes multi-sheet `.xlsx` (`b2b` sheet, skips 3 rows), causing flat CSVs to be silently dropped.
- **2026-09-08:** GSTR-1 item numbering and inactive tax heads: Official tool sets `num = int(rt * 100)` (e.g. 1800, 500) and prunes inactive zero-tax heads (`iamt` on intra, `camt`/`samt` on inter, `csamt` when 0) before `omitEmpty`.
- **2026-09-08:** CI Mypy Union-attr & Money Parser Duplication: In `generate_sales_register.py`, checking raw dict value without local assignment caused mypy `union-attr` failure; unified duplicated `_money()` helpers into `parse_money_field` in `utils.py` and wrapped `models.validate_gstin_str` in `validate_gst_input.py`.
- **2026-09-08:** CI Mypy type collision & duplicate annotation: Variable type re-assignment across branches in `omit_empty_structure` and repeated explicit typing of `itm_det` broke CI; renamed branch vars and pruned redundant annotation.
- **2026-09-08:** Runtime preference: User strictly prefers Bun (upgraded to latest v1.4.2) over Node.js for all JS/TS tools, headless pipelines, and JSON validations.
- **2026-09-08:** RCM liability vs credit separation: Recipient RCM liability is strictly 100% cash payable (Table 3.1d); corresponding ITC (Table 4A3) requires explicit payment confirmation (`rcm_paid: true`).
- **2026-08-25:** Bridge CLI input overwrite: `"3b" not in name` heuristic silently overwrote recon inputs; fixed with content-based detection and `--force` guard.
- **2026-08-25:** Statutory dues omitted in portal upload: Sec 50 interest and Sec 47 late fees were not forwarded to Table 6.1 `paid_cash`; wired `interest_details` while keeping `paid_cash` tax-only.
- **2026-08-25:** Value-mismatch ITC auto-claim: Mismatches were auto-claimed into Table 4(A)(5); routed to `table_4_a_5_value_mismatch_hold` for manual review.
- **2026-08-25:** Section 16(4) wall-clock dependency: Non-deterministic `datetime.now()` fallback broke reproducible audits; fixed to evaluate deterministically from return period `fp`.
- **2026-08-24:** B2CL threshold statutory update: B2CL threshold was reduced from ₹2.5L to ₹1.0L effective August 1, 2024 (Notification 12/2024-CT); all engines use ₹1,00,000.
- **2026-08-24:** LUT export tax calculation: Zero-rated exports under LUT (`WOPAY`) incorrectly had IGST auto-calculated; fixed in `parse_sales_register.py`.
- **2026-08-24:** RCM inward double-counting: RCM inward supplies were counted in both Table 3.1d and Table 4(A)(5); made mutually exclusive.
- **2026-08-24:** Obsolete state codes: State codes 25 and 28 were obsolete but passing checksums; purged from `STATE_CODES`.

## Current Architecture & Key Modules
- `SKILL.md`: Master agentic skill definition (10-step workflow, iron rules, reference index).
- `config/rules_manifest.json`: Machine-readable statutory rules manifest.
- `scripts/constants.py`: Centralized statutory constants, thresholds, state codes, and regexes.
- `scripts/models.py`: Pydantic v2 data models for GSTR-1, GSTR-3B, purchases, and 2B.
- `scripts/cli.py`: Typer & Rich interactive CLI runner.
- `scripts/validate_gst_input.py`: Mod-36 checksum, POS, rate, date, non-negativity, and credential safety checks.
- `scripts/gst_engine.py`: Outward aggregation (Tables 4, 5, 6, 7, 8, 9, 11, 12, 13), Sec 50 interest, Sec 47 late fee.
- `scripts/itc_optimizer.py`: Rule 88A linear optimization, RCM 100% Cash rule, Challan PMT-06.
- `scripts/reconcile_gstr2b.py`: GSTR-2B 2-way matcher with CDNR, ISD, and IMPG processing.
- `scripts/reconcile_fast.py`: Polars + Calamine + RapidFuzz high-scale engine (100k invoices in 8.9s).
- `scripts/ingest_pdf_vision.py`: Multi-page PDF to high-DPI image rasterizer with smart digital vs scanned auto-detection and force-image mode (PyMuPDF).
- `scripts/generate_gstr1_json.py` & `generate_gstr3b_json.py`: Official GST Portal offline upload serializers.
- `scripts/bridge_gstr1_to_gstr3b.py`: Auto-population bridge & DRC-01B/DRC-01C risk radar.
- `scripts/generate_filing_pack.py`: Audit-ready Markdown CA filing pack generator.
- `scripts/generate_pdf_statement.py`: Jinja2 + WeasyPrint certified CA statement generator.
- `scripts/gstr_offline_runner.ts`: Bun-native high-performance official GSTR-1 offline JSON generator and validator.
- `scripts/generate_sales_register.py`: Audit-ready 4-sheet Excel sales register generator with Executive Dashboard, Master Invoices, Itemized Details, Table 12 HSN (XlsxWriter), and direct upload-ready GSTR-1 export.
- `scripts/discover_statutory_rules.py`: Live statutory compliance discovery radar.
- `scripts/compliance_radar.py`: Self-updating statutory rule engine.
- `tests/`: 277 Pytest unit, integration, property (Hypothesis), contract, and fuzz tests (100% pass via `uv run pytest`).

