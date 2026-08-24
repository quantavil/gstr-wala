"""High-performance Tier-2 engine for large-scale GST processing.

Leverages:
  - `python-calamine`: Rust-backed Excel reader for reading multi-sheet .xlsx/.xls/.xlsb files at 15x speed.
  - `polars`: High-speed vectorized DataFrame engine for processing 100,000+ invoices with low RAM.
  - `rapidfuzz`: C++/SIMD-accelerated fuzzy string matching for near-duplicate and typo invoice matching.
"""

from typing import Any

import polars as pl
from python_calamine import CalamineWorkbook
from rapidfuzz import fuzz

from scripts.reconcile_gstr2b import normalize_inum
from scripts.utils import excel_cell_to_str, round_cur, safe_float

PARITY_WARNING: str = (
    "fast engine skips 17(5)/Rule 37/RCM/16(4) classification — run slow engine for filing decisions"
)


def read_excel_calamine(filepath: str, sheet_index: int = 0) -> list[dict[str, Any]]:
    """Reads Excel (.xlsx, .xls, .xlsb) using Rust-powered Calamine at maximum speed."""
    workbook = CalamineWorkbook.from_path(filepath)
    sheet_names = workbook.sheet_names
    if not sheet_names:
        return []

    sheet = workbook.get_sheet_by_name(sheet_names[sheet_index])
    rows = sheet.to_python()
    if not rows or len(rows) < 2:
        return []

    raw_headers = rows[0]
    headers = [str(h).strip().lower() if h is not None else "" for h in raw_headers]

    # Validate against blank headers
    blank_indices = [idx for idx, h in enumerate(headers) if not h]
    if blank_indices:
        raise ValueError(f"Blank headers detected at column indices: {blank_indices}")

    # Validate against duplicate headers
    seen = set()
    duplicates = set()
    for h in headers:
        if h in seen:
            duplicates.add(h)
        seen.add(h)
    if duplicates:
        raise ValueError(f"Duplicate headers detected in Excel sheet: {sorted(duplicates)}")

    records = []
    for row in rows[1:]:
        record = {}
        for col_idx, val in enumerate(row):
            if col_idx < len(headers):
                record[headers[col_idx]] = excel_cell_to_str(val)
        records.append(record)

    return records


def reconcile_polars_rapidfuzz(
    books_records: list[dict[str, Any]],
    gstr2b_records: list[dict[str, Any]],
    fuzzy_cutoff: float = 85.0,
) -> dict[str, Any]:
    """High-volume 2B reconciliation using Polars vectorized joins and RapidFuzz.

    NOTE: Fast engine performs rapid invoice normalization, exact joining, and value-gated
    fuzzy matching for high data volumes (100k+ rows). It deliberately bypasses
    Section 17(5) blocked credit, Rule 37 180-day reversal, RCM Table 4(A)(3), and
    Section 16(4) time-limit classification. Use `reconcile_gstr2b.reconcile()` for
    statutory filing decisions.

    Value gate on fuzzy matching:
      A candidate with string similarity >= fuzzy_cutoff is only accepted if
      tax_diff <= max(2.0, 0.01 * max(book_tax, g2b_tax)).
      Near-miss candidates whose tax diff exceeds this tolerance are diverted to
      `value_mismatches` and excluded from `missing_in_2b_count`.
    """
    if not books_records or not gstr2b_records:
        return {
            "engine": "polars+rapidfuzz (Rust/C++ accelerated)",
            "classification_performed": False,
            "parity_warning": PARITY_WARNING,
            "total_books_records": len(books_records),
            "total_2b_records": len(gstr2b_records),
            "exact_join_count": 0,
            "fuzzy_matched_count": 0,
            "fuzzy_matches": [],
            "value_mismatch_count": 0,
            "value_mismatches": [],
            "missing_in_2b_count": len(books_records),
            "unmatched_2b_count": len(gstr2b_records),
        }

    # Prepare Books DataFrame with safe_float conversion
    norm_books = []
    for idx, b in enumerate(books_records):
        txval = safe_float(b.get("txval", 0.0))
        iamt = safe_float(b.get("iamt", 0.0))
        camt = safe_float(b.get("camt", 0.0))
        samt = safe_float(b.get("samt", 0.0))
        csamt = safe_float(b.get("csamt", 0.0))
        tot_tax = round_cur(iamt + camt + samt + csamt)
        inum = str(b.get("inum", "")).strip()
        norm_books.append({
            "book_id": idx,
            "ctin": str(b.get("ctin", "")).strip().upper(),
            "inum": inum,
            "norm_inum": normalize_inum(inum),
            "txval": txval,
            "iamt": iamt,
            "camt": camt,
            "samt": samt,
            "csamt": csamt,
            "tot_tax": tot_tax,
        })
    df_books = pl.DataFrame(norm_books)

    # Prepare 2B DataFrame with safe_float conversion
    norm_2b = []
    for idx, r in enumerate(gstr2b_records):
        txval = safe_float(r.get("txval", 0.0))
        iamt = safe_float(r.get("iamt", 0.0))
        camt = safe_float(r.get("camt", 0.0))
        samt = safe_float(r.get("samt", 0.0))
        csamt = safe_float(r.get("csamt", 0.0))
        tot_tax = round_cur(iamt + camt + samt + csamt)
        inum = str(r.get("inum", "")).strip()
        norm_2b.append({
            "g2b_id": idx,
            "ctin": str(r.get("ctin", "")).strip().upper(),
            "inum": inum,
            "norm_inum": normalize_inum(inum),
            "txval": txval,
            "iamt": iamt,
            "camt": camt,
            "samt": samt,
            "csamt": csamt,
            "tot_tax": tot_tax,
        })
    df_2b = pl.DataFrame(norm_2b)

    # Fast Exact Join on (ctin, norm_inum)
    exact_joined = df_books.join(
        df_2b,
        on=["ctin", "norm_inum"],
        how="inner",
        suffix="_2b"
    )

    matched_book_ids: set[Any] = set()
    matched_g2b_ids: set[Any] = set()
    if exact_joined.height > 0:
        for row in exact_joined.sort(["book_id", "g2b_id"]).iter_rows(named=True):
            if row["g2b_id"] not in matched_g2b_ids and row["book_id"] not in matched_book_ids:
                matched_book_ids.add(row["book_id"])
                matched_g2b_ids.add(row["g2b_id"])

    # Filter unmatched for RapidFuzz fuzzy candidate search
    unmatched_books = [b for b in norm_books if b["book_id"] not in matched_book_ids]
    unmatched_2b = [r for r in norm_2b if r["g2b_id"] not in matched_g2b_ids]

    # Build lookup of 2B normalized invoice numbers per GSTIN
    g2b_by_ctin: dict[str, list[dict[str, Any]]] = {}
    for r in unmatched_2b:
        c_str = str(r["ctin"])
        if c_str not in g2b_by_ctin:
            g2b_by_ctin[c_str] = []
        g2b_by_ctin[c_str].append(r)

    fuzzy_matched: list[dict[str, Any]] = []
    value_mismatches: list[dict[str, Any]] = []
    value_mismatch_book_ids: set[Any] = set()

    for b in unmatched_books:
        c_str = str(b["ctin"])
        candidates = [r for r in g2b_by_ctin.get(c_str, []) if r["g2b_id"] not in matched_g2b_ids]
        if not candidates:
            continue

        query_str = str(b["norm_inum"])

        # Score all available candidates
        scored_candidates = []
        for cand in candidates:
            cand_str = str(cand["norm_inum"])
            score = float(fuzz.token_sort_ratio(query_str, cand_str))
            if score >= fuzzy_cutoff:
                tax_diff = round_cur(abs(b["tot_tax"] - cand["tot_tax"]))
                scored_candidates.append((score, tax_diff, cand["g2b_id"], cand))

        if not scored_candidates:
            continue

        # Deterministic tie-breaking: (score DESC, tax_diff ASC, g2b_id ASC)
        scored_candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
        best_score, best_tax_diff, _best_g2b_id, best_cand = scored_candidates[0]

        # Value Gate: tax_diff <= max(2.0, 0.01 * max(book_tax, g2b_tax))
        allowed_tolerance = max(2.0, 0.01 * max(b["tot_tax"], best_cand["tot_tax"]))
        if best_tax_diff <= allowed_tolerance:
            # Accepted fuzzy match
            matched_g2b_ids.add(best_cand["g2b_id"])
            matched_book_ids.add(b["book_id"])
            fuzzy_matched.append({
                "books_invoice": b,
                "gstr2b_invoice": best_cand,
                "fuzzy_similarity_score": best_score,
                "tax_diff": best_tax_diff,
            })
        else:
            # Rejected near-miss: value mismatch
            value_mismatch_book_ids.add(b["book_id"])
            value_mismatches.append({
                "books_invoice": b,
                "best_candidate_2b": best_cand,
                "fuzzy_similarity_score": best_score,
                "tax_diff": best_tax_diff,
                "allowed_tolerance": round_cur(allowed_tolerance),
                "reason": "Tax difference exceeds value tolerance gate",
            })

    exact_matched_count = len(matched_book_ids) - len(fuzzy_matched)
    missing_in_2b_count = len(norm_books) - len(matched_book_ids) - len(value_mismatch_book_ids)
    unmatched_2b_count = len(norm_2b) - len(matched_g2b_ids)

    return {
        "engine": "polars+rapidfuzz (Rust/C++ accelerated)",
        "classification_performed": False,
        "parity_warning": PARITY_WARNING,
        "total_books_records": len(norm_books),
        "total_2b_records": len(norm_2b),
        "exact_join_count": exact_matched_count,
        "fuzzy_matched_count": len(fuzzy_matched),
        "fuzzy_matches": fuzzy_matched,
        "value_mismatch_count": len(value_mismatches),
        "value_mismatches": value_mismatches,
        "missing_in_2b_count": missing_in_2b_count,
        "unmatched_2b_count": unmatched_2b_count,
    }
