# AGENT.md - Guidelines for AI Agents Working on gstr-wala

## Repository Purpose
`gstr-wala` is a self-contained AI Agent Skill (`SKILL.md`) and deterministic Python engine suite for Indian Goods and Services Tax (GST) filing (GSTR-1, GSTR-3B, GSTR-2B reconciliation, Rule 88A set-off optimization, multi-page PDF vision rasterization, and live statutory discovery).

## Iron Rules
1. **Never do tax arithmetic yourself.** All turnover, tax, interest, late fees, and credit allocations must be calculated by tested Python scripts in `scripts/`.
2. **Strict local execution.** No external server daemons or external network dependencies required.
3. **No credentials.** Never ask for, read, or store user GST portal passwords, OTPs, or bank logins.
4. **User performs final acts.** User uploads offline JSON, pays PMT-06 challan, clicks Submit, and verifies with EVC OTP.

## Blunder Log (Root Cause + Fix)
- **2026-08-24:** Avoided recursive subprocess execution in `scripts/compliance_radar.py` by targeting core business test suites explicitly.
- **2026-08-24:** Handled export under LUT (`WOPAY`) in `parse_sales_register.py` to prevent auto-calculating IGST on zero-rated export supplies.
- **2026-08-24:** Upgraded Pydantic models from deprecated `min_items` to `min_length`.
- **2026-08-24:** B2CL threshold was revised from ₹2.5 Lakh to ₹1 Lakh effective August 1, 2024 (Notification No. 12/2024-CT). Ensured all engines use ₹1,00,000 threshold.
- **2026-08-24:** Key mismatch between 3B generator and canonical schema caused Table 3.1.1/4D/5 to emit zero; aligned keys across serializers and added roundtrip contract test.
- **2026-08-24:** Fixed RCM double-counting in `reconcile_2b.py` by making RCM inward routing mutually exclusive with Table 4(A)(5) "All Other ITC".
- **2026-08-24:** Removed obsolete state codes 25 and 28 from `STATE_CODES` to prevent invalid GSTINs from passing checksum/state validation.
- **2026-08-24:** Standalone CLI invocation of engine scripts failed without `-e .` install; added `sys.path.insert(0, ...)` bootstrap to all scripts and centralized constants in `scripts/constants.py`.

## Current Architecture & Key Modules
- `SKILL.md`: Master agentic skill definition (10-step workflow, iron rules, reference index).
- `config/rules_manifest.json`: Machine-readable statutory rules manifest.
- `scripts/constants.py`: Centralized statutory constants, thresholds, state codes, and regexes.
- `scripts/models.py`: Pydantic v2 data models for GSTR-1, GSTR-3B, purchases, and 2B.
- `scripts/cli.py`: Typer & Rich interactive CLI runner.
- `scripts/validate_gst_input.py`: Mod-36 checksum, POS, rate, date, non-negativity, and credential safety checks.
- `scripts/gst_engine.py`: Outward aggregation (Tables 4, 5, 6, 7, 8, 9, 11, 12, 13), Sec 50 interest, Sec 47 late fee.
- `scripts/itc_optimizer.py`: Rule 88A linear optimization, RCM 100% Cash rule, Challan PMT-06.
- `scripts/reconcile_2b.py`: GSTR-2B 2-way matcher with CDNR, ISD, and IMPG processing.
- `scripts/fast_engine.py`: Polars + Calamine + RapidFuzz high-scale engine (100k invoices in 8.9s).
- `scripts/pdf_to_images.py`: Multi-page PDF to image rasterizer for multimodal AI vision.
- `scripts/generate_gstr1_json.py` & `generate_gstr3b_json.py`: Official GST Portal offline upload serializers.
- `scripts/gstr1_to_3b_bridge.py`: Auto-population bridge & DRC-01B/DRC-01C risk radar.
- `scripts/generate_filing_pack.py`: Audit-ready Markdown CA filing pack generator.
- `scripts/generate_pdf_report.py`: Jinja2 + WeasyPrint certified CA statement generator.
- `scripts/fetch_live_compliance.py`: Live statutory compliance discovery radar.
- `scripts/compliance_radar.py`: Self-updating statutory rule engine.
- `tests/`: 48 Pytest unit, integration, property (Hypothesis), contract, and fuzz tests (100% pass via `uv run pytest`).
