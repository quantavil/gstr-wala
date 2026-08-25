# Plan 06 — SKILL.md Absolute file:// Links Leak Username + Break Portability

**Finding #6 (doc hygiene) — Category: Docs/DX | Impact LOW | Effort S | Confidence HIGH**
**Evidence:** `SKILL.md:233-241`

## Current State

`SKILL.md:233-241`
```markdown
| [`references/gstr1-table-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/gstr1-table-guide.md) | Explaining or validating any GSTR-1 table ... |
| [`references/gstr3b-table-guide.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/gstr3b-table-guide.md) | ... |
| [`references/itc-rules-and-setoff.md`](file:///home/quantavil/Documents/Project/gstr-wala/references/itc-rules-and-setoff.md) | ... |
| ... 8 more rows with `file:///home/quantavil/Documents/Project/gstr-wala/references/...` |
```

Every Reference Index link is an absolute `file://` URL containing the author's home path. Cloned on any other machine or via `pip`/`skill install`, the links are dead and leak `quantavil`.

## Desired End State

- All Reference Index links are repo-relative (portable): `references/gstr1-table-guide.md` or `./references/...` or plain `references/...`.
- No `file://` or `/home/quantavil` strings remain in `SKILL.md`.
- Markdown renders correctly in GitHub and in Claude Code/Codex skill renderers.

## Step-by-Step Implementation

1. **Read `SKILL.md:229-243` fully.**
2. **Edit `SKILL.md:233-241`** — replace each `](file:///home/quantavil/Documents/Project/gstr-wala/references/` with `](references/` (or `](./references/` — pick one and apply uniformly). Example:
   ```markdown
   | [`references/gstr1-table-guide.md`](references/gstr1-table-guide.md) | Explaining or validating any GSTR-1 table ... |
   ```
   Do for all 8-9 rows. Ensure table pipes remain aligned.
3. **Grep to confirm:** `grep -n "file://" SKILL.md` → 0 hits; `grep -n "quantavil" SKILL.md` → 0 hits (except maybe author metadata — keep that).
4. **Run gates** (docs-only, but still gate):
   ```bash
   uv run pytest -q --no-cov
   uv run ruff check scripts/ tests/
   uv run mypy scripts/
   ```
   No test should break; optional doc-smoke: `grep -q "file://" SKILL.md && exit 1`.

## Out of Scope

- Plan 05 SKILL.md command fix (separate).
- README.md links (already relative).
- AGENT.md, references/* content.

## STOP Conditions

- If skill renderer requires `file://` absolute URLs (check Claude Code skill docs) — then keep `file://` but make path relative to skill dir (`file://./references/...`), not home-dir.
- If any gate fails due to unrelated pre-existing red — isolate.
