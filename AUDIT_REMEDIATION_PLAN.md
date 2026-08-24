# AUDIT REMEDIATION PLAN — Tasks 2–5 (Handoff for Implementing AI)

> **Audience:** an autonomous coding agent implementing these tasks. Another AI (the **Judge**) will review every commit: spec compliance first, then code quality, then live probes. Write accordingly.
>
> **Status of this document:** authoritative. Where it conflicts with older audit reports or chat history, THIS file wins.

---

## 0. GROUND RULES (non-negotiable)

1. **Branch:** `fix/audit-truthfulness`. Never commit to `main`. Baseline: commit `bc3fdfb`, **148 tests passing**.
2. **Venv / commands** (repo root `/home/quantavil/Documents/Project/gstr-wala`):
   - Tests: `.venv/bin/python -m pytest -q`
   - Lint delta check: `.venv/bin/python -m ruff check <files-you-touched>`
   - Live probes: `.venv/bin/python - <<'EOF' ... EOF` style snippets
3. **TDD mandatory**: failing test → implementation → green. Every numbered requirement below needs at least one test that would fail without your change.
4. **Sequential tasks, one commit per task**, exact commit messages given per task. Do NOT start Task N+1 before Task N is committed.
5. **File allowlists are hard limits.** If you believe a change outside the allowlist is required, STOP and report `BLOCKED` with reasoning instead of touching it.
6. **Truthfulness principle** (this project's core rule): a statutory figure must never be silently defaulted, clamped, fabricated, or zeroed on bad input. Fail loudly (`ValueError` naming row/field/alias) or emit an explicit error flag in output. Silence is a bug.
7. **Do not re-litigate adjudicated findings** (§1). Two independent audits + primary-source verification settled them.

## 1. ADJUDICATED FINDINGS — read before writing any line

| Finding | Verdict | What YOU must do |
|---|---|---|
| "Services must NOT go to B2CL" | **FALSE POSITIVE.** Notif. 12/2024-CT covers *goods or services or both*; repo doc `references/gstr1-table-guide.md:30` agrees | Do **NOT** add any SAC-prefix gate to B2CL classification. Instead ADD a regression test pinning current behavior: interstate B2C service invoice (HSN 99xxxx) > ₹1L invoice value → lands in `table_5_b2cl` |
| "B2CL effective date should be Nov 2024 not Aug 2024" | **FALSE POSITIVE.** Notif. 12/2024-CT dated 10-Jul-2024, effective 01-Aug-2024 | Leave `config/rules_manifest.json` date and `constants.py` untouched on this point |
| "Rule 37 reversal must be proportional" | **LAW: yes; PRACTICE: registers lack payment splits** | Keep full-reversal as DEFAULT; add opt-in `unpaid_value` field for proportional math (Task 2 §2.3). Never make proportionality mandatory |
| "ICEGATE ctin breaks import matching" | **MOSTLY FALSE.** Flattener maps `inum ← boenum`; BOE-numbered register rows match fine | Narrow scope (Task 2 §2.5): preserve `IMPGSEZ` section label only. No new matching machinery |
| Parser quality 4/10 | Outdated snapshot | Ignore. Current state post-`bc3fdfb` |

## 2. SHARED CONTEXT — helpers that already exist (reuse, don't reinvent)

From Task 1 (`scripts/utils.py`, all tested):
- `safe_float(val, default=0.0)` — lenient; handles `(1,234.56)` negatives, ₹/Rs./INR symbols, Indian grouping; rejects European format
- `safe_float_strict(val)` — raises ValueError on garbage. **Use for required money fields at parse boundaries**
- `excel_cell_to_str(v)` — kills Excel `.0` poisoning; datetime→`DD-MM-YYYY`
- `normalize_date_str(raw, context="")` — accepts DD-MM-YYYY / DD/MM/YYYY / YYYY-MM-DD; calendar-invalid raises; canonical `DD-MM-YYYY` out

Known gotchas learned the hard way:
- `isinstance(True, int)` is True in Python — exclude bools explicitly from numeric checks
- Under pytest, `sys.exit("msg")` does NOT print; assert via `pytest.raises(SystemExit)` + `ei.value.code`
- CSV files need `utf-8-sig` (BOM), CRLF tolerance
- Parser tax-column pattern to mirror: file-level `tax_alias_present` flag distinguishes absent columns (raise/opt-in derive) vs present-but-zero cells (warn, respect zeros)

---

## TASK 2 — Reconciliation statutory truth

**Files allowed:** `scripts/reconcile_gstr2b.py`, `tests/test_reconcile_gstr2b.py`, `tests/test_business_scenarios.py` (only if fixed RCM routing changes expectations — verify scenario numbers still make statutory sense first), NEW `tests/test_recon_truth.py`.
**Forbidden:** `reconcile_fast.py`, `gst_engine.py`, parsers, generators, `utils.py`.
**Read first:** `references/gstr2b-reconciliation-guide.md`, `references/itc-rules-and-setoff.md`, `references/drc-mismatch-audit-guide.md`.

### 2.1 Amended documents (CRITICAL)
`flatten_gstr2b()` (~lines 33–189) parses only `b2b/cdnr/isd/impg/impgsez`. Add:
- `b2ba` (amended B2B), `cdna` (amended CDN), `isda` (amended ISD), `isdc` if present in JSON shape
- Amendment supersedes original **for the period**: amended entries carry the original number under `oinum` (invoices) / `ont_num` (notes). When an amendment exists, drop the original record so nothing double-counts
- CDNA uses ntty C/D sign logic identical to CDNR
- Output records get `"section": "B2BA"/"CDNA"/"ISDA"` respectively (provenance preserved end-to-end)

### 2.2 RCM routing fix (CRITICAL)
Current bug (~lines 305–313): inside `rchrg == "Y"` branch, `itcavl == "N"` diverts portal-realistic RCM rows (GSTR-2B presents inward RCM as `rev=Y, itcavl=N`) into ineligible 4(D)(2).
Required:
- `rchrg=="Y"` → Table 4(A)(3) RCM inward **regardless of `itcavl`**
- `itcavl in ("N","RS")` routes to 4(D)(2) **only for non-RCM rows**
- Each 4(A)(3) entry gets `"itc_note": "claimable_only_after_rcm_cash_payment"` (Sec 16 read w/ Sec 41)
- Regression pair: `(rev=Y,itcavl=N,RCHRG=Y)` → 4(A)(3); `(RCHRG=N,itcavl=N)` → 4(D)(2)

### 2.3 Rule 37 proportional reversal
Second proviso to Sec 16(2)(a) read with Rule 37(1): reversal limited to unpaid portion.
- Purchase-register rows may carry optional numeric `unpaid_value`
- When present: `ratio = min(1.0, unpaid_value / (invoice_value + total_tax))`; reverse each head × ratio; entry gets `"reversal_basis": "proportional"`
- When absent: current full reversal; `"reversal_basis": "full_unpaid_assumed"`
- Test vectors: val=100000, tax=18000, unpaid=59000 → ratio 0.5 exactly; unpaid > invoice+tax → capped at 1.0; unpaid=0 → no reversal entry needed (paid in time path)

### 2.4 Tolerance = single axis
Guide §2: TOLERANCE_MATCH ⇔ tax diff ≤ ₹1 (rounding). Remove the extra `diff_txval <= 2.0` conjunct (~line 330). Report `txval_diff` informationally on every matched entry. Update printed header text to "(tax within ±₹1)". Document in test docstring that huge txval diff + ₹0.50 tax diff classifies TOLERANCE by design (per guide).

### 2.5 IMPGSEZ label preservation (narrow!)
~Line 174: stop merging `impgsez` under `"section": "IMPG"`. Emit `"section": "IMPGSEZ"` for those rows (keep `ctin: "ICEGATE"` synthetic key and `inum ← boenum` mapping EXACTLY as-is — they work). Nothing more.

### 2.6 Sec 16(4) time limit gate
- For books-side invoices, parse `idt` via `normalize_date_str`; ITC deadline = Nov 30 following the FY end of invoice date
- Expired → ineligible bucket (4(D)(2)-style) with `"reason": "16(4)_time_limit"`
- Injectability: function signature gains `_16_4_cutoff: Optional[str] = None` param (ISO date); when None compute from today. All tests use injected cutoffs — no flaky time-dependent tests
- Books-side only; portal 2B rows are never gated (portal echo)

### 2.7 Crash-proofing
Replace remaining raw `float(...)` reads on portal JSON (~lines 47, 95 and any others you find via `grep -n "float(" scripts/reconcile_gstr2b.py`) with `utils.safe_float`.

### Acceptance & verification
- New `tests/test_recon_truth.py`: b2ba supersedes b2b (counts don't double); cdna reduces gross ITC; both §2.2 regression rows; §2.3 vector set; §2.4 single-axis case; §2.6 expired-vs-live with two injected cutoffs; IMPGSEZ label assertion
- Full suite green. Existing `test_reconcile_gstr2b.py` may be updated where it codified old bugs — call out each edit
- Commit: `fix(recon): amended docs supersede originals, RCM→4(A)(3), proportional Rule 37, single-axis tolerance, 16(4) gate`

---

## TASK 3 — Fast engine honesty

**Files allowed:** `scripts/reconcile_fast.py`, `tests/test_reconcile_fast.py`, NEW tests inside existing file or `test_fast_engine_honesty.py`.
**Forbidden:** everything else.

### 3.1 Fuzzy tier value gate (CRITICAL — the #1 finding of the whole audit)
Reproduced defect: books ₹13.73 tax fuzzy-matched 2B ₹1,78,200 tax (score 85.7) → reported `missing_in_2b_count: 0`. The fuzzy block (~lines 141–158) records `tax_diff` but never gates on it.
Required:
- After `extractOne`, accept the match ONLY if `tax_diff <= max(2.0, 0.01 * max(book_tax, g2b_tax))` (i.e., ₹2 absolute OR 1% relative, whichever is larger)
- Rejected near-misses go to NEW bucket `"value_mismatch"` (books side) with fields: book record, best candidate, score, tax_diff. They are NOT matches and NOT missing_in_2b
- Add `value_mismatch_count` to summary dict
- Regression test = the exact repro above (INV07770/INV777X pair): must now land in value_mismatch, counts honest

### 3.2 Deterministic tie-breaking
`extractOne` returns first-max in candidate order → permutation-dependent selection. Replace with explicit selection: iterate candidates, keep best by tuple `(score DESC, tax_diff ASC, g2b_id ASC)`. Test: two equal-score candidates, reversed input order → same winner.

### 3.3 Loud parity warning
Fast engine performs NO 17(5)/Rule 37/4(D)(2)/RCM routing while loading those columns dead (~lines 77–78, 96–97).
Required: result dict gains `"classification_performed": false` plus `"parity_warning": "fast engine skips 17(5)/Rule 37/RCM/16(4) classification — run slow engine for filing decisions"` string constant printed by whoever consumes it. Delete the four dead DataFrame columns OR wire them into the value_mismatch gate — do not leave them loaded-but-unused.

### 3.4 Robustness parity
- Route all row coercion through `safe_float` (raw `float("1,800.00")` currently crashes ~lines 71–78, 90–97)
- Duplicate-header / blank-header detection in calamine reader: raise ValueError listing offending column names instead of silent last-win/drop

### Acceptance & verification
- Full suite green; new tests cover §§3.1–3.4
- `.venv/bin/python - <<EOF` probe reproducing the audit repro must show `value_mismatch_count: 1, missing_in_2b_count: 0`... actually correct final expectation: books row lands in `value_mismatch`, so `missing_in_2b_count: 0` ONLY because it's categorized as mismatch — ensure summary semantics state that explicitly (`missing_in_2b_count` excludes mismatches; document in docstring)
- Commit: `fix(fast-engine): value-gated fuzzy matching, deterministic ties, loud parity warning`

---

## TASK 4 — Core engine truth (AMENDED SCOPE)

**Files allowed:** `scripts/gst_engine.py`, `scripts/models.py`, `scripts/validate_gst_input.py`, `scripts/constants.py`, `tests/test_gst_engine.py`, `tests/test_models.py`, `tests/test_validate_gst_input.py`, NEW `tests/test_engine_truth.py`.
**Forbidden:** generators, cli, radar, reconcile_*.

### 4.1 Malformed dates never produce ₹0 statutory amounts (CRITICAL)
`gst_engine.parse_date` (~41–44) returns None on failure → interest/late fee silently 0 (verified: ₹1L liability 30 days late → ₹0.00 with slash-date).
Required:
- `parse_date(dt_str)`: `None`/empty input → returns None (legally absent). Present-but-malformed → `raise ValueError` naming the value
- `compute_statutory_interest` / `compute_statutory_late_fee`: let the error propagate. Docstrings updated: "malformed dates raise; absent dates return zero-delay result"
- CLI-facing callers are out of your allowlist — export clean exceptions; integration happens in Task 5
- Tests: slash-date raises; empty-string → zero-delay result; valid pair still computes ₹739.73 for (100000, 15d) @18%/365

### 4.2 One dispatch function everywhere
Three divergent payload-type heuristics exist: `gst_engine.compute` (~333, 3B-first), `validate_gst_input` dispatcher (~347, GSTR1-first), `cli.validate` (~154, invoices-only) — last one out of allowlist, but build the shared primitive so Task 5 plugs it in.
Required:
- New `detect_return_type(data: dict) -> str` returning `"GSTR-1"|"GSTR-3B"`, living in `scripts/constants.py`
- Logic: explicit top-level `"return_type"` wins (case-insensitive, validate ∈ {GSTR-1, GSTR-3B}); else infer: has `invoices`+`fp` → GSTR-1; has `ret_period`+`outward_supplies` → GSTR-3B; BOTH key-sets present → `ValueError("ambiguous payload: contains both GSTR-1 and GSTR-3B keys; set return_type explicitly")`; NEITHER → ValueError
- Engine + validator dispatchers both call it. Regression: dual-keyset payload now raises in BOTH entry points (was: validated-as-GSTR1/computed-as-GSTR3B)

### 4.3 CDNR nets into summary totals (kill overstated liability)
Engine summary (~223–241) sums invoice items only; credit/debit notes are passthrough → liability overstated by full note amount.
Required: summary computation subtracts credit notes (ntty=C) and adds debit notes (ntty=D) item-wise per head (txval/iamt/camt/samt/csamt). Advances (Table 11A received minus 11B adjusted) also net into summary. Keep raw passthrough tables unchanged. Test: one ₹50k taxable/₹9k CGST+SGST invoice + ₹10k/₹1.8k credit note → summary reflects net.

### 4.4 Model validation hardening (pydantic layer stops lying)
`models.py`:
- `pos`: add field_validator → must be in `STATE_CODES` (import from constants)
- `ctin` (when present): regex + checksum via THE shared validator (§4.5)
- `idt`: after DATE_REGEX, calendar-validate via `datetime.strptime` (31-02-2026 must fail)
- `due_date`/`filing_date` (GSTR3BInput): DATE_REGEX + calendar validation when present
- Deduplicate the two copy-pasted GSTIN validators (~169–181 vs ~207–219) into one shared `Annotated` type

### 4.5 Single GSTIN checksum source
`models._compute_gstin_checksum` ≡ `validate_gst_input.compute_gstin_checksum` (verbatim dup). Move ONE implementation to `scripts/constants.py` (beside CHAR_SET); both modules import it. `validate_gst_input.is_valid_gstin` stays the public API (re-export ok). Guard: non-charset char raises domain ValueError with the char named (not bare `'x' is not in list`).

### 4.6 Manifest-driven interest & late fee (single source of truth — fixes radar lie)
Currently hardcoded at gst_engine ~259/278 (0.18) and ~301–313 (late fee schedule) while manifest declares them → compliance-radar patches silently no-op.
Required:
- `constants.py`: expose `get_interest_rate_50_1() -> float`, `get_late_fee_caps() -> dict` reading from `rules_manifest.json` via existing loader
- Fix loader silent-fallback (~12–15): on corrupt/unreadable manifest → `warnings.warn` loudly AND fall back to embedded defaults (do NOT crash imports; do NOT stay silent)
- Engine consumes these accessors (delete hardcoded literals). Values identical (0.18, ₹20/₹500 nil, ₹50/day slabs ₹2000/₹5000/₹10000 caps per Notif 11/2020-CT) so all existing numeric assertions hold
- Note: `section_50_3_wrong_avail_utilized_p_a` stays DECLARED-BUT-UNUSED; add module docstring line in constants stating it is not yet implemented anywhere (honesty marker, prevents future "single source" confusion)

### 4.7 Dead-code removal (engine)
- Delete wrapper trio `safe_float`/`round_cur` re-exports (~34–48) and function-local-import `format_table` (~372–375) — import utils symbols directly at top
- Remove unused `from decimal import Decimal, ROUND_HALF_UP` (~20)
- Collapse byte-duplicated 3B extraction blocks (~335–369) into one helper; the neither-keygroup fallback must RAISE (via detect_return_type) instead of fabricating all-zero 3B
- Human-mode output for GSTR-3B (~397): print a compact 3B summary table instead of silence

### 4.8 Explicitly OUT OF SCOPE (do not touch)
SAC/B2CL classification (correct as-is — see §1); float→Decimal migration (future work); `turnover_slab` default semantics; Sec 50(3)/Rule 88B implementation (declared-unimplemented marker only); B2CL threshold/date values.

### Acceptance & verification
- Full suite green; new `tests/test_engine_truth.py` covers §§4.1–4.6 regressions incl. dual-payload ambiguity raise and services→B2CL pin from §1
- `grep -n "0.18\|def safe_float\|def round_cur" scripts/gst_engine.py` shows rate literals gone from engine (moved behind accessors)
- mypy `scripts` error count must not increase (baseline 7, all in compliance_radar)
- Commit: `fix(engine): loud date errors, unified dispatch, CDNR netting, model hardening, manifest-driven rates`

---

## TASK 5 — Pipeline truth & artifact enforcement

**Files allowed:** `scripts/generate_gstr1_json.py`, `scripts/generate_gstr3b_json.py`, `scripts/bridge_gstr1_to_gstr3b.py`, `scripts/cli.py`, `scripts/generate_pdf_statement.py`, `scripts/generate_filing_pack.py`, `scripts/compliance_radar.py`, `scripts/discover_statutory_rules.py`, `schemas/*.json`, `pyproject.toml`, relevant tests (`test_portal_generators.py`, `test_cli_commands.py`, `test_bridge_gstr3b.py`, `test_compliance_radar.py`), NEW `tests/test_pipeline_truth.py`.
**Forbidden:** engines/parsers (Tasks 2–4 territory).

### 5.1 Schema enforcement becomes real (kills "canonical schemas" lie)
- Add `"jsonschema>=4.21"` to `[project.dependencies]` in pyproject.toml
- FIX schemas to match generator reality (currently example violates schema): in `schemas/gstr3b_portal_schema.json`, IMPG/IMPS `itc_avl` rows must NOT require camt/samt (imports have no CGST/SGST)
- Both schemas gain root `"version"`: generator emits `"version": "gstr-wala-gstr1-1.0"` / `"gstr-wala-gstr3b-1.0"` (clearly OUR internal label — do NOT fake GSTN version strings); schemas require it
- New module-level function `validate_against_schema(payload, schema_path) -> list[str]` (errors, not throw) in generate_filing_pack.py or a small new helper inside allowed files
- `cli.pipeline` step 6 validates both generated portal JSONs; on errors prints them and exits 1. Test: pipeline artifacts pass validation; deliberately-broken payload fails with listed errors

### 5.2 PDF statement honesty
- Hardcoded legal fallbacks (~241–242 `"20-05-2026"`) removed → render `"—"` when due/filing date absent
- `os.makedirs(os.path.dirname(p) or ".")` guard (~273) so bare filenames work
- `generate_pdf` failure returns False already; `cli.pipeline` (~127–143) must honor it: PDF row appears in summary table ONLY if returned True; print visible warning otherwise
- Rename summary-table label "CA Signed PDF Statement" → "PDF Statement" (nothing is signed — false advertising)

### 5.3 Bridge/CLI honesty
- bridge main() (~329): replace argv-sniffing hack with argparse (positional g1_input, optional recon, positional output). Delete the `!= "output_3b.json"` heuristic
- bridge main() print bug (~346): `Total ITC: ₹{dict}` → formatted sum of available heads
- `cli.validate` (~154) and `cli.reconcile --fast` (~186): use `detect_return_type` from Task 4 for validate; fast path prints JSON (json.dumps) not raw dict repr
- DRC-01C denominator (~108–109): sum ALL 2B categories (`table_4_a_1_import_goods` + `table_4_a_3_rcm_inward` + `table_4_a_4_isd` + `table_4_a_5_all_other_itc` totals), not just all_other. Test: import-heavy fixture flips risk flag correctly

### 5.4 Compliance Radar gate integrity
- Recursion guard: replace blanket `-k not test_compliance_radar` exclusion (~56–58) with env-var sentinel: `run_self_verification` sets `GSTR_WALA_SELF_VERIFY=1` in child env; `tests/test_compliance_radar.py` skips itself when that env var is set (`pytest.mark.skipif(os.environ.get(...))`). Gate now RUNS the sync tests
- Collapse the triplicated bounds-validation blocks (~127–174) into one `_validate_numeric_map(sub_key, val, allowed, lo, hi)` helper
- Fix mypy 7 errors (~100–119 heterogeneous dict): type as `Dict[str, Optional[Dict[str, Tuple[float,float]]]]` won't fly with mixed consumers — prefer per-key dataclass or TypedDict; mypy clean REQUIRED (baseline 7 → target ≤2, ideally 0, none new elsewhere)

### 5.5 Discovery honesty
- `--live` flag (~171) currently parsed but ignored; network fetch always runs, failures swallowed then canned advisories presented as "identified mandates"
- Required: without `--live`, skip network entirely (offline mode: canned advisories labeled `"source_of_truth": "bundled_snapshot"`); with `--live`, attempt fetch, on ANY failure print `WARNING: live fetch failed (<reason>) — showing bundled snapshot` and continue
- Kill `except Exception: pass` (~100–101) → catch specific (URLError, TimeoutError, OSError) with the warning above
- Final status banner says which mode ran; never claim "Synchronized with CBIC Rules" offline
- Fix stale usage docstring (`fetch_live_compliance.py` → actual filename) and duplicate `sys.path.insert` (~27–32)

### 5.6 Filing pack consistency
- `os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)` in all three writers (~72/146/189)
- Tolerance description strings synced to Task 2 reality ("tax within ±₹1")
- GSTR-3B pack Table 4 section: add missing 4(A)(3) RCM row (data exists as `avail.rcm_inward`)

### Acceptance & verification
- Full suite green; jsonschema actually imported somewhere; pipeline end-to-end test produces schema-valid artifacts
- Radar probe: craft patch JSON updating `interest_rates.section_50_1_net_cash_p_a` to 0.19 → apply → gate runs → manifest changes → engine output CHANGES (prove the old no-op lie is dead) → restore. Use tmp copies of manifest; never mutate repo config in committed tests
- discover offline run: zero network attempts (monkeypatch urlopen to explode), honest banner
- Commit: `fix(pipeline): schema enforcement, honest PDF/radar/discovery, argparse bridges, DRC denominator`

---

## 3. JUDGING PROTOCOL (what the Judge will do to every task)

1. `git show <commit> --stat` — allowlist violations = instant reject
2. Read every changed line against the task spec — missing/extra/misread requirements listed with file:line
3. Full suite + ruff delta on touched files (no NEW violations; net reduction welcomed)
4. Live probes re-derived independently from this plan's acceptance criteria (never trusting implementer claims)
5. Truthfulness spot-checks: for every changed failure path, probe that bad input yields a LOUD error naming context, and good input yields unchanged numerics
6. Statutory sanity: numbers checked against §1 adjudications and reference docs

**Verdicts:** APPROVED / CHANGES_REQUIRED(list) / REJECTED(scope violation).
Implementer fixes until APPROVED. Tasks strictly sequential: 2 → 3 → 4 → 5 → final whole-diff review.

## 4. FINAL INTEGRATION GATE (after Task 5)

- Full suite green; coverage ≥ baseline 67% (should be materially higher)
- `ruff check scripts tests` count ≤ parent-of-Task-2 count
- mypy ≤ 2 errors, zero new outside compliance_radar
- End-to-end: `gstr-wala pipeline` smoke on examples/ produces 6 artifacts, all schema-valid
- Whole-diff adversarial review (dff04a6..HEAD) before merge consideration
