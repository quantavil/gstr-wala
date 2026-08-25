# Plan 10 — cli.py Dict-Shaped Purchase Register Crashes with AttributeError

**Finding #10 — Category: Robustness/DX | Impact LOW-MED | Effort S | Confidence HIGH**
**Evidence:** `scripts/cli.py:89,215` vs `scripts/reconcile_gstr2b.py:927-933` — probed traceback

## Current State

`scripts/cli.py:89`
```python
pr_list = pr_data.get("purchases", pr_data) if isinstance(pr_data, dict) else pr_data
```
`scripts/cli.py:215` same pattern.

`scripts/reconcile_gstr2b.py:927-933` (correct handling):
```python
if isinstance(pr_data, dict):
    raw_list = pr_data.get("purchases") or pr_data.get("invoices") or []
    pr_list: list[dict[str, Any]] = raw_list if isinstance(raw_list, list) else []
elif isinstance(pr_data, list):
    pr_list = pr_data
else:
    pr_list = []
```

When `pr_data = {"meta":"x","rows":[]}` (no `purchases` key), the cli path yields `pr_list = {"meta":"x","rows":[]}` (the whole dict). Then `reconcile()` iterates dict keys (strings) → `pr_inv.get` → `AttributeError: 'str' object has no attribute 'get'` (probed). The standalone reconcile `main()` degrades to `[]` gracefully.

## Desired End State

- `scripts/cli.py` pipeline and `reconcile_command` handle dict-shaped purchase registers robustly: `{purchases: [...]}`, `{invoices: [...]}`, `[...]`, or malformed dict → empty list or clear error, never raw traceback.
- On malformed dict with no recognized array key, exit with actionable message `Purchase register must contain a list of invoices or an object with 'purchases' array`.
- No change to valid paths.

## Step-by-Step Implementation

1. **Read `scripts/cli.py:82-110` and `scripts/cli.py:201-224` plus `scripts/parse_purchase_register.py:140-148` canonical shape.**
2. **Extract helper** (or inline, prefer helper for DRY):
   ```python
   def _coerce_purchase_list(pr_data: Any) -> list[dict[str, Any]]:
       if isinstance(pr_data, dict):
           raw = pr_data.get("purchases")
           if raw is None:
               raw = pr_data.get("invoices")
           if isinstance(raw, list):
               return raw
           # bare dict that is itself a single invoice? No — treat as malformed
           if raw is None and not pr_data:
               return []
           # If no recognized key, fail with actionable message rather than AttributeError
           if raw is None:
               # Mimic reconcile_gstr2b.main: empty, but cli pipeline should warn
               return []
           return raw if isinstance(raw, list) else []
       elif isinstance(pr_data, list):
           return pr_data
       else:
           return []
   ```
   Place near top of `cli.py` (after imports).

3. **Edit `scripts/cli.py:89`** and **`cli.py:215`** to:
   ```python
   pr_list = _coerce_purchase_list(pr_data)
   if not isinstance(pr_list, list):
       console.print("[bold red]Error: Purchase register must contain a list of invoices or an object with 'purchases' array.[/bold red]")
       raise typer.Exit(1)
   ```

   For pipeline, if `pr_list` empty due to malformed dict, also warn but proceed (reconcile of 0 invoices is valid — will produce `in_2b_only` only). Optionally add `console.print("[yellow]![/yellow] Warning: purchase register contained no recognized 'purchases' array — treating as 0 invoices.")`.

4. **Add tests** `tests/test_cli_purchase_shape.py`:
   - `{"meta":"x"}` → pipeline/reconcile does not traceback, exits 0 or 1 with actionable message, `reconciliation.json` written or error printed.
   - `{"purchases":[...]}` and `[...]` → still pass.
   - `{"invoices":[...]}` → pass.
5. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
cat > /tmp/weird_pr.json <<'EOF'
{"meta":"other tool export","rows":[]}
EOF
uv run python3 scripts/cli.py reconcile /tmp/weird_pr.json examples/sample_gstr2b.json 2>&1 | head
# expect no AttributeError traceback — either empty result or actionable error
```

## Out of Scope

- Changing `parse_purchase_register.py` shape (it already writes `{"purchases":[...]}`).
- Changing reconcile's own `main()` (already correct).
- Plan 04 HSN work.

## STOP Conditions

- If `cli.py` is intentionally strict and should `Exit(1)` on unknown dict shape rather than treat as `[]` — choose `Exit(1)` with message, not traceback.
- If any gate fails due to unrelated pre-existing red — isolate.
