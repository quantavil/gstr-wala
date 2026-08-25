# Plan 11 — QRMP / Quarterly Filing Unsupported (Due Date & Cutoff Hardcoded Monthly)

**Finding #11 — Category: Direction | Impact M if quarterly taxpayers use it | Effort L if full QRMP, S if doc-only | Confidence MED**
**Evidence:** `scripts/bridge_gstr1_to_gstr3b.py:34-44` + `grep -ri "quarter|qrmp|mpy"` = 0 hits

## Current State

`scripts/bridge_gstr1_to_gstr3b.py:34-44`
```python
def derive_gstr3b_due_date(ret_period: str) -> str:
    if not ret_period or len(ret_period) != 6 or not ret_period.isdigit():
        return ""
    mm = int(ret_period[:2])
    yyyy = int(ret_period[2:])
    if not (1 <= mm <= 12 and 2020 <= yyyy <= 2035):
        return ""
    next_mm = mm + 1 if mm < 12 else 1
    next_yyyy = yyyy if mm < 12 else yyyy + 1
    return f"20-{next_mm:02d}-{next_yyyy}"
```

`scripts/reconcile_gstr2b.py:558-567` derives `effective_cutoff = f"20-{next_mm:02d}-{next_yyyy}"` from `fp` — also monthly.

No code, docs, or tests mention QRMP (Quarterly Return Monthly Payment), IFF, or quarter mapping. Quarterly taxpayers whose `fp` is a quarter-end (e.g., `062026` for Apr-Jun) get a monthly next-month due date that is wrong for the quarter.

## Desired End State (scoped — doc + lightweight code guard)

Full QRMP tax logic (Table 3.1 quarterly aggregation, challan PMT-06 monthly, B2CL threshold per quarter) is **L** and not required now. Desired for this plan is **S**: explicit scope declaration + guardrails so quarterly users are not silently misled.

- `README.md` / `SKILL.md` (Step 0) state: "Monthly filing period (MMYYYY) — quarterly (QRMP) not yet supported; for QRMP quarters, pass explicit `--due-date` (Plan 01)."
- `derive_gstr3b_due_date` docstring warns about quarterly limitation; when `ret_period` looks like a quarter-end, optionally warn to use explicit due date.
- No silent wrong due date for quarter-end periods — at minimum a `warnings.warn`.

Full QRMP engine (if later) would map `fp` quarter → quarter-end due date (22nd/24th per quarter?) and adjust GSTR-1 Table 5/12 aggregation — out of scope for this plan.

## Step-by-Step Implementation (S — guardrail, not full QRMP)

1. **Read `scripts/bridge_gstr1_to_gstr3b.py:34-44`, `scripts/reconcile_gstr2b.py:558-567`, `SKILL.md:64-67`, `README.md` filing period mentions.**
2. **Edit `scripts/bridge_gstr1_to_gstr3b.py:34-44` docstring + body:**

   ```python
   def derive_gstr3b_due_date(ret_period: str) -> str:
       """Derives default GSTR-3B monthly due date (20th of succeeding month).

       Note: Only monthly filing (MMYYYY) is supported. For QRMP quarterly
       periods (e.g., 062026 for Apr-Jun quarter), pass --due-date explicitly;
       this function returns the monthly next-month 20th as a fallback.
       """
       # existing body unchanged, but add:
       # if ret_period ends with quarter-end months (03,06,09,12) and caller
       # is likely quarterly, emit UserWarning suggesting --due-date
   ```

   Add after validation:

   ```python
   if mm in (3, 6, 9, 12):
       # Do not change return value for backward compat; just warn when likely quarterly
       # Heuristic: if ret_period is quarter-end and no explicit due_date was passed, the caller
       # (bridge) can warn. Better warn in bridge_gstr1_and_2b_to_3b when due_date is None.
       pass
   ```

   Instead, add warning in `bridge_gstr1_and_2b_to_3b`:
   ```python
   if due_date is None and ret_period[0:2] in ("03","06","09","12"):
       import warnings
       warnings.warn("Quarterly (QRMP) filing not fully supported; derived due date assumes monthly 20th-next-month. Pass --due-date for quarter-end.", UserWarning, stacklevel=2)
   ```

3. **Edit docs:**
   - `README.md` CLI usage section: add note `> Note: Monthly MMYYYY only; for QRMP quarterly, pass explicit --due-date (e.g., 22-07-2026 for Apr-Jun quarter).`
   - `SKILL.md:64-67` Step 0: change `Return Period (e.g. 042026)` to `Return Period — monthly MMYYYY (e.g. 042026); QRMP quarterly not yet supported — use explicit due date if needed`.
4. **Add test** `tests/test_qrmp_guardrail.py`:
   - `derive_gstr3b_due_date("062026") == "20-07-2026"` (monthly fallback, unchanged).
   - `bridge_gstr1_and_2b_to_3b(..., due_date=None)` with quarter-end fp warns (pytest.warns).
5. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

## Out of Scope (explicit)

- Full QRMP engine: quarterly GSTR-1 (B2B aggregated per quarter), monthly PMT-06, IFF handling, `fp` quarter validation, late fee per quarter.
- Changing monthly 20th derivation.
- Changing reconcile 16(4) cutoff derivation beyond the warning.
- Filing calendar per state/turnover.

## STOP Conditions

- If team decides to implement full QRMP instead of guardrail — stop and rewrite this plan as L-effort engine plan.
- If `derive_gstr3b_due_date` is already used by external callers that depend on no warnings — make warning `stacklevel` and `category=UserWarning` so filtered by default.
- If any gate fails due to unrelated pre-existing red — isolate.
