"""High-performance Tier-2 engine for large-scale GST processing.

Leverages:
  - `python-calamine`: Rust-backed Excel reader for reading multi-sheet .xlsx/.xls/.xlsb files at 15x speed.
  - `polars`: High-speed vectorized DataFrame engine for processing 100,000+ invoices with low RAM.
  - `rapidfuzz`: C++/SIMD-accelerated fuzzy string matching for near-duplicate and typo invoice matching.
"""

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import polars as pl
from python_calamine import CalamineWorkbook
from rapidfuzz import fuzz, process

from scripts.reconcile_gstr2b import normalize_inum, round_cur



def read_excel_calamine(filepath: str, sheet_index: int = 0) -> List[Dict[str, Any]]:
    """Reads Excel (.xlsx, .xls, .xlsb) using Rust-powered Calamine at maximum speed."""
    workbook = CalamineWorkbook.from_path(filepath)
    sheet_names = workbook.sheet_names
    if not sheet_names:
        return []

    sheet = workbook.get_sheet_by_name(sheet_names[sheet_index])
    rows = sheet.to_python()
    if not rows or len(rows) < 2:
        return []

    headers = [str(h).strip().lower() for h in rows[0]]
    from scripts.utils import excel_cell_to_str

    records = []
    for row in rows[1:]:
        record = {}
        for col_idx, val in enumerate(row):
            if col_idx < len(headers) and headers[col_idx]:
                # excel_cell_to_str: 1001.0 -> "1001" (kills ".0"-poisoned
                # invoice numbers), datetimes -> DD-MM-YYYY, None -> "".
                record[headers[col_idx]] = excel_cell_to_str(val)
        records.append(record)

    return records


def reconcile_polars_rapidfuzz(
    books_records: List[Dict[str, Any]],
    gstr2b_records: List[Dict[str, Any]],
    fuzzy_cutoff: float = 85.0
) -> Dict[str, Any]:
    """High-volume 2B reconciliation using Polars vectorized joins and RapidFuzz."""
    if not books_records or not gstr2b_records:
        return {
            "engine": "polars+rapidfuzz (Rust/C++ accelerated)",
            "total_books_records": len(books_records),
            "total_2b_records": len(gstr2b_records),
            "exact_join_count": 0,
            "fuzzy_matched_count": 0,
            "fuzzy_matches": [],
            "missing_in_2b_count": len(books_records),
            "unmatched_2b_count": len(gstr2b_records),
        }

    # Prepare Books DataFrame
    norm_books = []
    for idx, b in enumerate(books_records):
        norm_books.append({
            "book_id": idx,
            "ctin": str(b.get("ctin", "")).strip().upper(),
            "inum": str(b.get("inum", "")).strip(),
            "norm_inum": normalize_inum(str(b.get("inum", ""))),
            "txval": float(b.get("txval", 0.0)),
            "iamt": float(b.get("iamt", 0.0)),
            "camt": float(b.get("camt", 0.0)),
            "samt": float(b.get("samt", 0.0)),
            "csamt": float(b.get("csamt", 0.0)),
            "tot_tax": round_cur(float(b.get("iamt", 0.0)) + float(b.get("camt", 0.0)) + float(b.get("samt", 0.0)) + float(b.get("csamt", 0.0))),
            "is_blocked_17_5": bool(b.get("is_blocked_17_5", False)),
            "unpaid_days": int(b.get("unpaid_days", 0))
        })
    df_books = pl.DataFrame(norm_books)

    # Prepare 2B DataFrame
    norm_2b = []
    for idx, r in enumerate(gstr2b_records):
        norm_2b.append({
            "g2b_id": idx,
            "ctin": str(r.get("ctin", "")).strip().upper(),
            "inum": str(r.get("inum", "")).strip(),
            "norm_inum": normalize_inum(str(r.get("inum", ""))),
            "txval": float(r.get("txval", 0.0)),
            "iamt": float(r.get("iamt", 0.0)),
            "camt": float(r.get("camt", 0.0)),
            "samt": float(r.get("samt", 0.0)),
            "csamt": float(r.get("csamt", 0.0)),
            "tot_tax": round_cur(float(r.get("iamt", 0.0)) + float(r.get("camt", 0.0)) + float(r.get("samt", 0.0)) + float(r.get("csamt", 0.0))),
            "itcavl": str(r.get("itcavl", "Y")),
            "rchrg": str(r.get("rchrg", "N"))
        })
    df_2b = pl.DataFrame(norm_2b)

    # Fast Exact Join on (ctin, norm_inum)
    exact_joined = df_books.join(
        df_2b,
        on=["ctin", "norm_inum"],
        how="inner",
        suffix="_2b"
    )

    # Deduplicate many-to-many join: each g2b_id used at most once (keep first per g2b_id)
    matched_book_ids: set = set()
    matched_g2b_ids: set = set()
    if exact_joined.height > 0:
        for row in exact_joined.sort(["book_id", "g2b_id"]).iter_rows(named=True):
            if row["g2b_id"] not in matched_g2b_ids:
                matched_book_ids.add(row["book_id"])
                matched_g2b_ids.add(row["g2b_id"])
        # Keep only deduped pairs in exact_joined for consistency
        exact_joined = exact_joined.sort(["book_id", "g2b_id"]).unique(subset=["g2b_id"], keep="first")

    # Filter unmatched for RapidFuzz fuzzy candidate search
    unmatched_books = [b for b in norm_books if b["book_id"] not in matched_book_ids]
    unmatched_2b = [r for r in norm_2b if r["g2b_id"] not in matched_g2b_ids]

    fuzzy_matched = []
    # Build lookup of 2B normalized invoice numbers per GSTIN
    g2b_by_ctin: Dict[str, List[Dict[str, Any]]] = {}
    for r in unmatched_2b:
        c_str = str(r["ctin"])
        if c_str not in g2b_by_ctin:
            g2b_by_ctin[c_str] = []
        g2b_by_ctin[c_str].append(r)

    for b in unmatched_books:
        c_str = str(b["ctin"])
        candidates = [r for r in g2b_by_ctin.get(c_str, []) if r["g2b_id"] not in matched_g2b_ids]
        if not candidates:
            continue

        cand_inums: List[str] = [str(r["norm_inum"]) for r in candidates]
        query_str = str(b["norm_inum"])
        best_match = process.extractOne(
            query_str,
            cand_inums,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=fuzzy_cutoff
        )

        if best_match:
            match_str, score, match_idx = best_match
            matched_r = candidates[int(match_idx)]
            matched_g2b_ids.add(matched_r["g2b_id"])
            matched_book_ids.add(b["book_id"])
            fuzzy_matched.append({
                "books_invoice": b,
                "gstr2b_invoice": matched_r,
                "fuzzy_similarity_score": score,
                "tax_diff": round_cur(abs(b["tot_tax"] - matched_r["tot_tax"]))
            })

    exact_matched_count = len(matched_book_ids) - len(fuzzy_matched)

    return {
        "engine": "polars+rapidfuzz (Rust/C++ accelerated)",
        "total_books_records": len(norm_books),
        "total_2b_records": len(norm_2b),
        "exact_join_count": exact_matched_count,
        "fuzzy_matched_count": len(fuzzy_matched),
        "fuzzy_matches": fuzzy_matched,
        "missing_in_2b_count": len(norm_books) - len(matched_book_ids),
        "unmatched_2b_count": len(norm_2b) - len(matched_g2b_ids)
    }
