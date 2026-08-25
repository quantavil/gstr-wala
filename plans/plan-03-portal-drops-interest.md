# Plan 03 — Portal GSTR-3B JSON Drops Computed Interest/Late Fee

**Finding #3 — Category: Correctness | Impact M-HIGH | Effort S | Confidence HIGH**
**Evidence:** `scripts/generate_gstr3b_json.py:204-255` (no interest key) vs `schemas/gstr3b_portal_schema.json:89-97` (defines `interest_details`) + live probe

## Current State

`scripts/generate_gstr3b_json.py:199-255` builds `tx_pmt` from `optimize_from_input_dict()` but never reads `interest_details`/`late_fee_details`:

```python
opt_res = optimize_from_input_dict(input_data)
m = opt_res["setoff_matrix"]
cash_tax = opt_res.get("cash_tax_payable", {})
tx_pmt = { "tx_py": [ { "paid_cash": { "iamt": round_cur(cash_tax.get(...)) ... } } ] }
# ... no interest_details / late_fee block ...
return { "version": ..., "gstin": ..., "ret_period": ..., "sup_details": ..., "itc_elg": ..., "inward_sup": ..., "tx_pmt": tx_pmt }
```

`schemas/gstr3b_portal_schema.json:89-97` declares optional top-level `interest_details`:
```json
"interest_details": { "type": "object", "properties": { "iamt": {"type":"number"}, "camt":..., "samt":..., "csamt":... } }
```

Probe with `g3b_input.json` containing `"interest_details": {"interest_amount": 900}`:
- `optimize_from_input_dict` → `net_cash_required 13,900` (interest included in challan)
- `generate_portal_gstr3b` output → `paid_cash 13,000`, no `interest_details` key → artifacts disagree.

`cash_tax_payable` is intentionally tax-only (Table 6.1) per prior remediation — that is correct. Missing is the separate statutory-dues section.

## Desired End State

- `generate_portal_gstr3b(input_data, portal_version=None)` emits `interest_details` (and if schema supports, late-fee details) when `input_data` contains them **or** when optimizer's `interest_liability`/`late_fee_liability` is non-zero, matching the portal schema shape.
- When no dues exist, output omits the key (no empty object) — keeps existing minimal output stable.
- Existing tests that compare portal JSON snapshots still pass (or are updated to expect the new optional key only when dues present).

## Step-by-Step Implementation

1. **Read `scripts/generate_gstr3b_json.py:36-255` and `schemas/gstr3b_portal_schema.json:89-110` fully.**
2. **Decide serialization shape:** portal schema `interest_details` expects per-head `{iamt,camt,samt,csamt}` (not single `interest_amount`). Optimizer already produces `opt_res["interest_liability"]` per head and supports input `interest_details` as either per-head or fallback `{"interest_amount": tot}` (see `itc_optimizer.py:156-190` split logic). Reuse that.
3. **Edit `scripts/generate_gstr3b_json.py:199-245`** — after `opt_res = optimize_from_input_dict(input_data)` add:
   ```python
   interest = opt_res.get("interest_liability", {})
   late_fee = opt_res.get("late_fee_liability", {})
   portal_extra: dict[str, Any] = {}
   if any(interest.get(k, 0) for k in ("iamt","camt","samt","csamt")):
       portal_extra["interest_details"] = {
           "iamt": round_cur(interest.get("iamt", 0.0)),
           "camt": round_cur(interest.get("camt", 0.0)),
           "samt": round_cur(interest.get("samt", 0.0)),
           "csamt": round_cur(interest.get("csamt", 0.0)),
       }
   # Late fee: schema has no top-level late_fee_details; portal expects interest_details only.
   # If schema later adds it, emit similarly. For now, include only interest.
   ```
   Merge into return: `return { ..., "tx_pmt": tx_pmt, **portal_extra }` — only when non-zero.
   - Alternative if input already has `interest_details` per-head: prefer `opt_res` computed per-head (authoritative after split).
4. **Add tests** `tests/test_portal_interest_emit.py`:
   - Input with `interest_amount=900`, `late_fee_details` → portal JSON contains `interest_details` per-head summing to 900, `paid_cash` remains tax-only.
   - Input without dues → no `interest_details` key (backward compat).
   - Validate output against `schemas/gstr3b_portal_schema.json` via `jsonschema` still passes.
5. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
python3 scripts/generate_gstr3b_json.py /tmp/g3b_with_interest.json /tmp/out_portal.json
python3 -c "import json; d=json.load(open('/tmp/out_portal.json')); print(json.dumps({k:v for k,v in d.items() if k=='interest_details'}, indent=2))"
```

## Out of Scope

- Changing `cash_tax_payable` vs `net_cash_required` semantics (Plan 01).
- Modifying interest/late-fee computation rates (`gst_engine.py`, `constants.py`).
- Emitting interest inside `tx_pmt` (Table 6.1 is tax-only by statute).
- QRMP/quarterly.

## STOP Conditions

- If portal schema in repo has been updated to make `interest_details` required or to nest it differently — adapt serialization to new schema, do not emit stale shape.
- If `optimize_from_input_dict` no longer returns `interest_liability` per-head — re-audit optimizer before emitting.
- If snapshot tests pin portal JSON without `interest_details` and fail only on that key — update snapshots to allow optional key, do not suppress the new key.
