# Plan 01 — Statutory Dues (Sec 50 / Sec 47) Unreachable via CLI/Pipeline

**Finding #1 — Category: Correctness | Impact HIGH | Effort S-M | Confidence HIGH**
**Evidence:** `scripts/bridge_gstr1_to_gstr3b.py:61,372-433` + `scripts/cli.py:109`

## Current State (exact excerpt)

`scripts/bridge_gstr1_to_gstr3b.py:47-62`
```python
def bridge_gstr1_and_2b_to_3b(
    gstr1_data: dict[str, Any],
    recon_data: dict[str, Any] | None = None,
    due_date: str | None = None,
    filing_date: str | None = None,
    turnover_slab: str = "upto_1.5cr",
    opening_credit_ledger: dict[str, float] | None = None,
    opening_cash_ledger: dict[str, float] | None = None
) -> dict[str, Any]:
    g1_res = compute_gstr1_tables(gstr1_data)
    gstin = g1_res["gstin"]
    ret_period = g1_res["fp"]
    computed_due_date = due_date or derive_gstr3b_due_date(ret_period)
    computed_filing_date = filing_date or computed_due_date
```

`scripts/bridge_gstr1_to_gstr3b.py:372-433` — `main()` parser has **no** `--due-date/--filing-date/--turnover-slab`:
```python
parser.add_argument("g1_input", help="Path to GSTR-1 Input JSON")
parser.add_argument("pos_args", nargs="*", help="Optional [recon_input] [output_3b]")
parser.add_argument("--recon", dest="recon_opt", default=None, ...)
parser.add_argument("-o", "--output", dest="out_opt", default=None, ...)
# ... no due/filing/turnover args ...
g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_data)
```

`scripts/cli.py:52-60` pipeline signature:
```python
def pipeline(
    sales: str = typer.Option(..., "--sales", "-s", ...),
    purchases: str = typer.Option(..., "--purchases", "-p", ...),
    gstr2b: str = typer.Option(..., "--gstr2b", "-b", ...),
    output_dir: str = typer.Option("output", "--output-dir", "-o", ...),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", ...)
) -> None:
```

Branch `cli.py:109`: `g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_res)` — never passes dates.

Result: `populate_statutory_dues()` always sees `filing_date == due_date` → `delay_days == 0` → `interest_details`/`late_fee_details` never populated via any CLI entry point. Tests only at `tests/test_audit_remediations.py:221` call the function with explicit kwargs.

## Desired End State

- `scripts/bridge_gstr1_to_gstr3b.py` CLI accepts `--due-date DD-MM-YYYY`, `--filing-date DD-MM-YYYY`, `--turnover-slab {upto_1.5cr,1.5cr_to_5cr,above_5cr}` and threads them to `bridge_gstr1_and_2b_to_3b`.
- `scripts/cli.py` `pipeline` command accepts same three options and threads them to the bridge call. Default remains `due=derive(ret_period)`, `filing=due`, `slab=upto_1.5cr` for backward compat (on-time filing).
- `populate_statutory_dues()` continues to respect pre-existing `interest_details`/`late_fee_details` (never overwrite) — no change there.
- New tests: pipeline + bridge CLI late-filing path produces non-zero `interest_details` and `late_fee_details` in `gstr3b_input.json`.

## Step-by-Step Implementation

1. **Read `scripts/bridge_gstr1_to_gstr3b.py` + `scripts/cli.py` fully** (do not assume line numbers stable).
2. **Edit `scripts/bridge_gstr1_to_gstr3b.py:372-420`:**
   - Add `parser.add_argument("--due-date", dest="due_date_cli", default=None, help="GSTR-3B due date DD-MM-YYYY; defaults to 20th of next month")`
   - Add `parser.add_argument("--filing-date", dest="filing_date_cli", default=None, help="Actual filing date DD-MM-YYYY; defaults to due date (on-time)")`
   - Add `parser.add_argument("--turnover-slab", dest="turnover_slab_cli", default="upto_1.5cr", choices=["upto_1.5cr","1.5cr_to_5cr","above_5cr"])`
   - Change call to `bridge_gstr1_and_2b_to_3b(g1_data, recon_data, due_date=args.due_date_cli, filing_date=args.filing_date_cli, turnover_slab=args.turnover_slab_cli)`
   - Validate dates via `validate_date_str` or `parse_date` — exit 1 with actionable message on malformed.
3. **Edit `scripts/cli.py:52-60` pipeline signature:**
   - Add `due_date: str = typer.Option(None, "--due-date", help="GSTR-3B due date DD-MM-YYYY")`
   - Add `filing_date: str = typer.Option(None, "--filing-date", help="Actual filing date DD-MM-YYYY")`
   - Add `turnover_slab: str = typer.Option("upto_1.5cr", "--turnover-slab", help="Turnover slab for late fee caps")`
   - At `cli.py:109` pass them: `bridge_gstr1_and_2b_to_3b(g1_data, recon_res, due_date=due_date, filing_date=filing_date, turnover_slab=turnover_slab)`
4. **Add test** `tests/test_cli_pipeline_dues.py` (or extend `test_audit_remediations.py`):
   - Use `CliRunner` to invoke `pipeline --sales ... --purchases ... --gstr2b ... --due-date 20-05-2026 --filing-date 04-07-2026 --turnover-slab upto_1.5cr --output-dir tmp` and assert `gstr3b_input.json` contains `interest_details.interest_amount > 0` and `late_fee_details`.
   - Unit test `bridge_gstr1_to_gstr3b.main` with tmp files and the new flags.
5. **Run gates** (see below).

## Verified Pass/Fail Gates (repo's own commands)

```bash
uv run pytest -q --no-cov
# or: uv run pytest -q
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Expect **211+ passed** (new tests added), ruff clean, mypy clean. Manual probe:

```bash
python3 scripts/bridge_gstr1_to_gstr3b.py examples/sample_sales_register.json --due-date 20-05-2026 --filing-date 04-07-2026 -o /tmp/g3b_late.json
python3 -c "import json; d=json.load(open('/tmp/g3b_late.json')); print(d.get('interest_details'), d.get('late_fee_details'))"
# should print non-empty dicts
```

## Out of Scope

- Changing Section 50 rate or late-fee cap math (`gst_engine.py`, `constants.py` — manifest-driven).
- Portal JSON serialization of dues (Plan 03).
- QRMP/quarterly due-date derivation (Plan 11).
- PMT-06 challan UI.

## STOP Conditions — Do Not Proceed, Ask User

- If `bridge_gstr1_to_gstr3b.py` parser already gained conflicting flags in `main` branch (merge) — reconcile before editing.
- If `populate_statutory_dues()` signature/behavior changed (no longer respects pre-existing details or no longer uses `optimize_from_input_dict()["cash_tax_payable"]["total"]`) — re-audit the function.
- If any gate fails due to unrelated pre-existing red (not your diff) — isolate and report; do not force.
