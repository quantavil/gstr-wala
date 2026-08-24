#!/usr/bin/env python3
"""GSTR-2B vs Purchase Register (Books) 2-Way Reconciliation Engine.

Performs:
  - Alphanumeric invoice normalization (strips slashes, dashes, whitespace, leading zeroes)
  - Multi-tier matching: EXACT_MATCH, TOLERANCE_MATCH (+/- ₹1 tax), VALUE_MISMATCH, IN_BOOKS_ONLY, IN_2B_ONLY
  - Section 17(5) Blocked Credit identification -> Table 4(B)(1)
  - Rule 37 (180-day non-payment) proportional & full reversal -> Table 4(B)(2)
  - Inward RCM supplies (rchrg == 'Y') -> Table 4(A)(3)
  - Import of Goods (impg, impgsez) -> Table 4(A)(1)
  - ISD Invoices (isd, isda) -> Table 4(A)(4)
  - Credit Notes (cdnr, cdna) handling (reduces gross ITC)
  - Amended documents (b2ba, cdna, isda) superseding originals
  - 2B Ineligible credit (itcavl == 'N') & Section 16(4) time-limit gating -> Table 4(D)(2)
  - Auto-derivation of GSTR-3B Table 4 Eligible/Ineligible ITC fields

Usage:
  python3 scripts/reconcile_gstr2b.py <purchase_register.json> <gstr2b.json> [--json]
"""

import json
import os
import sys
from datetime import UTC, date, datetime
from typing import Any

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.utils import (
    extract_trailing_digits_cached as extract_trailing_digits,
)
from scripts.utils import (
    normalize_date_str,
    round_cur,
    safe_float,
    safe_int,
)
from scripts.utils import (
    normalize_inum_cached as normalize_inum,
)


def _parse_dmy_date(d_str: str) -> date:
    """Parses normalized DD-MM-YYYY string to a date object."""
    parts = d_str.split("-")
    return date(int(parts[2]), int(parts[1]), int(parts[0]))


def _is_section_16_4_expired(idt_str: str | None, cutoff_date_str: str | None = None) -> bool:
    """Evaluates whether an invoice date has passed the Section 16(4) ITC claim deadline.

    Under Section 16(4), ITC must be claimed on or before 30th November following
    the end of the financial year (FY) in which the invoice was issued.
    """
    if not idt_str or not str(idt_str).strip():
        return False
    try:
        norm_idt = normalize_date_str(str(idt_str).strip())
        inv_dt = _parse_dmy_date(norm_idt)
    except (ValueError, TypeError, IndexError):
        return False

    # Financial year in India runs April 1 to March 31
    fy_end_year = inv_dt.year if inv_dt.month <= 3 else inv_dt.year + 1
    deadline_date = date(fy_end_year, 11, 30)

    if cutoff_date_str and str(cutoff_date_str).strip():
        try:
            norm_cutoff = normalize_date_str(str(cutoff_date_str).strip())
            eval_date = _parse_dmy_date(norm_cutoff)
        except (ValueError, TypeError, IndexError):
            eval_date = datetime.now(UTC).date()
    else:
        eval_date = datetime.now(UTC).date()

    return eval_date > deadline_date


def _extract_item_amounts(itm: Any) -> tuple[float, float, float, float, float]:
    """Shape-tolerant extractor for GSTR-2B item amounts.

    Handles official GSTN portal nesting (item details inside `itm_det`)
    as well as legacy flat item structures.
    """
    if not isinstance(itm, dict):
        return 0.0, 0.0, 0.0, 0.0, 0.0
    raw_det = itm.get("itm_det")
    det: dict[str, Any] = raw_det if isinstance(raw_det, dict) else itm
    txval = safe_float(det.get("txval", 0.0))
    iamt = safe_float(det.get("iamt", 0.0))
    camt = safe_float(det.get("camt", 0.0))
    samt = safe_float(det.get("samt", 0.0))
    csamt = safe_float(det.get("csamt", 0.0))
    return txval, iamt, camt, samt, csamt


def flatten_gstr2b(g2b_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flattens nested official GSTR-2B JSON into a flat list of normalized invoice records.

    Handles original documents (b2b, cdnr, isd, impg, impgsez) and amendments
    (b2ba, cdna, isda). Shape-tolerant for both official GSTN portal nesting (itms[].itm_det)
    and flat item arrays. Amendments supersede original documents for the period.
    """
    data_block = g2b_data.get("data", {}).get("docdata", g2b_data.get("docdata", g2b_data))
    if not isinstance(data_block, dict):
        return []

    b2b_records: list[dict[str, Any]] = []
    b2ba_records: list[dict[str, Any]] = []
    cdnr_records: list[dict[str, Any]] = []
    cdna_records: list[dict[str, Any]] = []
    isd_records: list[dict[str, Any]] = []
    isda_records: list[dict[str, Any]] = []
    impg_records: list[dict[str, Any]] = []
    impgsez_records: list[dict[str, Any]] = []

    # 1. Process B2B Invoices
    for supplier in data_block.get("b2b", []):
        ctin = str(supplier.get("ctin", "")).strip().upper()
        trdnm = str(supplier.get("trdnm", ""))
        inv_list = supplier.get("inv") or supplier.get("invoices") or []
        for inv in inv_list:
            inum = str(inv.get("inum") or inv.get("inv_num") or inv.get("num") or "").strip()
            idt = str(inv.get("idt") or inv.get("dt") or inv.get("inv_dt") or "")
            val = safe_float(inv.get("val", 0.0))
            pos = str(inv.get("pos", ""))
            rchrg = str(inv.get("rev") or inv.get("rchrg") or "N")
            itcavl = str(inv.get("itcavl", "Y"))
            rsn = str(inv.get("rsn", ""))
            items = inv.get("itms") or inv.get("items") or []

            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                tx_i, i_i, c_i, s_i, cs_i = _extract_item_amounts(itm)
                txval += tx_i
                iamt += i_i
                camt += c_i
                samt += s_i
                csamt += cs_i

            norm = normalize_inum(inum)
            b2b_records.append({
                "source": "GSTR-2B",
                "section": "B2B",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": inum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": idt,
                "val": val,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 1b. Process B2BA (Amended B2B Invoices)
    for supplier in data_block.get("b2ba", []):
        ctin = str(supplier.get("ctin", "")).strip().upper()
        trdnm = str(supplier.get("trdnm", ""))
        inv_list = supplier.get("inv") or supplier.get("invoices") or []
        for inv in inv_list:
            inum = str(inv.get("inum") or inv.get("inv_num") or inv.get("num") or "").strip()
            oinum = str(inv.get("oinum") or inv.get("oinv_num") or inv.get("onum") or "").strip()
            idt = str(inv.get("idt") or inv.get("dt") or inv.get("inv_dt") or "")
            oidt = str(inv.get("oidt") or inv.get("odt") or inv.get("oinv_dt") or "")
            val = safe_float(inv.get("val", 0.0))
            pos = str(inv.get("pos", ""))
            rchrg = str(inv.get("rev") or inv.get("rchrg") or "N")
            itcavl = str(inv.get("itcavl", "Y"))
            rsn = str(inv.get("rsn", ""))
            items = inv.get("itms") or inv.get("items") or []

            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                tx_i, i_i, c_i, s_i, cs_i = _extract_item_amounts(itm)
                txval += tx_i
                iamt += i_i
                camt += c_i
                samt += s_i
                csamt += cs_i

            norm = normalize_inum(inum)
            b2ba_records.append({
                "source": "GSTR-2B",
                "section": "B2BA",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": inum,
                "oinum": oinum,
                "oidt": oidt,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": idt,
                "val": val,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 2. Process Credit / Debit Notes (cdnr)
    for supplier in data_block.get("cdnr", []):
        ctin = str(supplier.get("ctin", "")).strip().upper()
        trdnm = str(supplier.get("trdnm", ""))
        nt_list = supplier.get("nt") or supplier.get("notes") or []
        for nt in nt_list:
            nt_num = str(nt.get("nt_num") or nt.get("inum") or nt.get("num") or "").strip()
            nt_dt = str(nt.get("dt") or nt.get("nt_dt") or nt.get("idt") or "")
            ntty = str(nt.get("ntty", "C"))  # C: Credit Note, D: Debit Note
            val = safe_float(nt.get("val", 0.0))
            pos = str(nt.get("pos", ""))
            rchrg = str(nt.get("rev") or nt.get("rchrg") or "N")
            itcavl = str(nt.get("itcavl", "Y"))
            rsn = str(nt.get("rsn", ""))
            items = nt.get("itms") or nt.get("items") or []

            sign = -1.0 if ntty == "C" else 1.0
            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                tx_i, i_i, c_i, s_i, cs_i = _extract_item_amounts(itm)
                txval += tx_i * sign
                iamt += i_i * sign
                camt += c_i * sign
                samt += s_i * sign
                csamt += cs_i * sign

            norm = normalize_inum(nt_num)
            cdnr_records.append({
                "source": "GSTR-2B",
                "section": "CDNR",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": nt_num,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": nt_dt,
                "val": val * sign,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "ntty": ntty,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 2b. Process CDNA (Amended Credit / Debit Notes)
    for supplier in data_block.get("cdna", []):
        ctin = str(supplier.get("ctin", "")).strip().upper()
        trdnm = str(supplier.get("trdnm", ""))
        nt_list = supplier.get("nt") or supplier.get("notes") or []
        for nt in nt_list:
            nt_num = str(nt.get("nt_num") or nt.get("inum") or nt.get("num") or "").strip()
            ont_num = str(nt.get("ont_num") or nt.get("oinum") or nt.get("onum") or "").strip()
            nt_dt = str(nt.get("dt") or nt.get("nt_dt") or nt.get("idt") or "")
            ont_dt = str(nt.get("ont_dt") or nt.get("odt") or nt.get("oidt") or "")
            ntty = str(nt.get("ntty", "C"))
            val = safe_float(nt.get("val", 0.0))
            pos = str(nt.get("pos", ""))
            rchrg = str(nt.get("rev") or nt.get("rchrg") or "N")
            itcavl = str(nt.get("itcavl", "Y"))
            rsn = str(nt.get("rsn", ""))
            items = nt.get("itms") or nt.get("items") or []

            sign = -1.0 if ntty == "C" else 1.0
            txval, iamt, camt, samt, csamt = 0.0, 0.0, 0.0, 0.0, 0.0
            for itm in items:
                tx_i, i_i, c_i, s_i, cs_i = _extract_item_amounts(itm)
                txval += tx_i * sign
                iamt += i_i * sign
                camt += c_i * sign
                samt += s_i * sign
                csamt += cs_i * sign

            norm = normalize_inum(nt_num)
            cdna_records.append({
                "source": "GSTR-2B",
                "section": "CDNA",
                "ctin": ctin,
                "trdnm": trdnm,
                "inum": nt_num,
                "ont_num": ont_num,
                "ont_dt": ont_dt,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": nt_dt,
                "val": val * sign,
                "pos": pos,
                "rchrg": rchrg,
                "itcavl": itcavl,
                "rsn": rsn,
                "ntty": ntty,
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 3. Process Input Service Distributor (isd)
    for isd_sup in data_block.get("isd", []):
        ctin = str(isd_sup.get("ctin", "")).strip().upper()
        doc_list = isd_sup.get("doclist") or isd_sup.get("docs") or []
        for doc in doc_list:
            docnum = str(doc.get("docnum") or doc.get("inum") or doc.get("num") or "").strip()
            docdt = str(doc.get("docdt") or doc.get("dt") or doc.get("idt") or "")
            iamt = safe_float(doc.get("iamt", 0.0))
            camt = safe_float(doc.get("camt", 0.0))
            samt = safe_float(doc.get("samt", 0.0))
            csamt = safe_float(doc.get("csamt", 0.0))
            norm = normalize_inum(docnum)
            isd_records.append({
                "source": "GSTR-2B",
                "section": "ISD",
                "ctin": ctin,
                "inum": docnum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": docdt,
                "itcavl": str(doc.get("itcavl", "Y")),
                "txval": 0.0,
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 3b. Process ISDA (Amended ISD)
    for isd_sup in data_block.get("isda", []):
        ctin = str(isd_sup.get("ctin", "")).strip().upper()
        doc_list = isd_sup.get("doclist") or isd_sup.get("docs") or []
        for doc in doc_list:
            docnum = str(doc.get("docnum") or doc.get("inum") or doc.get("num") or "").strip()
            odocnum = str(doc.get("odocnum") or doc.get("oinum") or doc.get("onum") or "").strip()
            docdt = str(doc.get("docdt") or doc.get("dt") or doc.get("idt") or "")
            odocdt = str(doc.get("odocdt") or doc.get("odt") or doc.get("oidt") or "")
            iamt = safe_float(doc.get("iamt", 0.0))
            camt = safe_float(doc.get("camt", 0.0))
            samt = safe_float(doc.get("samt", 0.0))
            csamt = safe_float(doc.get("csamt", 0.0))
            norm = normalize_inum(docnum)
            isda_records.append({
                "source": "GSTR-2B",
                "section": "ISDA",
                "ctin": ctin,
                "inum": docnum,
                "odocnum": odocnum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": docdt,
                "odocdt": odocdt,
                "itcavl": str(doc.get("itcavl", "Y")),
                "txval": 0.0,
                "iamt": round_cur(iamt),
                "camt": round_cur(camt),
                "samt": round_cur(samt),
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + camt + samt + csamt)
            })

    # 4. Process Import of Goods (impg)
    for imp in data_block.get("impg", []):
        boe_list = imp.get("boe") or imp.get("boes") or []
        for boe in boe_list:
            boenum = str(boe.get("boenum") or boe.get("inum") or boe.get("num") or "").strip()
            boedt = str(boe.get("boedt") or boe.get("dt") or boe.get("idt") or "")
            txval, iamt, csamt = 0.0, 0.0, 0.0
            items = boe.get("itms") or boe.get("items") or []
            if items:
                for itm in items:
                    tx_i, i_i, _, _, cs_i = _extract_item_amounts(itm)
                    txval += tx_i
                    iamt += i_i
                    csamt += cs_i
            else:
                txval = safe_float(boe.get("txval", 0.0))
                iamt = safe_float(boe.get("iamt", 0.0))
                csamt = safe_float(boe.get("csamt", 0.0))

            norm = normalize_inum(boenum)
            impg_records.append({
                "source": "GSTR-2B",
                "section": "IMPG",
                "ctin": "ICEGATE",
                "inum": boenum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": boedt,
                "itcavl": str(boe.get("itcavl", "Y")),
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": 0.0,
                "samt": 0.0,
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + csamt)
            })

    # 4b. Process Import from SEZ (impgsez) — preserve distinct IMPGSEZ section label
    for imp in data_block.get("impgsez", []):
        boe_list = imp.get("boe") or imp.get("boes") or []
        for boe in boe_list:
            boenum = str(boe.get("boenum") or boe.get("inum") or boe.get("num") or "").strip()
            boedt = str(boe.get("boedt") or boe.get("dt") or boe.get("idt") or "")
            txval, iamt, csamt = 0.0, 0.0, 0.0
            items = boe.get("itms") or boe.get("items") or []
            if items:
                for itm in items:
                    tx_i, i_i, _, _, cs_i = _extract_item_amounts(itm)
                    txval += tx_i
                    iamt += i_i
                    csamt += cs_i
            else:
                txval = safe_float(boe.get("txval", 0.0))
                iamt = safe_float(boe.get("iamt", 0.0))
                csamt = safe_float(boe.get("csamt", 0.0))

            norm = normalize_inum(boenum)
            impgsez_records.append({
                "source": "GSTR-2B",
                "section": "IMPGSEZ",
                "ctin": "ICEGATE",
                "inum": boenum,
                "norm_inum": norm,
                "trailing_digits": extract_trailing_digits(norm),
                "idt": boedt,
                "itcavl": str(boe.get("itcavl", "Y")),
                "txval": round_cur(txval),
                "iamt": round_cur(iamt),
                "camt": 0.0,
                "samt": 0.0,
                "csamt": round_cur(csamt),
                "tot_tax": round_cur(iamt + csamt)
            })

    # Deduplicate superseded original records where an amendment exists
    superseded_b2b: set[tuple[str, str]] = set()
    for r in b2ba_records:
        orig = r.get("oinum") or r.get("inum")
        if orig:
            superseded_b2b.add((r["ctin"], normalize_inum(orig)))

    superseded_cdnr: set[tuple[str, str]] = set()
    for r in cdna_records:
        orig = r.get("ont_num") or r.get("inum")
        if orig:
            superseded_cdnr.add((r["ctin"], normalize_inum(orig)))

    superseded_isd: set[tuple[str, str]] = set()
    for r in isda_records:
        orig = r.get("odocnum") or r.get("inum")
        if orig:
            superseded_isd.add((r["ctin"], normalize_inum(orig)))

    filtered_b2b = [r for r in b2b_records if (r["ctin"], r["norm_inum"]) not in superseded_b2b]
    filtered_cdnr = [r for r in cdnr_records if (r["ctin"], r["norm_inum"]) not in superseded_cdnr]
    filtered_isd = [r for r in isd_records if (r["ctin"], r["norm_inum"]) not in superseded_isd]

    return (
        filtered_b2b
        + b2ba_records
        + filtered_cdnr
        + cdna_records
        + filtered_isd
        + isda_records
        + impg_records
        + impgsez_records
    )


def _classify_books_invoice(
    pr_inv: dict[str, Any], _16_4_cutoff: str | None = None
) -> tuple[bool, bool, bool, float, float]:
    """Classifies books invoice for 17(5) blocked, Rule 37 (180-day), and Section 16(4) time-limit.

    Returns (is_blocked, is_unpaid_180, is_16_4_expired, tot_tax, txval).
    """
    txval = safe_float(pr_inv.get("txval", 0.0))
    iamt = safe_float(pr_inv.get("iamt", 0.0))
    camt = safe_float(pr_inv.get("camt", 0.0))
    samt = safe_float(pr_inv.get("samt", 0.0))
    csamt = safe_float(pr_inv.get("csamt", 0.0))
    tot_tax = round_cur(iamt + camt + samt + csamt)

    is_blocked = bool(pr_inv.get("is_blocked_17_5", False)) or (
        str(pr_inv.get("hsn_sc", "")).strip() in ["8702", "8703", "9963", "9965"]
    )
    ud = safe_int(pr_inv.get("unpaid_days", 0))
    is_unpaid_180 = ud > 180 or bool(pr_inv.get("rule_37_reversal"))

    date_raw = pr_inv.get("idt") or pr_inv.get("date") or pr_inv.get("invoice_date") or ""
    is_16_4_expired = _is_section_16_4_expired(str(date_raw), _16_4_cutoff)

    return is_blocked, is_unpaid_180, is_16_4_expired, tot_tax, txval


def _find_match_candidates(
    ctin: str,
    norm_in: str,
    trail_in: str,
    g2b_exact_map: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]],
    g2b_trailing_map: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]],
    matched_2b_indices: set[int],
) -> list[tuple[int, dict[str, Any]]]:
    """Finds candidate GSTR-2B records by exact normalized number or trailing digits."""
    candidates = [
        (idx, rec) for idx, rec in g2b_exact_map.get((ctin, norm_in), [])
        if idx not in matched_2b_indices
    ]
    if not candidates:
        candidates = [
            (idx, rec) for idx, rec in g2b_trailing_map.get((ctin, trail_in), [])
            if idx not in matched_2b_indices
        ]
    return candidates


def reconcile(
    purchase_register: list[dict[str, Any]],
    gstr2b_raw: dict[str, Any],
    _16_4_cutoff: str | None = None
) -> dict[str, Any]:
    """Reconciles Purchase Register against GSTR-2B records.

    Parameters:
      purchase_register: List of purchase invoices recorded in accounting books.
      gstr2b_raw: Raw official GSTR-2B JSON payload from the GST portal.
      _16_4_cutoff: Optional ISO or DD-MM-YYYY evaluation cutoff date for Section 16(4).
    """
    g2b_records = flatten_gstr2b(gstr2b_raw)

    matched: list[dict[str, Any]] = []
    tolerance_matched: list[dict[str, Any]] = []
    value_mismatches: list[dict[str, Any]] = []
    in_books_only: list[dict[str, Any]] = []
    blocked_17_5: list[dict[str, Any]] = []
    rule_37_reversals: list[dict[str, Any]] = []
    ineligible_2b: list[dict[str, Any]] = []
    rcm_inward_2b: list[dict[str, Any]] = []
    isd_inward_2b: list[dict[str, Any]] = []
    impg_inward_2b: list[dict[str, Any]] = []

    matched_2b_indices: set[int] = set()

    # Index 2B records by (ctin, norm_inum) and (ctin, trailing_digits)
    g2b_exact_map: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    g2b_trailing_map: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}

    for idx, rec in enumerate(g2b_records):
        key_exact = (rec["ctin"], rec["norm_inum"])
        if key_exact not in g2b_exact_map:
            g2b_exact_map[key_exact] = []
        g2b_exact_map[key_exact].append((idx, rec))

        key_trailing = (rec["ctin"], rec["trailing_digits"])
        if key_trailing not in g2b_trailing_map:
            g2b_trailing_map[key_trailing] = []
        g2b_trailing_map[key_trailing].append((idx, rec))

        # Index amended records by original doc number (oinum, ont_num, odocnum)
        orig_doc = rec.get("oinum") or rec.get("ont_num") or rec.get("odocnum")
        if orig_doc:
            norm_orig = normalize_inum(orig_doc)
            key_orig_exact = (rec["ctin"], norm_orig)
            if key_orig_exact not in g2b_exact_map:
                g2b_exact_map[key_orig_exact] = []
            if (idx, rec) not in g2b_exact_map[key_orig_exact]:
                g2b_exact_map[key_orig_exact].append((idx, rec))

            trail_orig = extract_trailing_digits(norm_orig)
            key_orig_trailing = (rec["ctin"], trail_orig)
            if key_orig_trailing not in g2b_trailing_map:
                g2b_trailing_map[key_orig_trailing] = []
            if (idx, rec) not in g2b_trailing_map[key_orig_trailing]:
                g2b_trailing_map[key_orig_trailing].append((idx, rec))

    for pr_inv in purchase_register:
        ctin = str(pr_inv.get("ctin", "")).strip().upper()
        inum = str(pr_inv.get("inum", "")).strip()
        norm_in = normalize_inum(inum)
        trail_in = extract_trailing_digits(norm_in)

        is_blocked, is_unpaid_180, is_16_4, tot_tax, txval = _classify_books_invoice(
            pr_inv, _16_4_cutoff
        )

        candidates = _find_match_candidates(
            ctin, norm_in, trail_in, g2b_exact_map, g2b_trailing_map, matched_2b_indices
        )

        if not candidates:
            # Not found in 2B
            item_record = {**pr_inv, "reason": "Missing in GSTR-2B (Supplier not filed GSTR-1 yet)"}
            in_books_only.append(item_record)
            continue

        # Sort candidates by tax amount and taxable value proximity to books invoice
        candidates.sort(
            key=lambda c: (
                abs(tot_tax - c[1]["tot_tax"]),
                abs(txval - c[1]["txval"])
            )
        )
        best_idx, best_2b = candidates[0]
        matched_2b_indices.add(best_idx)

        diff_tax = round_cur(abs(tot_tax - best_2b["tot_tax"]))
        diff_txval = round_cur(abs(txval - best_2b["txval"]))

        match_entry = {
            "books_invoice": pr_inv,
            "gstr2b_invoice": best_2b,
            "tax_diff": diff_tax,
            "txval_diff": diff_txval
        }

        # 1. Section 16(4) Time Limit Gate (Books side) -> Table 4(D)(2)
        if is_16_4:
            ineligible_2b.append({**match_entry, "reason": "Section 16(4) Time Limit Expired"})
            continue

        # 2. Inward RCM supplies (rchrg == 'Y') -> Table 4(A)(3) regardless of itcavl
        if best_2b.get("rchrg") == "Y":
            if is_blocked:
                blocked_17_5.append({**match_entry, "reason": "Section 17(5) Blocked Credit"})
            else:
                rcm_inward_2b.append({
                    **match_entry,
                    "itc_note": "claimable_only_after_rcm_cash_payment"
                })
            continue

        # 3. Non-RCM Ineligible in 2B flag (itcavl == 'N' / 'RS') -> Table 4(D)(2)
        if best_2b.get("itcavl") in ("N", "RS"):
            ineligible_2b.append({**match_entry, "reason": f"GSTR-2B Marked Ineligible: {best_2b.get('rsn', 'Restriction')}"})
            continue

        # 4. Section 17(5) Blocked Credit -> Table 4(B)(1)
        if is_blocked:
            blocked_17_5.append({**match_entry, "reason": "Section 17(5) Blocked Credit"})
            continue

        # 5. Rule 37 Reversals (> 180 Days Unpaid) -> Table 4(B)(2)
        if is_unpaid_180:
            unpaid_val_raw = (
                pr_inv.get("unpaid_value")
                if pr_inv.get("unpaid_value") is not None
                else pr_inv.get("unpaid_amount")
            )
            if unpaid_val_raw is not None:
                unpaid_val = safe_float(unpaid_val_raw)
                if unpaid_val <= 0.0:
                    # Fully paid consideration -> no Rule 37 reversal required
                    pass
                else:
                    # Proportional reversal: ratio = min(1.0, unpaid_val / (invoice_val + tax))
                    inv_total = safe_float(pr_inv.get("val", 0.0))
                    if inv_total <= 0.0:
                        inv_total = safe_float(pr_inv.get("txval", 0.0)) + tot_tax
                    if inv_total <= 0.0:
                        inv_total = safe_float(best_2b.get("val", 0.0)) or (
                            safe_float(best_2b.get("txval", 0.0)) + best_2b.get("tot_tax", 0.0)
                        )
                    ratio = min(1.0, unpaid_val / inv_total) if inv_total > 0.0 else 1.0

                    rev_i = round_cur(best_2b.get("iamt", 0.0) * ratio)
                    rev_c = round_cur(best_2b.get("camt", 0.0) * ratio)
                    rev_s = round_cur(best_2b.get("samt", 0.0) * ratio)
                    rev_cs = round_cur(best_2b.get("csamt", 0.0) * ratio)

                    rule_37_reversals.append({
                        **match_entry,
                        "reason": "Rule 37 Reversal (Unpaid > 180 days)",
                        "reversal_basis": "proportional",
                        "reversal_ratio": round(ratio, 4),
                        "unpaid_value": unpaid_val,
                        "reversed_amounts": {
                            "iamt": rev_i,
                            "camt": rev_c,
                            "samt": rev_s,
                            "csamt": rev_cs,
                            "total": round_cur(rev_i + rev_c + rev_s + rev_cs)
                        }
                    })
                    continue
            else:
                # Default: 100% full reversal assumed
                rule_37_reversals.append({
                    **match_entry,
                    "reason": "Rule 37 Reversal (Unpaid > 180 days)",
                    "reversal_basis": "full_unpaid_assumed",
                    "reversal_ratio": 1.0,
                    "reversed_amounts": {
                        "iamt": best_2b.get("iamt", 0.0),
                        "camt": best_2b.get("camt", 0.0),
                        "samt": best_2b.get("samt", 0.0),
                        "csamt": best_2b.get("csamt", 0.0),
                        "total": best_2b.get("tot_tax", 0.0)
                    }
                })
                continue

        # 6. Single-Axis Matching (tax_diff <= ₹1.00 is TOLERANCE_MATCH per guide)
        if diff_tax == 0.0 and diff_txval == 0.0:
            matched.append(match_entry)
        elif diff_tax <= 1.0:
            tolerance_matched.append(match_entry)
        else:
            value_mismatches.append(match_entry)

    # In 2B Only (Unmatched 2B records)
    in_2b_only = []
    unrecorded_purchases = []
    for idx, rec in enumerate(g2b_records):
        if idx not in matched_2b_indices:
            in_2b_only.append(rec)
            if rec["section"] in ("IMPG", "IMPGSEZ"):
                impg_inward_2b.append(rec)
            elif rec["section"] in ("ISD", "ISDA"):
                isd_inward_2b.append(rec)
            else:
                unrecorded_purchases.append(rec)

    # Calculate GSTR-3B Table 4 Amounts
    # Table 4(A)(1) Import of Goods (including SEZ imports)
    impg_i = sum(r.get("iamt", 0.0) for r in impg_inward_2b)
    impg_cs = sum(r.get("csamt", 0.0) for r in impg_inward_2b)

    # Table 4(A)(3) Inward RCM
    rcm_txval = sum(m["gstr2b_invoice"].get("txval", 0.0) for m in rcm_inward_2b)
    rcm_i = sum(m["gstr2b_invoice"].get("iamt", 0.0) for m in rcm_inward_2b)
    rcm_c = sum(m["gstr2b_invoice"].get("camt", 0.0) for m in rcm_inward_2b)
    rcm_s = sum(m["gstr2b_invoice"].get("samt", 0.0) for m in rcm_inward_2b)
    rcm_cs = sum(m["gstr2b_invoice"].get("csamt", 0.0) for m in rcm_inward_2b)

    # Table 4(A)(4) ISD
    isd_i = sum(r.get("iamt", 0.0) for r in isd_inward_2b)
    isd_c = sum(r.get("camt", 0.0) for r in isd_inward_2b)
    isd_s = sum(r.get("samt", 0.0) for r in isd_inward_2b)
    isd_cs = sum(r.get("csamt", 0.0) for r in isd_inward_2b)

    # Table 4(A)(5) All Other ITC (excluding RCM/ISD/IMPG)
    claim_i = sum(m["gstr2b_invoice"]["iamt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "IMPGSEZ", "ISD", "ISDA"]) + sum(min(safe_float(m["books_invoice"].get("iamt", 0.0)), m["gstr2b_invoice"]["iamt"]) for m in value_mismatches)
    claim_c = sum(m["gstr2b_invoice"]["camt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "IMPGSEZ", "ISD", "ISDA"]) + sum(min(safe_float(m["books_invoice"].get("camt", 0.0)), m["gstr2b_invoice"]["camt"]) for m in value_mismatches)
    claim_s = sum(m["gstr2b_invoice"]["samt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "IMPGSEZ", "ISD", "ISDA"]) + sum(min(safe_float(m["books_invoice"].get("samt", 0.0)), m["gstr2b_invoice"]["samt"]) for m in value_mismatches)
    claim_cs = sum(m["gstr2b_invoice"]["csamt"] for m in matched + tolerance_matched if m["gstr2b_invoice"]["section"] not in ["IMPG", "IMPGSEZ", "ISD", "ISDA"]) + sum(min(safe_float(m["books_invoice"].get("csamt", 0.0)), m["gstr2b_invoice"]["csamt"]) for m in value_mismatches)

    # Permanent Reversal Table 4(B)(1)
    rev_perm_i = sum(b["gstr2b_invoice"]["iamt"] for b in blocked_17_5)
    rev_perm_c = sum(b["gstr2b_invoice"]["camt"] for b in blocked_17_5)
    rev_perm_s = sum(b["gstr2b_invoice"]["samt"] for b in blocked_17_5)
    rev_perm_cs = sum(b["gstr2b_invoice"]["csamt"] for b in blocked_17_5)

    # Temporary Reversal Table 4(B)(2) (proportional or full)
    rev_temp_i = sum(r.get("reversed_amounts", {}).get("iamt", r["gstr2b_invoice"]["iamt"]) for r in rule_37_reversals)
    rev_temp_c = sum(r.get("reversed_amounts", {}).get("camt", r["gstr2b_invoice"]["camt"]) for r in rule_37_reversals)
    rev_temp_s = sum(r.get("reversed_amounts", {}).get("samt", r["gstr2b_invoice"]["samt"]) for r in rule_37_reversals)
    rev_temp_cs = sum(r.get("reversed_amounts", {}).get("csamt", r["gstr2b_invoice"]["csamt"]) for r in rule_37_reversals)

    # Ineligible Table 4(D)(2)
    inelg_i = sum(e["gstr2b_invoice"]["iamt"] for e in ineligible_2b)
    inelg_c = sum(e["gstr2b_invoice"]["camt"] for e in ineligible_2b)
    inelg_s = sum(e["gstr2b_invoice"]["samt"] for e in ineligible_2b)
    inelg_cs = sum(e["gstr2b_invoice"]["csamt"] for e in ineligible_2b)

    # Deferred ITC (Missing in 2B)
    def_i = sum(safe_float(b.get("iamt", 0.0)) for b in in_books_only)
    def_c = sum(safe_float(b.get("camt", 0.0)) for b in in_books_only)
    def_s = sum(safe_float(b.get("samt", 0.0)) for b in in_books_only)
    def_cs = sum(safe_float(b.get("csamt", 0.0)) for b in in_books_only)

    return {
        "summary": {
            "total_books_invoices": len(purchase_register),
            "total_2b_invoices": len(g2b_records),
            "exact_matched_count": len(matched),
            "tolerance_matched_count": len(tolerance_matched),
            "value_mismatch_count": len(value_mismatches),
            "in_books_only_count": len(in_books_only),
            "in_2b_only_count": len(unrecorded_purchases),
            "total_unmatched_2b_records": len(in_2b_only),
            "blocked_17_5_count": len(blocked_17_5),
            "rule_37_count": len(rule_37_reversals),
            "ineligible_2b_count": len(ineligible_2b),
            "rcm_inward_count": len(rcm_inward_2b),
            "isd_count": len(isd_inward_2b),
            "impg_count": len(impg_inward_2b)
        },
        "gstr3b_table_4_auto_population": {
            "table_4_a_1_import_goods": {
                "iamt": round_cur(impg_i), "csamt": round_cur(impg_cs), "total": round_cur(impg_i + impg_cs)
            },
            "table_4_a_3_rcm_inward": {
                "txval": round_cur(rcm_txval),
                "iamt": round_cur(rcm_i), "camt": round_cur(rcm_c), "samt": round_cur(rcm_s), "csamt": round_cur(rcm_cs),
                "total": round_cur(rcm_i + rcm_c + rcm_s + rcm_cs)
            },
            "table_4_a_4_isd": {
                "iamt": round_cur(isd_i), "camt": round_cur(isd_c), "samt": round_cur(isd_s), "csamt": round_cur(isd_cs),
                "total": round_cur(isd_i + isd_c + isd_s + isd_cs)
            },
            "table_4_a_5_all_other_itc": {
                "iamt": round_cur(claim_i), "camt": round_cur(claim_c), "samt": round_cur(claim_s), "csamt": round_cur(claim_cs),
                "total": round_cur(claim_i + claim_c + claim_s + claim_cs)
            },
            "table_4_b_1_permanent_reversals_17_5": {
                "iamt": round_cur(rev_perm_i), "camt": round_cur(rev_perm_c), "samt": round_cur(rev_perm_s), "csamt": round_cur(rev_perm_cs),
                "total": round_cur(rev_perm_i + rev_perm_c + rev_perm_s + rev_perm_cs)
            },
            "table_4_b_2_temporary_reversals_rule37": {
                "iamt": round_cur(rev_temp_i), "camt": round_cur(rev_temp_c), "samt": round_cur(rev_temp_s), "csamt": round_cur(rev_temp_cs),
                "total": round_cur(rev_temp_i + rev_temp_c + rev_temp_s + rev_temp_cs)
            },
            "table_4_c_net_itc": {
                "iamt": round_cur(claim_i + impg_i + rcm_i + isd_i - rev_perm_i - rev_temp_i),
                "camt": round_cur(claim_c + rcm_c + isd_c - rev_perm_c - rev_temp_c),
                "samt": round_cur(claim_s + rcm_s + isd_s - rev_perm_s - rev_temp_s),
                "csamt": round_cur(claim_cs + impg_cs + rcm_cs + isd_cs - rev_perm_cs - rev_temp_cs),
                "total": round_cur(
                    (claim_i + impg_i + rcm_i + isd_i - rev_perm_i - rev_temp_i) +
                    (claim_c + rcm_c + isd_c - rev_perm_c - rev_temp_c) +
                    (claim_s + rcm_s + isd_s - rev_perm_s - rev_temp_s) +
                    (claim_cs + impg_cs + rcm_cs + isd_cs - rev_perm_cs - rev_temp_cs)
                )
            },
            "table_4_d_2_ineligible_16_4": {
                "iamt": round_cur(inelg_i), "camt": round_cur(inelg_c), "samt": round_cur(inelg_s), "csamt": round_cur(inelg_cs),
                "total": round_cur(inelg_i + inelg_c + inelg_s + inelg_cs)
            },
            "deferred_itc_missing_in_2b": {
                "iamt": round_cur(def_i), "camt": round_cur(def_c), "samt": round_cur(def_s), "csamt": round_cur(def_cs),
                "total": round_cur(def_i + def_c + def_s + def_cs)
            }
        },
        "details": {
            "exact_matched": matched,
            "tolerance_matched": tolerance_matched,
            "value_mismatches": value_mismatches,
            "in_books_only": in_books_only,
            "in_2b_only": in_2b_only,
            "blocked_17_5": blocked_17_5,
            "rule_37_reversals": rule_37_reversals,
            "ineligible_2b": ineligible_2b,
            "rcm_inward_2b": rcm_inward_2b
        }
    }


def format_table(headers: list[str], rows: list[list[Any]]) -> str:
    from scripts.utils import format_table as _ft

    return _ft(headers, rows)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 reconcile_gstr2b.py <purchase_register.json> <gstr2b.json> [--json]")
        sys.exit(1)

    pr_file = sys.argv[1]
    g2b_file = sys.argv[2]
    json_output = "--json" in sys.argv

    if not os.path.exists(pr_file) or not os.path.exists(g2b_file):
        sys.exit("Error: Input files not found.")

    with open(pr_file, "r", encoding="utf-8") as f:
        pr_data = json.load(f)
    with open(g2b_file, "r", encoding="utf-8") as f:
        g2b_data = json.load(f)

    if isinstance(pr_data, dict):
        raw_list = pr_data.get("purchases") or pr_data.get("invoices") or []
        pr_list: list[dict[str, Any]] = raw_list if isinstance(raw_list, list) else []
    elif isinstance(pr_data, list):
        pr_list = pr_data
    else:
        pr_list = []

    result = reconcile(pr_list, g2b_data)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        s = result["summary"]
        t4 = result["gstr3b_table_4_auto_population"]
        print("=" * 70)
        print(" GSTR-2B vs PURCHASE REGISTER RECONCILIATION SUMMARY")
        print("=" * 70)
        summary_rows = [
            ["Total Invoices in Purchase Register (Books)", s["total_books_invoices"]],
            ["Total Invoices in GSTR-2B (Portal)", s["total_2b_invoices"]],
            ["Exact Matched Invoices", s["exact_matched_count"]],
            ["Tolerance Matched Invoices (tax within ±₹1)", s["tolerance_matched_count"]],
            ["Value Mismatches (Flagged)", s["value_mismatch_count"]],
            ["In Books Only (Rule 36(4) Deferred)", s["in_books_only_count"]],
            ["In 2B Only (Unrecorded Purchases)", s["in_2b_only_count"]],
            ["Section 17(5) Blocked Credit", s["blocked_17_5_count"]],
            ["Rule 37 Reversals (> 180 Days Unpaid)", s["rule_37_count"]],
            ["Ineligible in 2B (POS/16(4) Barred)", s["ineligible_2b_count"]],
            ["Inward RCM Supplies", s["rcm_inward_count"]]
        ]
        print(format_table(["Reconciliation Category", "Count"], summary_rows))

        print("\n[AUTO-DERIVED GSTR-3B TABLE 4 ITC VALUES]")
        t4_rows = [
            ["Table 4(A)(1) Import of Goods", f"₹{t4['table_4_a_1_import_goods']['iamt']:,.2f}", "-", "-", f"₹{t4['table_4_a_1_import_goods']['total']:,.2f}"],
            ["Table 4(A)(3) Inward RCM", f"₹{t4['table_4_a_3_rcm_inward']['iamt']:,.2f}", f"₹{t4['table_4_a_3_rcm_inward']['camt']:,.2f}", f"₹{t4['table_4_a_3_rcm_inward']['samt']:,.2f}", f"₹{t4['table_4_a_3_rcm_inward']['total']:,.2f}"],
            ["Table 4(A)(4) ISD Inward", f"₹{t4['table_4_a_4_isd']['iamt']:,.2f}", f"₹{t4['table_4_a_4_isd']['camt']:,.2f}", f"₹{t4['table_4_a_4_isd']['samt']:,.2f}", f"₹{t4['table_4_a_4_isd']['total']:,.2f}"],
            ["Table 4(A)(5) All Other ITC", f"₹{t4['table_4_a_5_all_other_itc']['iamt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['camt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['samt']:,.2f}", f"₹{t4['table_4_a_5_all_other_itc']['total']:,.2f}"],
            ["Table 4(B)(1) Permanent Reversal (17(5))", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['iamt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['camt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['samt']:,.2f}", f"₹{t4['table_4_b_1_permanent_reversals_17_5']['total']:,.2f}"],
            ["Table 4(B)(2) Temporary Reversal (Rule 37)", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['iamt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['camt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['samt']:,.2f}", f"₹{t4['table_4_b_2_temporary_reversals_rule37']['total']:,.2f}"],
            ["TABLE 4(C) NET AVAILABLE ITC", f"₹{t4['table_4_c_net_itc']['iamt']:,.2f}", f"₹{t4['table_4_c_net_itc']['camt']:,.2f}", f"₹{t4['table_4_c_net_itc']['samt']:,.2f}", f"₹{t4['table_4_c_net_itc']['total']:,.2f}"]
        ]
        print(format_table(["GSTR-3B Schedule", "IGST", "CGST", "SGST", "Total Net ITC"], t4_rows))

    sys.exit(0)


if __name__ == "__main__":
    main()
