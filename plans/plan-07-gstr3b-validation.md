# Plan 07 — GSTR-3B Portal Generator Performs No Validation (GSTR-1 Twin Does)

**Finding #7 — Category: DX/correctness | Impact M | Effort S | Confidence HIGH**
**Evidence:** `scripts/generate_gstr3b_json.py:258-282` vs `scripts/generate_gstr1_json.py:321-327`

## Current State

`scripts/generate_gstr1_json.py:321-327`
```python
val_res = validate_gstr1_input(data)
if not val_res.is_valid:
    print(f"Error: Validation failed with {len(val_res.errors)} error(s):")
    for e in val_res.errors:
        print(f"  - {e}")
    sys.exit(1)
portal_json = generate_portal_gstr1(data)
```

`scripts/generate_gstr3b_json.py:258-282` — no validation at all:
```python
def main():
    in_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "gstr3b_portal.json"
    if not os.path.exists(in_file):
        sys.exit(f"Error: File '{in_file}' not found.")
    with open(in_file, encoding="utf-8") as f:
        data = json.load(f)
    portal_json = generate_portal_gstr3b(data)  # ← no validate_gstr3b_input
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(portal_json, f, indent=2)
```

Consequence: negative liabilities, bad GSTIN, malformed period all produce a seemingly-successful `gstr3b_portal.json` headed for upload.

## Desired End State

- `scripts/generate_gstr3b_json.py:main()` mirrors the GSTR-1 path: fail fast with actionable errors, exit 1, never writes output on invalid input.
- Optional `--force` to emit despite warnings (not errors) if team wants leniency — but errors still block.
- Tests cover the new validation gate.

## Step-by-Step Implementation

1. **Read `scripts/generate_gstr3b_json.py:1-282` and `scripts/validate_gst_input.py:228-286`.**
2. **Edit `scripts/generate_gstr3b_json.py:1-20`** — add import:
   ```python
   from scripts.validate_gst_input import validate_gstr3b_input
   ```
3. **Edit `main()` after JSON load:**
   ```python
   val_res = validate_gstr3b_input(data)
   if not val_res.is_valid:
       print(f"Error: Validation failed with {len(val_res.errors)} error(s):")
       for e in val_res.errors:
           print(f"  - {e}")
       if val_res.warnings:
           for w in val_res.warnings:
               print(f"  [!] {w}")
       sys.exit(1)
   if val_res.warnings:
       for w in val_res.warnings:
           print(f"  [!] {w}", file=sys.stderr)
   portal_json = generate_portal_gstr3b(data)
   ```
   Keep `generate_portal_gstr3b()` pure (no validation inside) — validation only in `main()`, matching GSTR-1 twin.
4. **Add tests** `tests/test_gstr3b_validation_gate.py`:
   - Invalid GSTIN → `main()` exit 1, no output file created.
   - Negative `outward_supplies.taxable.iamt` → exit 1.
   - Valid input → exit 0, output matches snapshot and `itc_elg` schema.
5. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
cat > /tmp/bad3b.json <<'EOF'
{"gstin":"09AAAAA0000A1Z5","ret_period":"132026","outward_supplies":{"taxable":{"txval":100,"iamt":-5,"camt":0,"samt":0,"csamt":0}}}
EOF
python3 scripts/generate_gstr3b_json.py /tmp/bad3b.json /tmp/out.json; echo exit:$?
# expect exit 1, no /tmp/out.json, error mentions ret_period / negative
```

## Out of Scope

- Changing validation rules (`validate_gst_input.py`).
- Adding JSON schema validation inside this generator (pipeline already does `validate_against_schema`).
- Portal interest emission (Plan 03).

## STOP Conditions

- If `validate_gstr3b_input` is too strict and blocks the pipeline's own `gstr3b_input.json` (bridge output) — loosen validator or fix bridge output shape, do not suppress the gate silently.
- If GSTR-1 validation path has diverged (e.g., now uses Pydantic, not `validate_gstr1_input`) — mirror the *current* GSTR-1 path, not the excerpt.
- If any gate fails due to unrelated pre-existing red — isolate.
