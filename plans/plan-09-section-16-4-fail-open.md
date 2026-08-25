# Plan 09 — Section 16(4) Time-Limit Gate Fails Open on Malformed Date

**Finding #9 — Category: Robustness | Impact LOW practical (hand-crafted JSON only) | Effort S | Confidence HIGH (behavior)**
**Evidence:** `scripts/reconcile_gstr2b.py:52-79`

## Current State

`scripts/reconcile_gstr2b.py:52-79`
```python
def _is_section_16_4_expired(idt_str: str | None, cutoff_date_str: str | None = None) -> bool:
    if not idt_str or not str(idt_str).strip():
        return False
    try:
        norm_idt = normalize_date_str(str(idt_str).strip())
        inv_dt = _parse_dmy_date(norm_idt)
    except (ValueError, TypeError, IndexError):
        return False  # ← fail-open: malformed → claimable

    fy_end_year = inv_dt.year if inv_dt.month <= 3 else inv_dt.year + 1
    deadline_date = date(fy_end_year, 11, 30)
    if cutoff_date_str and str(cutoff_date_str).strip():
        try:
            norm_cutoff = normalize_date_str(str(cutoff_date_str).strip())
            eval_date = _parse_dmy_date(norm_cutoff)
        except (ValueError, TypeError, IndexError):
            eval_date = datetime.now(UTC).date()  # ← second fail-open
    else:
        eval_date = datetime.now(UTC).date()
    return eval_date > deadline_date
```

Upstream parsers (`parse_purchase_register.py:87`, `parse_sales_register.py:121`) strictly validate dates, so normal flow never hits this. Risk: hand-edited `purchase_register.json` / `gstr2b.json` with typo date like `"31-02-2026"` or `"2026/13/01"` bypasses 16(4) and is classified claimable (over-claim).

## Desired End State

- Malformed invoice date that reaches this gate is treated as *ineligible/barred* (fail-closed) or explicitly surfaced as a validation error — not silently claimable.
- Malformed cutoff falls back to wall-clock **but** logs a warning so the operator knows evaluation was degraded.
- No change to valid-date behavior; existing tests for valid/invalid cutoff still pass.

## Step-by-Step Implementation

1. **Read `scripts/reconcile_gstr2b.py:46-80` and `scripts/utils.py:190-236` (`normalize_date_str`).**
2. **Edit `_is_section_16_4_expired`:**

   ```python
   def _is_section_16_4_expired(idt_str: str | None, cutoff_date_str: str | None = None) -> bool:
       if not idt_str or not str(idt_str).strip():
           return False  # missing date → cannot bar; upstream should have rejected
       try:
           norm_idt = normalize_date_str(str(idt_str).strip())
           inv_dt = _parse_dmy_date(norm_idt)
       except (ValueError, TypeError, IndexError) as e:
           # Malformed invoice date that escaped upstream validation → bar ITC and surface
           # Caller (reconcile) will route to ineligible bucket; log once.
           import warnings
           warnings.warn(f"Section 16(4) gate: malformed invoice date {idt_str!r} — treating as time-barred: {e}", UserWarning, stacklevel=2)
           return True  # fail-closed

       fy_end_year = inv_dt.year if inv_dt.month <= 3 else inv_dt.year + 1
       deadline_date = date(fy_end_year, 11, 30)
       if cutoff_date_str and str(cutoff_date_str).strip():
           try:
               norm_cutoff = normalize_date_str(str(cutoff_date_str).strip())
               eval_date = _parse_dmy_date(norm_cutoff)
           except (ValueError, TypeError, IndexError) as e:
               import warnings
               warnings.warn(f"Section 16(4) gate: malformed cutoff {cutoff_date_str!r} — falling back to today: {e}", UserWarning, stacklevel=2)
               eval_date = datetime.now(UTC).date()
       else:
           eval_date = datetime.now(UTC).date()
       return eval_date > deadline_date
   ```

   Alternative stricter: raise `ValueError` instead of returning `True` and let `reconcile()` catch and route to `ineligible_2b`+`details` with reason. Either satisfies fail-closed; `return True` is minimal diff.

3. **Add tests** `tests/test_16_4_malformed.py`:
   - `idt="31-02-2026"` → `is_expired == True` (or raises → caller bars).
   - `idt="not-a-date"` → barred.
   - `cutoff="bad"` → warns, does not crash, uses today.
   - Valid `idt="15-04-2025"` with explicit future cutoff → not expired (regression).
4. **Run gates.** Ensure no existing test expects `return False` on malformed date — grep `is_section_16_4_expired` in tests.

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

## Out of Scope

- Changing 16(4) deadline rule (Nov 30 FY+1) or wall-clock default.
- Adding upstream validation (parsers already strict).
- Plan 12 coverage work.

## STOP Conditions

- If tests assert `malformed → False` as desired behavior (e.g., `test_reconcile_gstr2b.py` expects malformed dates to be claimable) — reconcile with authors; do not flip silently.
- If `_is_section_16_4_expired` is called from a hot path where `warnings.warn` would flood logs — rate-limit or use `logger.warning` once.
- If any gate fails due to unrelated pre-existing red — isolate.
