# Plan 02 — Bridge CLI Silently Overwrites Input Files Containing "3b"

**Finding #2 — Category: Correctness/data-loss | Impact HIGH | Effort S | Confidence HIGH**
**Evidence:** `scripts/bridge_gstr1_to_gstr3b.py:372-433` — live probe destroyed `recon_3b.json`

## Current State (exact excerpt)

`scripts/bridge_gstr1_to_gstr3b.py:387-411`
```python
if args.pos_args:
    if len(args.pos_args) == 1:
        arg0 = args.pos_args[0]
        if args.recon_opt:
            out_file = arg0
        elif args.out_opt:
            recon_file = arg0
        else:
            is_recon = False
            if os.path.exists(arg0) and "3b" not in arg0.lower():
                try:
                    with open(arg0, encoding="utf-8") as f_check:
                        sample = json.load(f_check)
                        if isinstance(sample, dict) and ("gstr3b_table_4_auto_population" in sample or "summary" in sample):
                            is_recon = True
                except Exception:
                    is_recon = False
            if is_recon:
                recon_file = arg0
            else:
                out_file = arg0
    elif len(args.pos_args) >= 2:
        recon_file = args.pos_args[0] if not recon_file else recon_file
        out_file = args.pos_args[1]
```

Later `main()` does `with open(out_file, "w", ...)` with no existence guard — if the single positional was an existing recon file whose name contains `"3b"`, it is unconditionally truncated.

Probe: `bridge_gstr1_to_gstr3b.py sales.json recon_3b.json` (where `recon_3b.json` is a valid reconciliation) → `recon_3b.json` overwritten with bridge output, exit 0.

## Desired End State

- Single-positional form never destroys an existing file without explicit `--output` or user confirmation.
- Heuristic `"3b" not in name` removed; detection based solely on file content + explicit flags.
- If `out_file` already exists and is not `/dev/null`, either refuse with actionable error or require `--force` to overwrite. Existing behavior `out_file = "gstr3b_input.json"` default remains.

## Step-by-Step Implementation

1. **Read `scripts/bridge_gstr1_to_gstr3b.py:372-433` fully.**
2. **Replace the positional-sniff block (lines 387-411) with:**

   ```python
   if args.pos_args:
       if len(args.pos_args) == 1:
           arg0 = args.pos_args[0]
           if args.recon_opt:
               out_file = arg0
           elif args.out_opt:
               recon_file = arg0
           else:
               # Content-based detection only — no name heuristic
               is_recon = False
               if os.path.exists(arg0):
                   try:
                       with open(arg0, encoding="utf-8") as f_check:
                           sample = json.load(f_check)
                           if isinstance(sample, dict) and ("gstr3b_table_4_auto_population" in sample or "summary" in sample):
                               is_recon = True
                           # Also accept raw GSTR-2B shape? No — that is not a recon file; only recon has summary+table_4
                   except Exception:
                       is_recon = False
               if is_recon:
                   recon_file = arg0
               else:
                   out_file = arg0
       elif len(args.pos_args) >= 2:
           recon_file = args.pos_args[0] if not recon_file else recon_file
           out_file = args.pos_args[1] if not args.out_opt else args.out_opt  # explicit -o wins
   ```

   Add parser flag: `parser.add_argument("-f","--force", action="store_true", help="Allow overwriting existing output file")`
3. **Guard the write:** before `with open(out_file, "w", ...)` add:
   ```python
   if os.path.exists(out_file) and not args.force and out_file != recon_file:
       # If out_file is an existing recon input, never silently clobber
       # Probe: if out_file == recon_file (user passed recon path as output), error
       parser.error(f"Output file '{out_file}' already exists. Use --force to overwrite or choose a different -o path.")
   ```
   Alternatively, if `out_file` resolves to same inode as `recon_file`, error unconditionally.
4. **Add tests** `tests/test_bridge_cli_overwrite.py`:
   - Create tmp `recon_3b.json` with `gstr3b_table_4_auto_population` key, invoke bridge with single positional = that file → assert `recon_file` chosen, `out_file` remains default, original file unmodified (checksum).
   - Create existing `output.json`, invoke bridge with same as output positional without `--force` → assert exit 2 / error message.
   - With `--force` → succeeds.
5. **Run gates** (below).

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

New overwrite-guard tests must pass. Manual probe:

```bash
cp examples/sample_sales_register.json /tmp/sales.json
python3 scripts/bridge_gstr1_to_gstr3b.py /tmp/sales.json /tmp/recon_3b.json 2>&1 | head
# with existing recon_3b.json containing "3b" in name, should NOT overwrite it
```

## Out of Scope

- Changing 2-arg form semantics (`sales recon out`).
- Adding interactive prompts (CI non-interactive).
- Plan 01's due/filing flags (separate).
- Changing default output path.

## STOP Conditions

- If upstream merge changed `bridge_gstr1_to_gstr3b.py` argument names or added a competing overwrite guard — reconcile rather than duplicate.
- If tests reveal `pos_args` handling is used by `cli.py` pipeline — ensure pipeline path (which calls the function directly, not `main()`) unaffected.
- If any gate fails due to unrelated pre-existing red — isolate.
