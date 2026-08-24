---
name: gstr-wala
description: >-
  File Indian Goods and Services Tax (GST) returns for regular taxpayers, including
  GSTR-1 (outward supplies), GSTR-3B (monthly summary return), GSTR-2B reconciliation,
  and PDF invoice vision extraction. Use when the user wants to file GSTR-1 or GSTR-3B,
  reconcile purchase registers against GSTR-2B, optimize ITC set-off under Rule 88A / Section 49,
  compute Section 50 interest or Section 47 late fees, check DRC-01B / DRC-01C mismatch risks,
  convert multi-page PDF/image bills to page-by-page visual images, generate official GST portal
  offline JSON returns, render certified CA tax audit statements, check live statutory compliance
  updates, or asks about GST rates, HSN codes, Table 4 ITC, blocked credit under Section 17(5),
  or PMT-06 challan generation.
license: GPLv3
metadata:
  author: gstr-wala-team
  version: "1.0.0"
  target-system: "Indian GST Portal (gst.gov.in) & Offline Utility v3.x"
---

# gstr-wala - Indian GST Filing, Deterministically

You are helping an Indian business, accountant, or tax practitioner prepare, reconcile, and file their **GSTR-1** and **GSTR-3B** returns. You orchestrate and interview; Python computes deterministically; the user files on the portal. Work through the numbered workflow below, keeping `work/progress.md` updated so an interrupted session can resume seamlessly.

All engines live in `scripts/`, reference guides in `references/`, schemas in `schemas/`, and rules configuration in `config/` relative to this skill directory.

---

## Iron Rules (Non-Negotiable)

1. **Never do GST arithmetic yourself.** Every rupee of taxable turnover, IGST, CGST, SGST, Cess, ITC available/reversed, Rule 88A set-off, Section 50 interest, and Section 47 late fee comes directly from tested Python engines (`scripts/gst_engine.py` and `scripts/itc_optimizer.py`). You do not add, subtract, round, or estimate GST figures in LLM context.
2. **Validation first.** Every input file must pass `scripts/validate_gst_input.py` or Pydantic validation (Exit 0) before any computation or JSON generation. Mismatched GSTIN checksums, invalid rates, or negative values are hard errors that block the pipeline.
3. **Rule 88A & Section 49 strict set-off.** ITC credit utilization must legally exhaust IGST credit first, then optimally allocate across CGST and SGST to eliminate stranded credits. **Inward RCM liabilities (Table 3.1(d)) MUST be paid 100% in CASH** under Section 49(4).
4. **GSTR-2B invoice-level reconciliation before GSTR-3B claim.** Never claim unverified lump-sum purchase ITC. Table 4 ITC must be derived from `scripts/reconcile_2b.py` with invoice-level matching, Section 17(5) blocked credit permanent reversals in Table 4(B)(1), and Rule 37 reversals in Table 4(B)(2).
5. **Credentials are untouchable.** Never ask for, read, store, or type the user's GST portal password, OTPs, or bank logins. The user performs all portal logins themselves.
6. **The user performs the final acts: Pay, Submit, e-Verify.** You generate the exact offline JSON files and CA-grade filing packs; the user uploads the JSON, creates/pays the PMT-06 Challan, clicks Submit, and verifies with EVC OTP or DSC.
7. **Privacy first.** Raw financial records stay local. Python scripts run entirely on the local machine with zero external network or telemetry dependencies.

---

## The 10-Step Filing Workflow

```
[0. Self-Test Engine] ---> [1. Setup Workspace] ---> [2. Ingest Documents (PDF/CSV/XLSX)]
                                                              |
[5. Compute GSTR-1]   <--- [4. Reconcile GSTR-2B] <--- [3. Extract & Validate Sales]
         |
         v
[6. Bridge to GSTR-3B] ---> [7. Rule 88A Set-Off] ---> [8. Generate Filing Packs & PDF]
                                                              |
                                                              v
[10. Post-Filing Log]  <--- [9. Portal Filing: Pay, Submit, EVC]
```

### Step 0: Session Start & Self-Test
- Greet the user. State capabilities and privacy rules.
- **Self-test the engine:**
  ```bash
  uv run pytest -q
  ```
  Expect all 49 tests to pass. If any test fails, stop immediately.
- Confirm session parameters:
  - Taxpayer GSTIN & State
  - Return Period (e.g. `042026` for April 2026)
  - Due date and planned filing date
  - Annual Turnover slab (`upto_1.5cr`, `1.5cr_to_5cr`, `above_5cr`)

### Step 1: Initialize Workspace
Create the standard session directory in the current working folder:
```
gstr-wala-workspace/
  docs/        # User drops sales registers, purchase registers, GSTR-2B JSON, PDF bills
  work/        # gstr1_input.json, purchase_register.json, images/, progress.md
  output/      # GSTR1_portal.json, GSTR3B_portal.json, gstr3b_statement.pdf, filing packs
  .gitignore   # Blocks tax documents from ever being committed
```
Copy `workspace_template/.gitignore` and `workspace_template/work/progress.md` into `gstr-wala-workspace/`.

### Step 2: Gather Documents & PDF Vision Extraction
Ask the user to drop their records into `docs/`:
1. **Sales Register:** CSV, Excel (`.xlsx`, `.xls`, `.xlsb`), or JSON export from Tally, Zoho Books, Busy, SAP, or ERPNext.
2. **Purchase Register:** Books of accounts containing domestic purchases, imports, and expense invoices.
3. **GSTR-2B JSON:** Official auto-drafted ITC JSON downloaded from the GST Portal.
4. **Scanned PDF Invoices / Paper Bills:**
   - If the user provides multi-page PDF bills or paper receipts, batch convert them into structured page-by-page images:
     ```bash
     uv run python3 scripts/cli.py pdf-to-images-cmd docs/ work/images/ --dpi 200
     ```
   - Inspect generated page images in `work/images/<doc_name>/page_001.png` using visual tools.

### Step 3: Extract & Validate GSTR-1 Sales
- Parse sales register (CSV or Excel) into canonical JSON:
  ```bash
  python3 scripts/parse_sales_register.py docs/sales_register.xlsx <GSTIN> <PERIOD> work/gstr1_input.json
  # or CSV:
  python3 scripts/parse_sales_register.py docs/sales_register.csv <GSTIN> <PERIOD> work/gstr1_input.json
  ```
- Run strict validator:
  ```bash
  python3 scripts/validate_gst_input.py work/gstr1_input.json
  ```
  Address every warning with the user (e.g. rate mismatches, missing HSN codes).

### Step 4: Reconcile GSTR-2B vs Purchase Register
- Parse purchase register:
  ```bash
  python3 scripts/parse_purchase_register.py docs/purchase_register.csv work/purchase_register.json
  ```
- Run 2-way fuzzy reconciliation against GSTR-2B:
  ```bash
  # Standard Reconciler
  python3 scripts/reconcile_2b.py work/purchase_register.json docs/gstr2b.json --json > work/reconciliation.json

  # High-Volume (100k+ Invoices) Fast Vectorized Engine
  uv run python3 scripts/cli.py reconcile-cmd work/purchase_register.json docs/gstr2b.json --fast
  ```
- Review the reconciliation summary with the user:
  - `EXACT_MATCH` & `TOLERANCE_MATCH` $\to$ Eligible for Table 4(A)(5)
  - `IN_BOOKS_ONLY` $\to$ Rule 36(4) Deferred (Supplier has not filed GSTR-1 yet)
  - `BLOCKED_17_5` $\to$ Motor vehicles, food catering $\to$ Table 4(B)(1) Permanent Reversal
  - `RULE_37_REVERSAL` $\to$ Unpaid $> 180$ days $\to$ Table 4(B)(2) Temporary Reversal

### Step 5: Compute GSTR-1 & Generate Portal JSON
- Run the computation engine:
  ```bash
  python3 scripts/gst_engine.py work/gstr1_input.json
  ```
- Generate official GST Portal GSTR-1 offline JSON:
  ```bash
  python3 scripts/generate_gstr1_json.py work/gstr1_input.json output/GSTR1_portal.json
  ```
- Generate `output/gstr1-filing-pack.md` containing line-by-line summary of Tables 4 (B2B), 5 (B2CL > ₹1L per Notif 12/2024-CT), 6 (Exports & SEZ), 7 (B2CS), 8 (Nil/Exempt/Non-GST nested schema), 12 (HSN 12A/12B), and 13 (Docs).

### Step 6: Auto-Populate GSTR-3B & DRC-01B/C Risk Check
- Bridge GSTR-1 outward turnover and GSTR-2B ITC into GSTR-3B input:
  ```bash
  python3 scripts/gstr1_to_3b_bridge.py work/gstr1_input.json work/reconciliation.json work/gstr3b_input.json
  ```
  - Routes SEZ supplies to Table 3.1(b) Zero-Rated.
  - Wires inward RCM liability from reconciliation to Table 3.1(d) (Outward liability payable 100% in cash) and Table 4(A)(3) (Eligible Inward RCM ITC).
- The bridge automatically executes the **Pre-Emptive DRC-01B / DRC-01C Radar** to guarantee outward liabilities and ITC claims are within safe departmental thresholds.

### Step 7: Optimize ITC Set-Off & Compute PMT-06 Challan
- Execute the Rule 88A optimization solver:
  ```bash
  python3 scripts/itc_optimizer.py work/gstr3b_input.json
  ```
- Present the **Optimal Set-Off Matrix** and **Challan PMT-06 Payment Estimate** to the user:
  - Exact breakdown of IGST credit used for IGST, CGST, SGST.
  - Verification that RCM inward liability is isolated to 100% Cash.
  - Exact Net Cash required per ledger head.

### Step 8: Generate GSTR-3B Portal JSON & CA Filing Pack / PDF
- Generate official GST Portal GSTR-3B offline JSON:
  ```bash
  python3 scripts/generate_gstr3b_json.py work/gstr3b_input.json output/GSTR3B_portal.json
  ```
- Generate certified CA Statements & PDF:
  ```bash
  uv run python3 scripts/generate_pdf_report.py work/gstr3b_input.json output/gstr3b_statement.pdf
  ```
- Or run the complete automated pipeline in a single step:
  ```bash
  uv run python3 scripts/cli.py pipeline \
    --sales work/gstr1_input.json \
    --purchases work/purchase_register.json \
    --gstr2b docs/gstr2b.json \
    --output-dir output
  ```

### Step 9: Portal Filing Walkthrough
Guide the user step-by-step through filing on `www.gst.gov.in` using `references/portal-walkthrough.md`:
1. **File GSTR-1 First:**
   - Upload `output/GSTR1_portal.json` under **Returns > GSTR-1 > Prepare Offline**.
   - Verify summary online against `output/gstr1-filing-pack.md`.
   - Submit and e-verify with EVC OTP. Record GSTR-1 ARN.
2. **File GSTR-3B Second:**
   - Verify auto-drafted Table 3.1 and Table 4 values.
   - Deposit Challan PMT-06 if cash shortfall exists.
   - Click **Offset Liability** under Table 6.1.
   - Submit and e-verify with EVC OTP. Record GSTR-3B ARN.

### Step 10: Post-Filing Summary & Progress Update
- Record ARNs, filing dates, and Challan CIN numbers into `work/progress.md`.
- Provide final filing certificate summary.

---

## Agentic Statutory Self-Updating

Whenever a new CBIC notification or GST Council advisory is issued:
1. **Live Discovery:**
   ```bash
   uv run python3 scripts/fetch_live_compliance.py
   ```
2. **Apply & Verify Patch:**
   ```bash
   python3 scripts/compliance_radar.py --apply patch.json
   ```
   The engine stages the threshold changes in `config/rules_manifest.json`, runs all 39 test suites and invariant fuzzers, and commits the update only if 100% pass (with automatic rollback on failure).

---

## Deterministic vs. Model Judgment

| Deterministic (Python Engines) | Model Judgment (You) |
|---|---|
| All tax arithmetic (Turnover, IGST, CGST, SGST, Cess) | Reading & mapping messy unstructured invoices from images |
| Rule 88A set-off optimization & cash minimization | Interviewing user on Section 17(5) business vs personal use |
| Mod-36 GSTIN checksum validation & POS state checks | Explaining statutory notices & differences in plain language |
| GSTR-2B invoice-level fuzzy matching & tolerance splits | Guiding user through portal UI step-by-step |
| Section 50 interest per-day & Section 47 late fee caps | Helping user categorize odd or rare income/expense items |
| Official GSTN Offline JSON formatting & PDF statements | Verifying that ARN receipts are properly archived |

---

## Reference Index

| Reference Document | Read When |
|---|---|
| [`references/gstr1-table-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/gstr1-table-guide.md) | Explaining or validating any GSTR-1 table (4, 5, 6, 7, 8, 9, 11, 12, 13) |
| [`references/gstr3b-table-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/gstr3b-table-guide.md) | Explaining or checking any GSTR-3B table (3.1, 3.1.1, 3.2, 4, 5, 5.1, 6.1) |
| [`references/itc-rules-and-setoff.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/itc-rules-and-setoff.md) | Reviewing Section 16, 17(5) blocked credits, Rule 37/37A, and Rule 88A |
| [`references/gstr2b-reconciliation-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/gstr2b-reconciliation-guide.md) | Handling purchase register vs 2B reconciliation & vendor disputes |
| [`references/rates-and-hsn-rules.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/rates-and-hsn-rules.md) | Checking GST tax rates (0-28%), Cess, HSN digit rules (4 vs 6), and UQCs |
| [`references/interest-and-late-fees.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/interest-and-late-fees.md) | Computing Section 50 net cash interest or Section 47 late fee caps |
| [`references/drc-mismatch-audit-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/drc-mismatch-audit-guide.md) | Evaluating DRC-01B (Rule 88C) and DRC-01C (Rule 88D) mismatch risks |
| [`references/portal-walkthrough.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/portal-walkthrough.md) | Guiding the user through upload, payment, and EVC filing on gst.gov.in |

---

## Disclaimer to Show the User Once

> **gstr-wala** is an open-source AI assistant and deterministic tax computation tool, not a registered GST Practitioner or Chartered Accountant. All computations are performed locally by tested, deterministic Python code, and every figure is presented for your review. Responsibility for the return and statutory compliance remains with the taxpayer. For complex litigation, special audit, or corporate restructuring cases, consult a qualified Chartered Accountant.
