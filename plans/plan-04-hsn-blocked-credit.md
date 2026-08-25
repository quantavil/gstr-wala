# Plan 04 — HSN-Based Section 17(5) Blocked Credit Never Fires for Parsed Registers

**Finding #4 — Category: Direction/correctness | Impact M | Effort S | Confidence HIGH**
**Evidence:** `scripts/parse_purchase_register.py:106-118` vs `scripts/reconcile_gstr2b.py:513-515`

## Current State

`scripts/parse_purchase_register.py:106-118` emits purchases without `hsn_sc`:
```python
purchases.append({
    "ctin": ctin.upper(),
    "inum": inum,
    "idt": idt,
    "pos": pos,
    "txval": round_cur(txval),
    "iamt": round_cur(iamt),
    "camt": round_cur(camt),
    "samt": round_cur(samt),
    "csamt": round_cur(csamt),
    "is_blocked_17_5": is_blocked,
    "unpaid_days": unpaid_days
})
```

`scripts/reconcile_gstr2b.py:513-515`
```python
is_blocked = bool(pr_inv.get("is_blocked_17_5", False)) or (
    str(pr_inv.get("hsn_sc", "")).strip() in BLOCKED_HSNS
)
```
`BLOCKED_HSNS = {"8702","8703","8704","9963","9965","9966","9967"}` (`constants.py:72`). The second disjunct is always false for parser-produced rows.

`parse_purchase_register.py` also lacks Excel support (CSV/JSON only) while `parse_sales_register.py` handles Excel — the same HSN gap would affect any future Excel path. `examples/sample_purchase_register.json` contains no `hsn_sc` rows to catch this.

Manual `is_blocked_17_5` column still works (`parse_purchase_register.py:97-100`), so the gap is *automatic* HSN detection for CSV/Excel-ingested books.

## Desired End State

- CSV and Excel purchase registers may include an `hsn_sc` / `hsn_code` / `hsn` / `sac` column (case-insensitive, per existing `_money` alias pattern). When present, its value is preserved as `hsn_sc` on the purchase record; when absent, `hsn_sc` omitted (no fabricated default).
- Reconcile's automatic `BLOCKED_HSNS` check then fires for parser-produced records without requiring manual `is_blocked_17_5`.
- Optional: also parse `unpaid_value` / `unpaid_amount` if present (enables Rule 37 proportional reversal — currently defaults to full).

## Step-by-Step Implementation

1. **Read `scripts/parse_purchase_register.py` and `scripts/reconcile_gstr2b.py:499-523` fully.**
2. **Edit `scripts/parse_purchase_register.py`:**
   - Add alias tuple: `_HSN_ALIASES = ("hsn_sc","hsn_code","hsn","sac")` and `_UNPAID_VAL_ALIASES = ("unpaid_value","unpaid_amount","balance_payable")`.
   - After `pos = ...` add:
     ```python
     hsn_sc = next((row_norm.get(a) for a in _HSN_ALIASES if row_norm.get(a)), "")
     hsn_sc = str(hsn_sc).strip() if hsn_sc else ""
     unpaid_val_raw = next((row_norm.get(a) for a in _UNPAID_VAL_ALIASES if row_norm.get(a) not in (None, "")), None)
     try:
         unpaid_value = safe_float_strict(unpaid_val_raw) if unpaid_val_raw is not None else None
     except ValueError:
         raise ValueError(f"Row {row_idx}: column 'unpaid_value' has unparseable amount {unpaid_val_raw!r}") from None
     ```
   - In `purchases.append(...)` add `"hsn_sc": hsn_sc` only when non-empty (or always as `""` — match reconcile's `str(...).strip()` check). Prefer always include as `"hsn_sc": hsn_sc` for debuggability.
   - If `unpaid_value is not None`: include `"unpaid_value": round_cur(unpaid_value)`.
   - Extend `parse_csv_purchases` to also handle `unpaid_days` already there; keep.
   - Add `parse_excel_purchases(excel_path)` mirroring `parse_excel_sales` using `read_excel_calamine` (reuse), then wire in `main()` `elif lower_file.endswith((".xlsx",".xls",".xlsb"))` branch.
3. **Do not change** `reconcile_gstr2b.py:_classify_books_invoice` — it already reads `hsn_sc` correctly. No change to `BLOCKED_HSNS`.
4. **Add tests** `tests/test_parse_purchase_hsn.py`:
   - CSV with `hsn_sc=8702` → reconcile classifies as `blocked_17_5`.
   - CSV without HSN → not blocked unless `is_blocked_17_5=true`.
   - Excel path same (use `read_excel_calamine` mock or tiny xlsx fixture).
   - `unpaid_value` proportional path: row with `unpaid_days=190, unpaid_value=5000` → Rule 37 proportional reversal ratio correct.
5. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
python3 -c "
import csv, json, tempfile, os
from scripts.parse_purchase_register import parse_csv_purchases
from scripts.reconcile_gstr2b import reconcile
# write tmp csv with hsn 8702, run reconcile against empty 2B, check is_blocked
"
```

## Out of Scope

- Changing `BLOCKED_HSNS` set.
- Changing reconcile's blocked→`table_4_b_1` routing.
- Adding new blocked HSNs beyond manifest.
- Full Excel formatting/validation overhaul.

## STOP Conditions

- If purchase CSV schema in the wild uses a different HSN header (e.g., `HSN/SAC`, `Service Code`) not in alias list — expand alias list rather than fail.
- If `safe_float_strict` for `unpaid_value` breaks existing CSVs with blank cells — keep blank→`None` path, only error on present-but-unparseable.
- If Excel engine `python-calamine` not available in CI — gate with `pytest.importorskip`.
