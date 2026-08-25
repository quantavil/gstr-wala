# Plan 05 — SKILL.md Broken ingest-pdf Command + False DRC Claim

**Finding #5 — Category: Docs/DX | Impact M | Effort S | Confidence HIGH**
**Evidence:** `SKILL.md:89,149` vs `scripts/cli.py:226-238` and `scripts/bridge_gstr1_to_gstr3b.py:372-433`

## Current State

`SKILL.md:88-90`
```markdown
      ```bash
      uv run python3 scripts/cli.py ingest-pdf docs/ work/images/ --dpi 200
      ```
```

`scripts/cli.py:226-238` — only one positional:
```python
def ingest_pdf(
    input_path: str = typer.Argument(..., help="Path to PDF file or directory of PDFs"),
    output_dir: str = typer.Option("work/images", "--output-dir", "-o", help="Output directory ..."),
    dpi: int = typer.Option(200, "--dpi", ...),
    force_image: bool = typer.Option(False, "--force-image", "-f", ...)
) -> None:
```

Second positional `work/images/` → `Got unexpected extra argument` (probed).

`SKILL.md:149`
```markdown
- The bridge automatically executes the **Pre-Emptive DRC-01B / DRC-01C Radar** ...
```

`scripts/bridge_gstr1_to_gstr3b.py:372-433` `main()` never calls `check_drc_mismatch_risks`; only `scripts/cli.py:108-122` pipeline does:
```python
drc_res = check_drc_mismatch_risks(comp1["summary"], g3b_input, tot_2b_itc)
```

## Desired End State

- `SKILL.md` Step 2 command uses the correct flag form and succeeds when an agent copies it verbatim.
- `SKILL.md` Step 6 language matches code: pipeline runs the radar; standalone bridge does not (or bridge is changed to run it — either, but doc and code must agree).
- No other SKILL.md workflow steps broken.

## Step-by-Step Implementation

1. **Read `SKILL.md:80-150` and `scripts/cli.py:226-238`, `scripts/bridge_gstr1_to_gstr3b.py:372-433`.**
2. **Edit `SKILL.md:88-90`** — change to:
   ```markdown
   uv run python3 scripts/cli.py ingest-pdf docs/ --output-dir work/images/ --dpi 200
   ```
   Also fix any other occurrences of that pattern (search `ingest-pdf` in SKILL.md/README.md).
3. **Fix the DRC claim — choose A or B (prefer A, doc-only, minimal risk):**

   **A. Doc fix (recommended):** Edit `SKILL.md:149` to:
   ```markdown
   - The **pipeline** (`scripts/cli.py pipeline`) automatically executes the Pre-Emptive DRC-01B/DRC-01C Radar.
     The standalone bridge (`scripts/bridge_gstr1_to_gstr3b.py`) only populates Table 3/4; run the radar via `python3 -c "from scripts.bridge_gstr1_to_gstr3b import check_drc_mismatch_risks; ..."` or via the pipeline.
   ```

   **B. Code fix (if team prefers code to match doc):** In `scripts/bridge_gstr1_to_gstr3b.py:420-429` after `g3b_input = bridge_gstr1_and_2b_to_3b(...)` compute DRC and print:
   ```python
   from scripts.gst_engine import compute_gstr1_tables as _cg1
   from scripts.utils import safe_float as _sf
   comp1 = _cg1(g1_data)
   t4 = (recon_data or {}).get("gstr3b_table_4_auto_population", {})
   tot_2b = sum(_sf(t4.get(k, {}).get("total", 0.0)) for k in ("table_4_a_1_import_goods","table_4_a_3_rcm_inward","table_4_a_4_isd","table_4_a_5_all_other_itc"))
   drc = check_drc_mismatch_risks(comp1["summary"], g3b_input, tot_2b)
   print(json.dumps(drc, indent=2))
   ```
   Guard so no failure when `recon_data` is None.

   Pick A or B and document choice in plan execution notes. Default to A unless user asks otherwise.
4. **Verify `README.md:79` already uses correct `--output-dir` — leave as is.**
5. **Add/extend test** `tests/test_cli_commands.py::test_cli_pdf_to_images_command` already uses correct `--output-dir` form — no change. Add doc-smoke test: assert `SKILL.md` contains `"ingest-pdf" + "--output-dir"` not `"ingest-pdf docs/ work/images/"`.
6. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
uv run python3 scripts/cli.py ingest-pdf --help | grep -q "output-dir" && echo ok
# and copy-paste SKILL.md command verbatim with a tmp docs dir → exit 0, manifest exists
```

## Out of Scope

- Changing ingest-pdf Python API.
- Plan 06 file:// links (separate).
- Plan 12 coverage.

## STOP Conditions

- If `scripts/cli.py:ingest_pdf` signature has been changed to accept a second positional — keep the old SKILL.md form and update this plan.
- If team decides bridge should run DRC and you chose doc-fix — ask which path.
- If any gate fails due to unrelated pre-existing red — isolate.
