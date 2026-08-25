# Plan 08 — PDF Statement Table 4(C) Net Understates When RCM/ISD/IMPG Present

**Finding #8 — Category: Correctness (display) | Impact M-LOW (RCM/ISD taxpayers) | Effort S | Confidence MED-HIGH**
**Evidence:** `scripts/generate_pdf_statement.py:224-268`

## Current State

`scripts/generate_pdf_statement.py:223-268`
```python
itc = g3b_data.get("itc", {})
avail = itc.get("available", {}).get("all_other", {})   # ← only A5
rev = itc.get("reversed", {}).get("permanent_17_5_rules", {})  # ← only B1
avl_i = float(avail.get("iamt", 0.0)); ...
rev_i = float(rev.get("iamt", 0.0)); ...
net_itc_i=max(0.0, avl_i - rev_i)  # ← Table 4(C) in template
```

Template `HTML_TEMPLATE_GSTR3B` labels row `Table 4(C) Net Available ITC` but value is `A5 − B1` only. Real `Table 4(C)` per `reconcile_gstr2b.py:869-880` is:
```
4C = A1(import) + A3(RCM) + A4(ISD) + A5(all_other) − B1(17(5)) − B2(Rule37)
```
When bridge populates RCM/ISD/IMPG (non-zero for importers/RCM taxpayers), the statement's 4C is understated; challan still correct via optimizer, so statement vs challan disagree.

## Desired End State

- `generate_pdf()` computes `net_itc_*` exactly as reconcile's `table_4_c_net_itc` (include all A heads minus both B heads), or reuses `optimize_from_input_dict`'s ITC totals if already available.
- Template row still labeled `Table 4(C) Net Available ITC` but now correct for RCM/ISD importers.
- Optional: show breakdown rows for A1/A3/A4 when non-zero (nice-to-have, not required).

## Step-by-Step Implementation

1. **Read `scripts/generate_pdf_statement.py:210-271` and `scripts/reconcile_gstr2b.py:839-880` to confirm canonical 4C formula.**
2. **Edit `scripts/generate_pdf_statement.py:223-268`:**

   Replace the 6-line avail/rev extraction with:

   ```python
   itc = g3b_data.get("itc", {})
   avail = itc.get("available", {})
   rev = itc.get("reversed", {})
   # Sum all Table 4(A) heads: import_goods, import_services, rcm_inward, isd, all_other
   def _sum_itc(bucket: dict, heads: list[str]) -> dict[str, float]:
       out = {"iamt":0.0,"camt":0.0,"samt":0.0,"csamt":0.0}
       for h in heads:
           node = bucket.get(h, {}) if isinstance(bucket, dict) else {}
           for k in out:
               out[k] += float(node.get(k, 0.0) or 0.0)
       return out
   avail_sum = _sum_itc(avail, ["import_goods","import_services","rcm_inward","isd","all_other"])
   rev_sum = _sum_itc(rev, ["permanent_17_5_rules","temporary_others","permanent_others","temporary_37"])
   # canonical keys are permanent_17_5_rules + temporary_others; support alt names defensively
   avl_i, avl_c, avl_s, avl_cs = avail_sum["iamt"], avail_sum["camt"], avail_sum["samt"], avail_sum["csamt"]
   rev_i, rev_c, rev_s, rev_cs = rev_sum["iamt"], rev_sum["camt"], rev_sum["samt"], rev_sum["csamt"]
   net_itc_i=max(0.0, avl_i - rev_i)  # etc. — same 4 lines but now over full sums
   ```

   Keep variable names `avl_i` etc. so template render unchanged. Alternatively, keep separate section rows: pass `isd/rcm/impg` aggregates to template if expanding the table — but minimal fix is the 4-line net correction above.

   Also update the template row label if expanding: keep `Table 4(C)` label; optionally add footnotes for included heads.

3. **Add tests** `tests/test_pdf_statement_4c.py`:
   - Input with `rcm_inward iamt=10000, import_goods iamt=5000, all_other iamt=20000, rev B1=2000, B2=3000` → assert `net_itc_i == 10000+5000+20000-2000-3000 == 30,000`.
   - Zero-RCM case → unchanged (regression).
   - Render HTML contains `30000.00` for that case.
4. **Run gates.**

## Verified Pass/Fail Gates

```bash
uv run pytest -q --no-cov
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Manual probe:

```bash
python3 -c "
import json
from scripts.generate_pdf_statement import generate_pdf
import tempfile, os
data=json.load(open('examples/sample_gstr3b_portal.json'))  # adapt to gstr3b_input shape
# inject RCM 10k for test
data['itc']['available']['rcm_inward']={'iamt':10000,'camt':0,'samt':0,'csamt':0}
generate_pdf(data, '/tmp/test_state.pdf')
print(open('/tmp/test_state.html').read().count('30000'))
"
```

## Out of Scope

- Optimizer/challan math (already correct).
- Adding interest/late fee to statement (separate dues section — future).
- Full template redesign.

## STOP Conditions

- If `g3b_data` shape differs (portal shape `itc_elg` vs canonical `itc.available`) — the statement handles canonical; detect shape and branch, do not assume one.
- If `_sum_itc` double-counts because `rev` keys renamed in a merge — inspect actual keys on disk before summing.
- If any gate fails due to unrelated pre-existing red — isolate.
