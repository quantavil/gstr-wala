# Plan 12 — Coverage Holes in Self-Modifying Components (compliance_radar 47%, discover 24%)

**Finding #12 — Category: Test coverage / Tech debt | Impact M | Effort M | Confidence HIGH**
**Evidence:** `uv run pytest --cov` → `scripts/compliance_radar.py 47%`, `scripts/discover_statutory_rules.py 24%`, `scripts/benchmark_stress.py 0%`

## Current State

Coverage report (77% total):
```
scripts/compliance_radar.py      214 stmts  113 missed  47%  misses include _validate_patch branches, apply_compliance_patch, print_status, main
scripts/discover_statutory_rules.py 85 stmts  65 missed  24%
scripts/benchmark_stress.py       65 stmts   65 missed   0%
```

`scripts/compliance_radar.py:110-179` `_validate_patch` — the safety gate for agentic self-rewriting of `config/rules_manifest.json` — has most branches uncovered (`tests/test_compliance_radar.py` 94 lines, 3 tests, only happy paths). Mutations to `b2cl_threshold`, `interest_rates`, `late_fee_caps`, `drc_surveillance_thresholds`, `statutory_gst_rates` each have allowlist+bounds checks that are untested for rejection paths.

`scripts/benchmark_stress.py` is dev-only but imported in CI `uv sync --all-extras` — 0% is acceptable if marked `pragma: no cover`.

## Desired End State

- `_validate_patch` and `apply_compliance_patch` (including rollback path) covered to ≥90% branch coverage.
- `discover_statutory_rules` happy paths + offline fallback covered to ≥70%.
- `benchmark_stress.py` either covered by a smoke invocation or explicitly `pragma: no cover` so it doesn't drag total.
- Total `scripts/` coverage ≥85% (stretch: 90%) without lowering the bar on other modules.

## Step-by-Step Implementation

1. **Read `scripts/compliance_radar.py:50-254` and `tests/test_compliance_radar.py:1-94` plus `scripts/discover_statutory_rules.py:79-193`.**
2. **Add `tests/test_compliance_radar_validation.py` (new file):**
   - For each allowlisted key, test **rejection**: non-allowlisted top key, `b2cl_threshold` out of bounds (value 1000, 600000), `interest_rates` NaN/Inf/bool/negative-out-of-range, `late_fee_caps` Inf string, `drc` percentage >100 and amount ≤0, `statutory_gst_rates` non-list / NaN element / bool element, `table_12_hsn_b2b_b2c_split` non-bool `mandatory`.
   - `apply_compliance_patch` — stage invalid patch → `return False`, file unchanged (read before/after). Stage valid patch → `save_rules_manifest` called, `run_self_verification` mocked to True → committed; mocked to False → rollback restores backup.
   - Mock `run_self_verification` to avoid 14s full suite per case; also add one integration smoke with real `run_self_verification` behind `@pytest.mark.slow` if desired, gated by env var.
   - Cover `print_status` (capture stdout).
   - Cover `main()` `--status`, `--verify-rules`, `--apply` arg parsing via `unittest.mock.patch`.

3. **Add `tests/test_discover_rules.py`:**
   - `fetch_portal_advisories(live=False)` → returns bundled snapshot, `mode=="bundled_snapshot"`.
   - `scan_for_regulatory_updates` dedup + keyword matching → `requires_review` entries.
   - `run_discovery(live=False, save_patch=tmp)` → writes patch JSON with `discovered_triggers`.

4. **Handle `benchmark_stress.py`:** add `# pragma: no cover` to `generate_synthetic_workload` / `main()` or move to `dev` extra and exclude from `tool.coverage.run.omit` in `pyproject.toml`:
   ```toml
   [tool.coverage.run]
   omit = ["tests/*", "scripts/benchmark_stress.py", "scripts/fuzz_gst_engine.py"]
   ```
   Only omit the benchmark; keep `fuzz_gst_engine.py` covered (already 90%) — don't omit it.

5. **Gate check:** run `uv run pytest --cov=scripts --cov-report=term --cov-report=html` and assert `compliance_radar >= 85%`, `discover >= 70%`, total >= 85%.

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov          # fast gate: new tests pass
uv run pytest --cov=scripts --cov-report=term  # coverage gate: totals ≥85%
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

## Out of Scope

- Changing patch validation logic (only adding tests).
- Refactoring `compliance_radar` to be more testable beyond mocking.
- Load/stress performance tuning.
- QRMP, PDF, portal gates.

## STOP Conditions

- If mocking `run_self_verification` hides a real subprocess bug (e.g., `-o addopts=` override) — keep one unmocked smoke test that actually runs `pytest tests.unit` subset.
- If coverage target forces testing of `benchmark_stress` synthetic generation at 500k records (slow) — omit it via pragma, not by slowing CI.
- If any gate fails due to unrelated pre-existing red — isolate.
