# CA-reviewed preparation: implementation status

Updated 8 September 2026. The intended workflow is dependable preparation followed by one consolidated CA review. No numerical real-world accuracy percentage is claimed without an independently approved benchmark.

## Implemented

| Area | Corrected behaviour |
|---|---|
| Table 4 | Gross current credit includes amounts subsequently reversed; blocked and Rule 37 amounts are deducted once |
| Imports / ISD | Only matched, eligible records enter special credit buckets; unmatched documents are held |
| BoE identity | Preserve port code; match using document number, date and port; accept nested or flat BoE records |
| Matching | Check dates, taxable value and each tax head; trailing-number suggestions and unresolved ambiguity are held |
| Missing information | Missing book/2B dates are held; malformed purchase structures, invalid money and unsupported 2B sections fail explicitly |
| RCM | Cash liability survives blocked/ineligible credit; proposed ITC requires explicit payment confirmation; books-only RCM still creates liability |
| Outward bridge | Recipient-paid RCM is excluded from supplier liability; nested advances and explicitly classified zero-rated notes route correctly |
| Claim date | Pipeline forwards actual filing date into Section 16(4) evaluation; invalid supplied cutoffs fail; supplied annual-return filing dates restrict later fresh claims |
| Prior claims | An explicit previously-claimed flag prevents another automatic claim |
| HSN | Business-use decision replaces automatic code-only blocking; missing decisions for flagged categories are held |
| Rules | Support 40% from 22 September 2025 at format-validation level, and historical B2CL threshold before August 2024 |
| Reloads | Update the shared rate set in place; restore live constants after rollback; read current DRC configuration when comparing |
| Validation | Both portal serializers validate direct calls; notes, non-finite amounts, credentials and malformed containers are checked |
| Set-off | Reject negative/invalid ledger cases requiring a separate adjustment schedule instead of silently discarding negatives |
| Parsers | Reject conflicting invoice dates/POS and bad ageing; preserve RCM/BoE fields; reject unknown purchase JSON wrappers |
| Output | Stage and publish the complete pipeline run atomically; refuse existing output directories |
| Review | Produce one issue list, exact rule snapshot and source/output hashes; record local review and verify unchanged artifacts |
| Claims | DRC output describes internal comparisons, without notice predictions; statements are drafts, not CA certifications |
| Examples | Corrected the purchase CSV tax typo so the blocked purchase agrees with the JSON/2B sample |

The shared implementation is in [workflow.py](scripts/workflow.py); regression cases are in [test_ca_review_contract.py](tests/test_ca_review_contract.py). Existing tests that encoded automatic unmatched import claims, HSN-only blocking or single-axis matching were corrected. Invalid synthetic GSTINs/POS in serializer tests were corrected when direct validation became mandatory.

## Architectural choices

Keep a modular local Python application. Shared input contracts and atomic publication replace duplicated CLI coercion. Standard reconciliation is the source of tax classification; the fast matcher remains an explicitly exploratory tool and cannot populate a return through the bridge. Its exact-identity path now checks values/head differences as well.

Every pipeline run has an immutable-by-convention directory. Review hashes detect accidental changes; they are not cryptographic identity certificates or protection against an attacker who can rewrite the entire directory. `approve-run` records the named reviewer's explanation for every issue and never changes the calculated figures. `verify-run` checks the outputs and approval/manifest relationship.

## Limits that still require explicit professional handling

- **Benchmarking:** synthetic tests establish particular behaviours, not a measured 95–99% correct automatic-processing rate. Compare representative locally held cases against independently CA-approved results.
- **Statutory scope:** format rate validation is not an effective-dated HSN/SAC tax classification database. Due-date extensions, waivers, the correct annual-return filing date and specialised relief require professional verification.
- **History:** no persistent cross-period claim/reversal ledger is implemented. Supply prior-claim information and separately review reclaims, historical reversals and annual-return context.
- **Special schedules:** import services, complex amendments, IMS decisions, Rules 42/43/37A, ECO cases and other categories not fully derived from the supplied inputs need an explicit reviewed schedule. Negative liability/credit adjustment workflows are rejected rather than guessed.
- **Imports:** BoE matching is a GST-credit preparation aid, not customs clearance, duty assessment or an IMS client.
- **Numerics:** existing engines still contain float arithmetic with currency rounding. Boundary/property checks pass, but a complete Decimal-domain migration has not been performed.
- **Distribution:** the documented installation is a repository checkout. Standalone wheel resource packaging and a local browser interface remain separate development work.
- **External acceptance:** local JSON contracts are not official portal certification. Validate against applicable GST Portal tooling and retain actual filing receipts.

These limits are surfaced in documentation and the run's context review issues; approving a draft must not be interpreted as the software having automatically verified them.

## Validation commands

```bash
uv run ruff check .
uv run mypy scripts/
uv run pytest -q
uv run gstr-wala pipeline --sales examples/sample_sales_register.json \
  --purchases examples/sample_purchase_register.json --gstr2b examples/sample_gstr2b.json \
  --output-dir output/fresh-run --no-pdf
uv run gstr-wala verify-run output/fresh-run
```

## Public statutory references

- [GSTN Table 4 advisory](https://tutorial.gst.gov.in/downloads/news/advisory_of_label_change_in_GSTR_3B_02_09_2022.pdf): distinguishes availment, reversal and net-credit reporting.
- [CBIC Notification 9/2025–Integrated Tax (Rate)](https://courier.cbic.gov.in/advisory/2025/NOTIFICATION%20NO.%209_2025-INTEGRATED%20TAX%20%28RATE%29%20-1759486719.pdf): source for the 2025 rate schedule; specific supply classification still requires review.
- [GST Portal BoE guide](https://tutorial.gst.gov.in/userguide/taxpayersdashboard/Manual_boe.htm): documentary identifiers for import investigations.
- [Current GSTR-3B guide](https://tutorial.gst.gov.in/userguide/returns/GSTR3B.htm): use for the actual portal workflow and current reporting behaviour.
