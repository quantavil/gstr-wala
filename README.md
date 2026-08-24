# gstr-wala 🇮🇳

[![Tests](https://img.shields.io/badge/pytest-210%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)]()
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> **Deterministic AI Agent Skill & Python Engine Suite for Indian GST Compliance (GSTR-1, GSTR-3B, GSTR-2B Reconciliation, Rule 88A Optimization, Multi-Page PDF Vision Ingestion & Agentic Compliance Radar)**

`gstr-wala` operates as a self-contained **AI Agent Skill (`SKILL.md`)** and standalone command-line suite for Claude Code, Codex, Gemini CLI, and Antigravity. It enables AI assistants and accountants to deterministically compute, reconcile, and generate GST Portal offline-tool-shaped JSON returns and certified CA tax audit statements.

---

## Key Features

- **Multi-Format Sales & Purchase Ingestion:**
  - Ingests CSV, Excel (`.xlsx`, `.xls`, `.xlsb` via **`python-calamine`**), and JSON registers directly without external server daemons.
- **GSTR-1 Outward Supply Engine:**
  - Automated Table 4 (B2B), Table 5 (B2CL > ₹1 Lakh per Notification No. 12/2024-CT), Table 6 (Exports & SEZ), Table 7 (B2CS), Table 8 (Nil/Exempt/Non-GST nested schema), Table 9 (CDNR/CDNUR), and Table 13 (Docs).
  - Table 12 HSN Summary with mandatory **Table 12A (B2B)** and **Table 12B (B2C)** bifurcation.
  - Offline-tool-shaped GSTR-1/3B JSON generators (`output/gstr1_portal.json`) — verify against the official Returns Offline Tool before upload.
- **GSTR-2B vs Purchase Register 2-Way Matcher:**
  - High-speed vectorized join via **`polars`** and C++/SIMD fuzzy matching via **`rapidfuzz`** (100,000 invoices processed in 8.9s at 11,204 invoices/sec).
  - Multi-tier matching (`EXACT_MATCH`, `TOLERANCE_MATCH` $\pm ₹1$, `VALUE_MISMATCH`, `IN_BOOKS_ONLY`, `IN_2B_ONLY`).
  - Section 17(5) Blocked Credit identification $\to$ Table 4(B)(1) permanent reversal.
  - Rule 37 (180-day non-payment) tracking $\to$ Table 4(B)(2) temporary reversal.
  - Supports CDNR credit notes, ISD distributions, and ICEGATE `impg` imports.
- **Multi-Page PDF & Invoice Vision Ingestion:**
  - Uses **`PyMuPDF`** (`pymupdf` C engine) to split and rasterize multi-page PDF bills into structured `work/images/<doc_name>/page_001.png` images for multimodal AI vision reading, featuring smart auto-detection (digital text parsing vs scanned photocopy vision routing) and `--force-image` mode.

- **Rule 88A / Section 49 Linear Optimization Solver:**
  - Optimally exhausts IGST credit first, then apportions across CGST and SGST to strictly eliminate stranded credits and minimize net cash outflow.
  - Enforces Section 49(4): Inward RCM liability (Table 3.1(d)) is strictly **100% Cash**.
  - Electronic Cash Ledger offsetting and exact **Challan PMT-06** deposit computation.
- **Statutory Interest & Late Fee Engine:**
  - Section 50 daily interest @ 18% p.a. calculated strictly on **Net Cash Liability**.
  - Section 47 late fee per day with turnover-based statutory caps.
- **DRC-01B & DRC-01C Pre-Emptive Risk Radar:**
  - Real-time detection of Rule 88C (liability mismatch) and Rule 88D (ITC mismatch) threshold deviations before filing.
- **Agentic Statutory Compliance Radar:**
  - Live discovery (`scripts/discover_statutory_rules.py`) and self-updating rule engine (`scripts/compliance_radar.py`) with staged testing and automated rollback.
- **Printable Certified CA Statements:**
  - Generates audit-ready PDF computation statements via **`jinja2`** and **`weasyprint`**.

---

## Quick Start with `uv`

### 1. Installation & Environment Setup
```bash
# Clone the repository
git clone https://github.com/quantavil/gstr-wala.git
cd gstr-wala

# Setup virtual environment and install with uv
uv venv
uv pip install -e ".[all]"
```

### 2. Run Complete Test Suite
```bash
uv run pytest -v
```

---

## CLI Usage

### 1. Run Complete End-to-End Filing Pipeline
```bash
uv run python3 scripts/cli.py pipeline \
  --sales examples/sample_sales_register.json \
  --purchases examples/sample_purchase_register.json \
  --gstr2b examples/sample_gstr2b.json \
  --output-dir output
```

### 2. Batch Convert Multi-Page PDF Invoices to Images
```bash
uv run python3 scripts/cli.py ingest-pdf docs/invoices/ --output-dir work/images/ --dpi 200
```

### 3. Run GSTR-2B Reconciliation (Vectorized High-Speed)
```bash
uv run python3 scripts/cli.py reconcile examples/sample_purchase_register.json examples/sample_gstr2b.json --fast
```

### 4. Check Live Statutory Compliance Radar
```bash
uv run python3 scripts/discover_statutory_rules.py
```

---

## Directory Structure

```
gstr-wala/
├── SKILL.md                          # Master Agentic Skill for AI Assistants
├── AGENT.md                          # Repository guidelines and architectural invariants
├── README.md                         # Project documentation
├── pyproject.toml                    # UV / Pip build configuration
├── config/                           # Machine-readable statutory rules & thresholds
│   └── rules_manifest.json
├── schemas/                          # Canonical input and GSTN official offline schemas
│   ├── gstr1_input_schema.json
│   ├── gstr3b_input_schema.json
│   ├── gstr1_portal_schema.json
│   ├── gstr3b_portal_schema.json
│   └── gstr2b_schema.json
├── scripts/                          # Deterministic Python engines & parsers
│   ├── models.py                     # Pydantic v2 data models
│   ├── cli.py                        # Typer & Rich interactive CLI
│   ├── gst_engine.py                 # Outward calculation, Sec 50/47 math
│   ├── itc_optimizer.py              # Rule 88A linear solver
│   ├── reconcile_gstr2b.py           # GSTR-2B 2-way matcher
│   ├── reconcile_fast.py             # Polars + Calamine + RapidFuzz high-scale engine
│   ├── ingest_pdf_vision.py          # Multi-page PDF to image rasterizer
│   ├── bridge_gstr1_to_gstr3b.py     # Outward to 3B bridge & DRC risk scanner
│   ├── generate_gstr1_json.py        # Official GSTR-1 offline JSON serializer
│   ├── generate_gstr3b_json.py        # Official GSTR-3B offline JSON serializer
│   ├── generate_filing_pack.py       # CA Markdown filing pack generator
│   ├── generate_pdf_statement.py     # Jinja2 + WeasyPrint CA statement generator
│   ├── discover_statutory_rules.py   # Live statutory discovery radar
│   ├── compliance_radar.py           # Self-updating compliance engine
│   └── fuzz_gst_engine.py            # Invariant property fuzzer
├── tests/                            # 210 Pytest unit, property & fuzzer tests (100% pass)
│   ├── fixtures/                     # Authentic GSTN, ERPNext, and SME datasets
│   ├── test_business_scenarios.py
│   ├── test_official_gstn_compliance.py
│   ├── test_portal_generators.py
│   ├── test_cli_commands.py
│   ├── test_property_invariants.py
│   ├── test_fuzz_gst_engine.py
│   ├── test_ingest_pdf_vision.py
│   ├── test_reconcile_fast.py
│   ├── test_compliance_radar.py
│   ├── test_validate_gst_input.py
│   ├── test_gst_engine.py
│   ├── test_itc_optimizer.py
│   ├── test_models.py
│   ├── test_reconcile_gstr2b.py
│   └── test_bridge_gstr3b.py
├── references/                       # Comprehensive statutory field guides
│   ├── gstr1-table-guide.md
│   ├── gstr3b-table-guide.md
│   ├── itc-rules-and-setoff.md
│   ├── gstr2b-reconciliation-guide.md
│   ├── rates-and-hsn-rules.md
│   ├── interest-and-late-fees.md
│   ├── drc-mismatch-audit-guide.md
│   ├── portal-walkthrough.md
│   └── file-naming-standard.md

├── examples/                         # Real-world sample datasets & portal JSONs
│   ├── sample_sales_register.json
│   ├── sample_purchase_register.json
│   ├── sample_gstr2b.json
│   ├── sample_gstr1_portal.json
│   └── sample_gstr3b_portal.json
└── workspace_template/               # User session runtime workspace template
    ├── docs/
    ├── work/
    ├── output/
    └── .gitignore
```

---

## License

GNU General Public License v3.0 (GPLv3). Designed with ❤️ for Indian businesses, chartered accountants, and tax developers.
