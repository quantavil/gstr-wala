# gstr-wala Audit — Vetted Findings

> Date: 2026-08-25 · Scope: full repo audit (correctness, security, performance, tests, tech debt, dependency risk, DX, docs, direction). No source code was modified in this pass.
>
> **STATUS (2026-08-25): REMEDIATED.** All 15 findings closed across two remediation rounds (external AI pass + review/closure round). Final gates: **210 passed · ruff clean · mypy clean**. Residual notes: #10 resolved via honesty fix (version tags overridable; official GSTN token unverified by design — see AGENT.md blunder log); scale-benchmark timing bound loosened to a CI-stable smoke assertion.

## RECON (verified, not guessed)

- **Stack:** Python ≥3.12, pydantic v2, typer/rich, polars, rapidfuzz, python-calamine, jinja2, pillow, pymupdf, jsonschema; setuptools; `uv.lock`
- **Gates:** `uv run pytest -q` · `.venv/bin/python -m ruff check` · `.venv/bin/python -m mypy scripts/` (from `pyproject.toml:55-78` + `AUDIT_REMEDIATION_PLAN.md` §0.2). **No Makefile, no CI** (`.github/` absent)
- **Live gate results:** pytest **198 passed** / coverage 77% · mypy clean · ruff **90 errors**

## Findings table (ranked by impact/effort × confidence)

| # | Category | Finding | Evidence | Impact | Effort | Conf |
|---|---|---|---|---|---|---|
| 1 | Correctness | Sec 50 interest & Sec 47 late-fee engines are never wired into the pipeline — only tests call them; bridge never emits `interest_details`/`late_fee_details`, so a late filer's challan is computed at ₹0 interest | `gst_engine.py:298-398` (defn); grep: callers only in `tests/`; probe confirmed bridge output lacks both keys; `itc_optimizer.py:151` reads them from input that's never populated | Late filers underpay → statutory dues + notice risk | M | HIGH |
| 2 | Correctness | Portal `tx_pmt.paid_cash` conflates tax + interest + late fee: `req_cash_*` includes `intr_*`/late fee, then generator emits it as cash-paid-per-tax-head (probe: liability ₹18,000 but `paid_cash.iamt` = ₹19,000) | `itc_optimizer.py:190-193` → `generate_gstr3b_json.py:212-217, 228-233` | Misstated Table 6.1 on portal upload | S-M | HIGH |
| 3 | Correctness | Blocked-credit HSN list divergence: reconcile hardcodes `{8702,8703,9963,9965}`, dropping `8704,9966,9967` from the canonical `BLOCKED_HSNS` — trucks/services blocked credit flows to eligible ITC | `constants.py:49` vs `reconcile_gstr2b.py:505-507` | Wrong ITC claims for affected HSNs | S | HIGH |
| 4 | Docs/DX | Test-count drift: docs say "62 tests"; actual suite is **198 passed**. SKILL.md Step 0 tells the agent to *stop* if counts don't match expectations | `README.md:3` badge, `SKILL.md:62`, `SKILL.md:211`, `AGENT.md:44` | Agents/users misread self-test gate as failure | S | HIGH |
| 5 | Tech debt/DX | Lint gate is red: `ruff check scripts/ tests/` = 90 findings (61 auto-fixable: F401 unused imports ×17, UP006/I001, BLE001 ×6...), and no `[tool.ruff]` section exists to pin an intended ruleset — while AUDIT_REMEDIATION_PLAN names ruff as a pass/fail gate | ruff output (see Appendix A); grep confirms no ruff config anywhere | Gate can't be green; noise hides real issues | S | HIGH |
| 6 | Correctness | Two rounding regimes coexist: parsers derive taxes with banker's `round()` while the repo contract is Decimal HALF_UP (`round_cur`). Probe: ₹0.25 @18% → derive gives 0.04, round_cur gives 0.05. Also `val` accumulation uses `round()` | `parse_sales_register.py:169-172`, `:220` vs `utils.py:11-21` | 1-paisa drift vs statutory rounding on .5p boundaries | S | HIGH |
| 7 | Correctness/DX | Section 16(4) gating is wall-clock nondeterministic: falls back to `datetime.now(UTC)`, and CLI `main()` never passes `_16_4_cutoff`, so the same recon JSON is classified differently across days — contradicts the "deterministic engine" promise and breaks reproducible audit trail | `reconcile_gstr2b.py:73-75`, `:900`; `models.GSTR3BInput` has no cutoff field either | Non-reproducible filings; untestable edge | M | MED-HIGH |
| 8 | Direction/correctness | Value-mismatch ITC is auto-claimed into Table 4(A)(5) via per-head `min(books, 2B)` without user sign-off — in tension with SKILL.md iron rule #4 ("never claim unverified"). Probe confirmed a mismatch invoice's ₹1,620 landed in T4A5 | `reconcile_gstr2b.py:763-766` | Conservative min() mitigates; still silent claiming of flagged rows | S-M | MED |
| 9 | DX | Bridge CLI positional sniffing breaks the 2-arg form: pre-existing output file lacking "3b" in its name gets classified as the recon file → raw JSONDecodeError traceback, output never written (probed live) | `bridge_gstr1_to_gstr3b.py:341-347` | Confusing crash for scripted use | S | HIGH |
| 10 | Direction/docs | "Official GSTN offline JSON / v3.x compliant" claim is overstated: version tokens are `"gstr-wala-gstr1-1.0"` / `"gstr-wala-gstr3b-1.0"`, schemas are self-authored & loose (`required` = version/gstin/fp), generated HSN rows omit mandatory `rt` (probed) | `generate_gstr1_json.py:276`, `generate_gstr3b_json.py:240`, `schemas/gstr1_portal_schema.json` | Users may expect direct portal upload acceptance | L | HIGH (on discrepancy; portal acceptance unverifiable offline) |
| 11 | Correctness | POS normalization inconsistent across layers: validator rejects `"7"`, pydantic `min_length=2` blocks its zfill validator (dead path), engine accepts via `zfill(2)` — numeric POS from ERP exports fails validation but would compute fine | `validate_gst_input.py:133`, `models.py:145+157-162`, `gst_engine.py:86` | Spurious validation failures | S | HIGH |
| 12 | Redundancy | Dead code & shim duplication: unused `Decimal` import (`itc_optimizer.py:19`), no-op `if intr_cs == 0: intr_cs = 0.0` (`:180-181`), `format_table` re-export shims duplicated in `itc_optimizer.py:344-347` and `reconcile_gstr2b.py:869-872`, interest fallback dumps entire amount on IGST when no cash tax (`:182-183`) | as cited | Maintenance drag only | S | HIGH |
| 13 | Tech debt | Manifest freshness split-brain: `B2CL_THRESHOLD`/DRC frozen at import time (`constants.py:31-48`) while `get_interest_rate_50_1()`/`get_late_fee_caps()` re-read per call (`:116-135`) — a compliance patch updates some rules immediately, others next process | `constants.py:31-48` vs `:116-135` | Post-patch inconsistency window | S | MED |
| 14 | DX/process | No CI despite three defined gates; ruff being red (#5) proves nothing enforces them | absence of `.github/workflows/` | Regressions land silently | S | HIGH |
| 15 | Robustness | `compliance_radar.run_self_verification()` inherits pyproject `addopts --cov` (pytest-cov is a dev extra); in a runtime env without dev extras, pytest exits with "unrecognized arguments" → every valid patch "fails" and rolls back | `compliance_radar.py:73-84`, `pyproject.toml:58`, `:36-42` | Patch pipeline bricked outside dev envs | S | LOW-MED |


## Security note

No secrets/credentials found anywhere in tracked files (verified via `git ls-files` + recursive key scans in validator). Nothing to rotate.

---

## Appendix A — Ruff breakdown (90 findings, ruff 0.16.4)

```
21 UP006   non-pep585-annotation          [*] fixable
17 F401    unused-import                  [*]
14 I001    unsorted-imports               [*]
11 UP035   deprecated-import
 6 BLE001  blind-except
 6 EXE001  shebang-not-executable
 4 PLR1730 if-stmt-min-max                [*]
 4 UP045   non-pep604-annotation-optional [*]
 1 C414    unnecessary-double-cast-or-process
 1 F541    f-string-missing-placeholders  [*]
 1 F841    unused-variable
 1 PLR0124 comparison-with-itself
 1 RUF046  unnecessary-cast-to-int
 1 RUF059  unused-unpacked-variable
 1 S110    try-except-pass
```
Note: `PLR0124 comparison-with-itself` flags `v != v` NaN checks in `utils.py` — intentional, exclude from any autofix sweep.

## Appendix B — Verification probes used during vetting

| Probe | Result |
|---|---|
| derive_taxes vs round_cur on ₹0.25 @18% | 0.04 vs 0.05 — regimes diverge (#6) |
| Validator vs engine on `pos="7"` | validator errors; pydantic blocks at min_length; engine zfills and accepts (#11) |
| `BLOCKED_HSNS − hardcoded list` | `{8704, 9966, 9967}` missing in reconcile (#3) |
| Optimizer with interest ₹1,000 + tax ₹18,000, no credit | `net_cash_required.iamt` = 19,000; portal `paid_cash.iamt` = 19,000 vs liability 18,000 (#2) |
| Bridge CLI 2-arg form with pre-existing `out.json` | Raw traceback; output never written (#9) |
| Generated GSTR-1 HSN row keys | No `rt` key (#10) |
| Bridge output keys | No `interest_details` / `late_fee_details` (#1) |
| Value-mismatch invoice through reconcile | T4A5 claims min(books, 2B) = 1,620 (#8) |
| GSTIN checksum on valid sample | Passes — function correct |

## Next step

Pick finding numbers from the table above; each will get ONE self-contained plan doc (current-state excerpt, exact steps, verified test/lint gates, out-of-scope list, stop conditions). No code until then.
