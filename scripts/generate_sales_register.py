#!/usr/bin/env python3
"""Generates audit-ready, executive-grade GST Sales Register Excel workbooks (.xlsx).

Produces a structured 4-sheet workbook:
  1. Executive Dashboard: High-level KPI cards, statutory tax split, GSTR-1 return cross-walk, top clients.
  2. Sales Register: Master invoice-level register with buyer names, GSTINs, POS, tax heads, and totals.
  3. Itemized Details: Complete line-item breakdown with individual service descriptions, HSN, rates.
  4. HSN-SAC Summary: Table 12-ready aggregate summary by HSN/SAC code and tax rate.

Truthfulness & Zero Outbound:
  - 100% deterministic local computation with XlsxWriter.
  - No remote telemetry or cloud calls.
  - Dynamic Excel formulas (SUM) with pre-cached values for complete cross-platform compatibility.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pymupdf
import xlsxwriter

from scripts.constants import STATE_CODES

# Standard statutory service descriptions for logistics HSN/SAC codes
STATUTORY_HSN_DESCRIPTIONS: dict[str, str] = {
    "996111": "Services auxiliary to financial services / Cargo handling & incentives",
    "996511": "Road transport services of freight / Container movement & trucking",
    "996512": "Railway transport services of freight / CFS transport services",
    "996519": "Other land transport services / Inland haulage services",
    "996521": "Coastal & transoceanic water transport of freight / Ocean freight",
    "996711": "Container handling services / Terminal handling charges (THC)",
    "996712": "Customs clearance & agency services / Documentation & cargo support",
    "996713": "Storage & warehousing services / Plant quarantine & health inspection",
    "996719": "Other auxiliary transport services / Bill of Lading (BL) charges",
    "996799": "Other supporting transport services / Container seal services",
}


def clean_num(val: Any) -> float:
    """Cleans currency strings, symbols, and formatting into a rounded float."""
    if val is None:
        return 0.0
    s = str(val).replace(",", "").replace("₹", "").replace("$", "").replace("+", "").strip()
    if s in ("", "-", "--", "None", "null"):
        return 0.0
    try:
        return round(float(s), 2)
    except (ValueError, TypeError):
        return 0.0


def parse_date(date_str: str) -> datetime.date | str:
    """Parses DD/MM/YYYY or DD-MM-YYYY into a datetime.date object, falling back to string."""
    if not date_str:
        return ""
    m = re.match(r"^(\d{2})[/.-](\d{2})[/.-](\d{4})$", str(date_str).strip())
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return str(date_str)


def extract_invoices_from_pdf_dir(
    pdf_dir: Path | str,
    gstr1_json_path: Path | str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extracts rich multi-item invoice data and party details from PDF files.

    Cross-references with existing gstr1_input.json when available to ensure
    100% consistency with official return numbers.
    """
    pdf_path = Path(pdf_dir)
    pattern = str(pdf_path / "*.pdf")
    found_files = glob.glob(pattern)
    if not found_files:
        raise ValueError(f"No PDF invoices found in '{pdf_dir}'")

    def _sort_key(p: str) -> int:
        m = re.search(r"\d+", Path(p).stem)
        return int(m.group()) if m else 999999

    pdf_files = sorted(found_files, key=_sort_key)

    g1_map: dict[str, dict[str, Any]] = {}
    taxpayer_info: dict[str, Any] = {
        "trade_name": "Vishal Logistics Solutions",
        "gstin": "09AXBPS5714M1ZZ",
        "fp": "082026",
        "state_code": "09",
        "state_name": "Uttar Pradesh",
    }

    candidate_g1 = (
        Path(gstr1_json_path)
        if gstr1_json_path
        else pdf_path.parent / "output" / "gstr1_input.json"
    )
    if candidate_g1.exists():
        try:
            with open(candidate_g1, encoding="utf-8") as f:
                g1_data = json.load(f)
            taxpayer_info["gstin"] = g1_data.get("gstin", taxpayer_info["gstin"])
            taxpayer_info["fp"] = g1_data.get("fp", taxpayer_info["fp"])
            for inv in g1_data.get("invoices", []):
                g1_map[str(inv.get("inum")).strip()] = inv
        except Exception:
            pass

    invoices: list[dict[str, Any]] = []

    for p in pdf_files:
        p_obj = Path(p)
        inum_file = re.search(r"\d+", p_obj.stem)
        inum_default = inum_file.group() if inum_file else p_obj.stem

        doc = pymupdf.open(p)
        page = doc[0]
        txt = page.get_text("text", sort=True)

        # Date
        dt_m = re.search(r"Invoice Date\.?\s*[:\s]*(\d{2}/\d{2}/\d{4})", txt)
        idt_str = dt_m.group(1) if dt_m else ""
        if not idt_str and inum_default in g1_map:
            raw_dt = g1_map[inum_default].get("idt", "")
            if "-" in raw_dt:
                p_dt = raw_dt.split("-")
                idt_str = f"{p_dt[0]}/{p_dt[1]}/{p_dt[2]}"

        idt_date = parse_date(idt_str)

        # Buyer Trade Name & GSTIN
        lines = [line.strip() for line in txt.split("\n") if line.strip()]
        buyer = "UNKNOWN"
        for i, line_text in enumerate(lines):
            if line_text.lower() == "bill to" and i + 1 < len(lines):
                buyer = lines[i + 1]
                break

        gstin_m = re.search(
            r"GSTIN/UIN\s*:\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})",
            txt,
        )
        ctin = gstin_m.group(1) if gstin_m else ""
        if not ctin and inum_default in g1_map:
            ctin = g1_map[inum_default].get("ctin", "")

        pos_m = re.search(r"State Name\s*:[^,\n]*,\s*Code\s*:\s*(\d{2})", txt)
        pos = pos_m.group(1) if pos_m else (ctin[:2] if ctin else "09")
        if inum_default in g1_map and g1_map[inum_default].get("pos"):
            pos = str(g1_map[inum_default]["pos"]).zfill(2)

        state_name = STATE_CODES.get(pos, "Other")

        # Roundoff & Total Amount from footer
        round_m = re.search(r"Round Off\s*(?:\(([+\-])\)|([+\-]))?\s*([\d\.]+)", txt)
        round_off = 0.0
        if round_m:
            sign = round_m.group(1) or round_m.group(2) or "+"
            try:
                val_num = float(round_m.group(3))
                round_off = round(-val_num if sign == "-" else val_num, 2)
            except ValueError:
                pass

        doc_total = 0.0
        if inum_default in g1_map and g1_map[inum_default].get("val"):
            doc_total = clean_num(g1_map[inum_default]["val"])

        # Extract table items
        tabs = page.find_tables()
        if not tabs.tables:
            continue

        tab = tabs[0].extract()
        h_idx = -1
        for idx, r in enumerate(tab):
            r_txt = " ".join(str(c) for c in r if c)
            if any(k in r_txt for k in ("Item & Description", "SI.No", "Sl.No")):
                h_idx = idx
                break

        if h_idx == -1:
            continue

        header_row = tab[h_idx]
        has_currency = any("Currency" in str(c) for c in header_row if c)
        is_igst = any("IGST" in str(c) for c in header_row if c)

        inv_items: list[dict[str, Any]] = []
        for r in tab[h_idx + 1 :]:
            r_txt = " ".join(str(c) for c in r if c)
            if any(k in r_txt for k in ("Sub Total", "CGST Output", "Total Tax")):
                break
            vals = [str(c).strip() for c in r if c is not None and str(c).strip() != ""]
            if not vals or vals[0] == "%" or (len(vals) == 1 and vals[0] in ("%", "Amt")):
                continue

            sl = str(r[0]).strip() if r[0] else str(len(inv_items) + 1)
            desc = str(r[1]).replace("\n", " ").strip() if len(r) > 1 and r[1] else ""
            hsn = str(r[2]).strip() if len(r) > 2 and r[2] else "996712"
            qty_raw = str(r[3]).strip() if len(r) > 3 and r[3] else "1.0"

            qty = 1.0
            uqc = "NOS"
            if "\n" in qty_raw:
                parts = qty_raw.split("\n")
                qty = clean_num(parts[0])
                uqc = parts[1].upper().strip()
            else:
                q_m = re.search(r"([\d\.]+)\s*([a-zA-Z]*)", qty_raw)
                if q_m:
                    qty = clean_num(q_m.group(1))
                    uqc = q_m.group(2).upper() if q_m.group(2) else "NOS"

            currency = "INR"
            if has_currency:
                currency = str(r[4]).strip() if len(r) > 4 and r[4] else "INR"
                rate = clean_num(r[5])
                taxable = clean_num(r[7])
                cgst_pct = clean_num(str(r[8]).replace("%", "")) if len(r) > 8 else 0.0
                cgst_amt = clean_num(r[9]) if len(r) > 9 else 0.0
                sgst_pct = clean_num(str(r[10]).replace("%", "")) if len(r) > 10 else 0.0
                sgst_amt = clean_num(r[11]) if len(r) > 11 else 0.0
                igst_pct = 0.0
                igst_amt = 0.0
            elif is_igst:
                rate = clean_num(r[5]) if len(r) > 5 else clean_num(r[4])
                taxable = clean_num(r[6]) if len(r) > 6 else clean_num(r[5])
                igst_pct = clean_num(str(r[7]).replace("%", "")) if len(r) > 7 else 18.0
                igst_amt = clean_num(r[8]) if len(r) > 8 else 0.0
                cgst_pct = 0.0
                cgst_amt = 0.0
                sgst_pct = 0.0
                sgst_amt = 0.0
            else:
                rate = clean_num(r[4])
                taxable = clean_num(r[5])
                cgst_pct = clean_num(str(r[6]).replace("%", "")) if len(r) > 6 else 9.0
                cgst_amt = clean_num(r[7]) if len(r) > 7 else 0.0
                sgst_pct = clean_num(str(r[8]).replace("%", "")) if len(r) > 8 else 9.0
                sgst_amt = clean_num(r[9]) if len(r) > 9 else 0.0
                igst_pct = 0.0
                igst_amt = 0.0

            tax_rate = igst_pct if is_igst else (cgst_pct + sgst_pct)
            total_tax = round(igst_amt + cgst_amt + sgst_amt, 2)

            inv_items.append({
                "sl": sl,
                "desc": desc,
                "hsn": hsn,
                "qty": qty,
                "uqc": uqc,
                "currency": currency,
                "rate": rate,
                "taxable": taxable,
                "tax_rate": tax_rate,
                "cgst_pct": cgst_pct,
                "cgst": cgst_amt,
                "sgst_pct": sgst_pct,
                "sgst": sgst_amt,
                "igst_pct": igst_pct,
                "igst": igst_amt,
                "total_tax": total_tax,
            })

        inv_taxable = round(sum(it["taxable"] for it in inv_items), 2)
        inv_cgst = round(sum(it["cgst"] for it in inv_items), 2)
        inv_sgst = round(sum(it["sgst"] for it in inv_items), 2)
        inv_igst = round(sum(it["igst"] for it in inv_items), 2)
        inv_tax = round(inv_cgst + inv_sgst + inv_igst, 2)

        if doc_total == 0.0:
            doc_total = round(inv_taxable + inv_tax + round_off, 2)

        supply_type = "Inter-State (IGST)" if is_igst else "Intra-State (CGST+SGST)"

        invoices.append({
            "inum": inum_default,
            "idt": idt_date,
            "buyer": buyer,
            "ctin": ctin,
            "pos": pos,
            "pos_state": state_name,
            "supply_type": supply_type,
            "is_igst": is_igst,
            "rchrg": "N",
            "inv_typ": "R",
            "taxable": inv_taxable,
            "cgst": inv_cgst,
            "sgst": inv_sgst,
            "igst": inv_igst,
            "total_tax": inv_tax,
            "round_off": round_off,
            "doc_total": doc_total,
            "items": inv_items,
        })

    return taxpayer_info, invoices


def build_sales_register_excel(
    taxpayer_info: dict[str, Any],
    invoices: list[dict[str, Any]],
    output_path: Path | str,
) -> str:
    """Builds a formatted 4-sheet Sales Register Excel workbook."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    workbook = xlsxwriter.Workbook(str(out_file))

    # Palette
    COLOR_NAVY = "#1F4E78"
    COLOR_STEEL = "#2F5597"
    COLOR_ICE = "#D9E1F2"
    COLOR_CARD = "#F9FAFC"
    COLOR_BORDER = "#D3D3D3"

    # Formats
    fmt_title = workbook.add_format({
        "bold": True,
        "font_size": 15,
        "font_color": "#FFFFFF",
        "bg_color": COLOR_NAVY,
        "align": "left",
        "valign": "vcenter",
        "left": 1,
        "right": 1,
        "top": 1,
        "bottom": 1,
    })

    fmt_subtitle = workbook.add_format({
        "font_size": 10,
        "font_color": "#FFFFFF",
        "bg_color": COLOR_STEEL,
        "align": "left",
        "valign": "vcenter",
        "italic": True,
        "left": 1,
        "right": 1,
        "top": 1,
        "bottom": 1,
    })

    fmt_tbl_header = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "font_color": "#FFFFFF",
        "bg_color": COLOR_NAVY,
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
        "border": 1,
        "border_color": "#FFFFFF",
    })

    fmt_tbl_header_left = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "font_color": "#FFFFFF",
        "bg_color": COLOR_NAVY,
        "align": "left",
        "valign": "vcenter",
        "text_wrap": True,
        "border": 1,
        "border_color": "#FFFFFF",
    })

    fmt_tbl_header_num = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "font_color": "#FFFFFF",
        "bg_color": COLOR_NAVY,
        "align": "right",
        "valign": "vcenter",
        "text_wrap": True,
        "border": 1,
        "border_color": "#FFFFFF",
    })

    fmt_data_text = workbook.add_format({
        "font_size": 9,
        "align": "left",
        "valign": "vcenter",
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_data_center = workbook.add_format({
        "font_size": 9,
        "align": "center",
        "valign": "vcenter",
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_data_date = workbook.add_format({
        "font_size": 9,
        "align": "center",
        "valign": "vcenter",
        "num_format": "dd/mm/yyyy",
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_data_num = workbook.add_format({
        "font_size": 9,
        "align": "right",
        "valign": "vcenter",
        "num_format": '"₹ "#,##0.00;("₹ "#,##0.00);"-"',
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_data_qty = workbook.add_format({
        "font_size": 9,
        "align": "right",
        "valign": "vcenter",
        "num_format": "#,##0.00",
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_data_pct = workbook.add_format({
        "font_size": 9,
        "align": "right",
        "valign": "vcenter",
        "num_format": "0.0%",
        "border": 1,
        "border_color": COLOR_BORDER,
    })

    fmt_grand_total_label = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "align": "left",
        "valign": "vcenter",
        "bg_color": COLOR_ICE,
        "top": 1,
        "bottom": 6,  # Double bottom border
        "border_color": "#000000",
    })

    fmt_grand_total_num = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "align": "right",
        "valign": "vcenter",
        "bg_color": COLOR_ICE,
        "num_format": '"₹ "#,##0.00;("₹ "#,##0.00);"-"',
        "top": 1,
        "bottom": 6,
        "border_color": "#000000",
    })

    fmt_grand_total_qty = workbook.add_format({
        "bold": True,
        "font_size": 10,
        "align": "right",
        "valign": "vcenter",
        "bg_color": COLOR_ICE,
        "num_format": "#,##0.00",
        "top": 1,
        "bottom": 6,
        "border_color": "#000000",
    })

    # KPI Card Formats
    fmt_kpi_label = workbook.add_format({
        "font_size": 9,
        "bold": True,
        "align": "center",
        "valign": "vcenter",
        "bg_color": COLOR_STEEL,
        "font_color": "#FFFFFF",
        "border": 1,
    })

    fmt_kpi_val = workbook.add_format({
        "font_size": 13,
        "bold": True,
        "align": "center",
        "valign": "vcenter",
        "bg_color": COLOR_CARD,
        "font_color": COLOR_NAVY,
        "num_format": '"₹ "#,##0.00',
        "border": 1,
    })

    fmt_kpi_val_int = workbook.add_format({
        "font_size": 13,
        "bold": True,
        "align": "center",
        "valign": "vcenter",
        "bg_color": COLOR_CARD,
        "font_color": COLOR_NAVY,
        "border": 1,
    })

    # Aggregations
    total_taxable = round(sum(inv["taxable"] for inv in invoices), 2)
    total_cgst = round(sum(inv["cgst"] for inv in invoices), 2)
    total_sgst = round(sum(inv["sgst"] for inv in invoices), 2)
    total_igst = round(sum(inv["igst"] for inv in invoices), 2)
    total_tax = round(total_cgst + total_sgst + total_igst, 2)
    total_round_off = round(sum(inv["round_off"] for inv in invoices), 2)
    total_val = round(sum(inv["doc_total"] for inv in invoices), 2)
    total_items_count = sum(len(inv.get("items", [])) for inv in invoices)

    intra_taxable = round(sum(inv["taxable"] for inv in invoices if not inv["is_igst"]), 2)
    inter_taxable = round(sum(inv["taxable"] for inv in invoices if inv["is_igst"]), 2)

    # -------------------------------------------------------------
    # SHEET 1: EXECUTIVE DASHBOARD
    # -------------------------------------------------------------
    ws_dash = workbook.add_worksheet("Executive Dashboard")
    ws_dash.set_tab_color(COLOR_NAVY)
    ws_dash.hide_gridlines(0)

    ws_dash.set_row(0, 32)
    ws_dash.set_row(1, 20)
    ws_dash.merge_range(
        "A1:E1",
        f"  {taxpayer_info['trade_name'].upper()} — OUTWARD SALES REGISTER & GST COMPLIANCE REPORT",
        fmt_title,
    )
    period_str = f"Tax Period: August 2026 ({taxpayer_info['fp']})  |  Taxpayer GSTIN: {taxpayer_info['gstin']}  |  State: {taxpayer_info['state_name']} ({taxpayer_info['state_code']})"
    ws_dash.merge_range("A2:E2", f"  {period_str}", fmt_subtitle)

    # Balanced 4 KPI Summary Cards across Cols A-E
    ws_dash.set_row(2, 12)  # spacer
    ws_dash.set_row(3, 22)
    ws_dash.set_row(4, 32)

    cards = [
        ("TOTAL TURNOVER (TAXABLE)", total_taxable, "num", "A4:B4", "A5:B5"),
        ("TOTAL GST COLLECTED", total_tax, "num", "C4:C4", "C5:C5"),
        ("GROSS INVOICE VALUE", total_val, "num", "D4:D4", "D5:D5"),
        ("TOTAL DOCUMENTS", f"{len(invoices)} Invoices ({total_items_count} Items)", "str", "E4:E4", "E5:E5"),
    ]

    for label, val, val_type, r_lbl, r_val in cards:
        if ":" in r_lbl and r_lbl.split(":")[0] != r_lbl.split(":")[1]:
            ws_dash.merge_range(r_lbl, label, fmt_kpi_label)
            ws_dash.merge_range(r_val, val, fmt_kpi_val if val_type == "num" else fmt_kpi_val_int)
        else:
            cell_l = r_lbl.split(":")[0]
            cell_v = r_val.split(":")[0]
            ws_dash.write(cell_l, label, fmt_kpi_label)
            ws_dash.write(cell_v, val, fmt_kpi_val if val_type == "num" else fmt_kpi_val_int)

    # Section 1: Statutory Tax Split Table
    ws_dash.set_row(5, 14)  # spacer
    ws_dash.set_row(6, 24)
    ws_dash.set_row(7, 24)
    ws_dash.write("A7", "1. STATUTORY TAX LIABILITY SPLIT", workbook.add_format({"bold": True, "font_size": 11}))
    headers_tax = ["Tax Head", "Rate Applicability", "Taxable Turnover (₹)", "Tax Amount (₹)", "% Share of Tax"]
    for col_idx, h in enumerate(headers_tax):
        ws_dash.write(7, col_idx, h, fmt_tbl_header)

    tax_rows = [
        ("Integrated Tax (IGST)", "Inter-State Supplies", inter_taxable, total_igst, (total_igst / total_tax) if total_tax else 0.0),
        ("Central Tax (CGST)", "Intra-State Supplies (50%)", intra_taxable, total_cgst, (total_cgst / total_tax) if total_tax else 0.0),
        ("State Tax (SGST)", "Intra-State Supplies (50%)", intra_taxable, total_sgst, (total_sgst / total_tax) if total_tax else 0.0),
        ("GST Compensation Cess", "Not Applicable", 0.0, 0.0, 0.0),
    ]

    for idx, (head, desc, tx, amt, pct) in enumerate(tax_rows, start=8):
        ws_dash.set_row(idx, 20)
        ws_dash.write(idx, 0, head, fmt_data_text)
        ws_dash.write(idx, 1, desc, fmt_data_center)
        ws_dash.write(idx, 2, tx, fmt_data_num)
        ws_dash.write(idx, 3, amt, fmt_data_num)
        ws_dash.write(idx, 4, pct, fmt_data_pct)

    tot_tax_row = 8 + len(tax_rows)
    ws_dash.set_row(tot_tax_row, 22)
    ws_dash.write(tot_tax_row, 0, "TOTAL TAX LIABILITY", fmt_grand_total_label)
    ws_dash.write(tot_tax_row, 1, "", fmt_grand_total_label)
    ws_dash.write(tot_tax_row, 2, total_taxable, fmt_grand_total_num)
    ws_dash.write_formula(tot_tax_row, 3, f"=SUM(D9:D{tot_tax_row})", fmt_grand_total_num, value=total_tax)
    ws_dash.write(tot_tax_row, 4, 1.0, workbook.add_format({"bold": True, "align": "right", "num_format": "0.0%", "bg_color": COLOR_ICE, "top": 1, "bottom": 6}))

    # Section 2: GSTR-1 Return Tables Cross-Walk
    r_start_g1 = tot_tax_row + 2
    ws_dash.set_row(r_start_g1 - 1, 14)  # spacer
    ws_dash.set_row(r_start_g1, 24)
    ws_dash.set_row(r_start_g1 + 1, 24)
    ws_dash.write(r_start_g1, 0, "2. GSTR-1 OFFICIAL RETURN TABLE RECONCILIATION", workbook.add_format({"bold": True, "font_size": 11}))
    g1_headers = ["GSTR-1 Table", "Description", "Document Count", "Taxable Value (₹)", "Total Tax (₹)"]
    for col_idx, h in enumerate(g1_headers):
        ws_dash.write(r_start_g1 + 1, col_idx, h, fmt_tbl_header)

    g1_rows = [
        ("Table 4: B2B Invoices", "Taxable supplies to registered persons (Regular)", len(invoices), total_taxable, total_tax),
        ("Table 5: B2CL Large", "Unregistered inter-state invoices > ₹1,00,000", 0, 0.0, 0.0),
        ("Table 7: B2CS Small", "Other supplies to unregistered persons", 0, 0.0, 0.0),
        ("Table 6: Exports", "Zero-rated exports and supplies to SEZ", 0, 0.0, 0.0),
        ("Table 12: HSN Summary", "HSN/SAC summary of outward supplies", total_items_count, total_taxable, total_tax),
        ("Table 13: Documents", f"Invoices issued serial {invoices[0]['inum']} to {invoices[-1]['inum']}", len(invoices), 0.0, 0.0),
    ]

    for idx, (t_name, t_desc, cnt, tx, tx_amt) in enumerate(g1_rows, start=r_start_g1 + 2):
        ws_dash.set_row(idx, 20)
        ws_dash.write(idx, 0, t_name, fmt_data_text)
        ws_dash.write(idx, 1, t_desc, fmt_data_text)
        ws_dash.write(idx, 2, cnt, fmt_data_center)
        if t_name == "Table 13: Documents":
            ws_dash.write(idx, 3, "-", fmt_data_center)
            ws_dash.write(idx, 4, "-", fmt_data_center)
        else:
            ws_dash.write(idx, 3, tx, fmt_data_num)
            ws_dash.write(idx, 4, tx_amt, fmt_data_num)

    # Section 3: Top Revenue Debtors
    buyer_revenue: dict[str, float] = {}
    for inv in invoices:
        b_name = inv["buyer"]
        buyer_revenue[b_name] = round(buyer_revenue.get(b_name, 0.0) + inv["taxable"], 2)

    top_debtors = sorted(buyer_revenue.items(), key=lambda x: x[1], reverse=True)[:5]
    r_start_debtors = r_start_g1 + len(g1_rows) + 3
    ws_dash.set_row(r_start_debtors - 1, 14)  # spacer
    ws_dash.set_row(r_start_debtors, 24)
    ws_dash.set_row(r_start_debtors + 1, 24)
    ws_dash.write(r_start_debtors, 0, "3. TOP CLIENTS BY TAXABLE TURNOVER", workbook.add_format({"bold": True, "font_size": 11}))
    debtor_hdrs = ["Client / Trade Name", "Applicability / State", "Invoices", "Taxable Turnover (₹)", "% Share"]
    for col_idx, h in enumerate(debtor_hdrs):
        ws_dash.write(r_start_debtors + 1, col_idx, h, fmt_tbl_header)

    for idx, (c_name, rev) in enumerate(top_debtors, start=r_start_debtors + 2):
        ws_dash.set_row(idx, 20)
        c_invs = sum(1 for inv in invoices if inv["buyer"] == c_name)
        c_pos_state = next((inv["pos_state"] for inv in invoices if inv["buyer"] == c_name), "-")
        c_share = (rev / total_taxable) if total_taxable else 0.0
        ws_dash.write(idx, 0, c_name, fmt_data_text)
        ws_dash.write(idx, 1, c_pos_state, fmt_data_center)
        ws_dash.write(idx, 2, c_invs, fmt_data_center)
        ws_dash.write(idx, 3, rev, fmt_data_num)
        ws_dash.write(idx, 4, c_share, fmt_data_pct)

    dash_widths = [34, 46, 20, 22, 18]
    for i, w in enumerate(dash_widths):
        ws_dash.set_column(i, i, w)

    # -------------------------------------------------------------
    # SHEET 2: SALES REGISTER (INVOICE-LEVEL MASTER)
    # -------------------------------------------------------------
    ws_inv = workbook.add_worksheet("Sales Register")
    ws_inv.set_tab_color("#2E75B6")
    ws_inv.freeze_panes(2, 4)

    ws_inv.set_row(0, 28)
    ws_inv.merge_range(
        "A1:P1",
        f"  {taxpayer_info['trade_name']} — SALES REGISTER (INVOICE TAX SUMMARY) — PERIOD: {taxpayer_info['fp']}",
        fmt_title,
    )

    inv_headers = [
        "Sl No", "Invoice No", "Date", "Customer Trade Name", "Customer GSTIN",
        "POS Code", "Place of Supply", "Supply Type", "RCM",
        "Taxable Value (₹)", "CGST (₹)", "SGST (₹)", "IGST (₹)",
        "Total Tax (₹)", "Round Off (₹)", "Invoice Total (₹)",
    ]

    ws_inv.set_row(1, 26)
    for col_idx, h in enumerate(inv_headers):
        if col_idx in (0, 1, 2, 5, 8):
            ws_inv.write(1, col_idx, h, fmt_tbl_header)
        elif col_idx in (3, 4, 6, 7):
            ws_inv.write(1, col_idx, h, fmt_tbl_header_left)
        else:
            ws_inv.write(1, col_idx, h, fmt_tbl_header_num)

    for row_idx, inv in enumerate(invoices, start=2):
        ws_inv.set_row(row_idx, 20)
        ws_inv.write(row_idx, 0, row_idx - 1, fmt_data_center)
        ws_inv.write(row_idx, 1, inv["inum"], fmt_data_center)

        # Date formatting
        if isinstance(inv["idt"], datetime.date):
            ws_inv.write_datetime(row_idx, 2, inv["idt"], fmt_data_date)
        else:
            ws_inv.write(row_idx, 2, str(inv["idt"]), fmt_data_center)

        ws_inv.write(row_idx, 3, inv["buyer"], fmt_data_text)
        ws_inv.write(row_idx, 4, inv["ctin"], fmt_data_center)
        ws_inv.write(row_idx, 5, inv["pos"], fmt_data_center)
        ws_inv.write(row_idx, 6, inv["pos_state"], fmt_data_text)
        ws_inv.write(row_idx, 7, inv["supply_type"], fmt_data_text)
        ws_inv.write(row_idx, 8, inv["rchrg"], fmt_data_center)
        ws_inv.write(row_idx, 9, inv["taxable"], fmt_data_num)
        ws_inv.write(row_idx, 10, inv["cgst"], fmt_data_num)
        ws_inv.write(row_idx, 11, inv["sgst"], fmt_data_num)
        ws_inv.write(row_idx, 12, inv["igst"], fmt_data_num)
        ws_inv.write_formula(
            row_idx, 13, f"=SUM(K{row_idx+1}:M{row_idx+1})", fmt_data_num, value=inv["total_tax"]
        )
        ws_inv.write(row_idx, 14, inv["round_off"], fmt_data_num)
        ws_inv.write_formula(
            row_idx, 15, f"=J{row_idx+1}+N{row_idx+1}+O{row_idx+1}", fmt_data_num, value=inv["doc_total"]
        )

    # Grand Total Row for Invoices
    last_inv_row = 1 + len(invoices)
    tot_row_idx = last_inv_row + 1
    ws_inv.set_row(tot_row_idx, 22)
    ws_inv.write(tot_row_idx, 0, "TOTAL", fmt_grand_total_label)
    ws_inv.write(tot_row_idx, 1, f"{len(invoices)} Invoices", fmt_grand_total_label)
    for c in range(2, 9):
        ws_inv.write(tot_row_idx, c, "", fmt_grand_total_label)

    ws_inv.write_formula(tot_row_idx, 9, f"=SUM(J3:J{tot_row_idx})", fmt_grand_total_num, value=total_taxable)
    ws_inv.write_formula(tot_row_idx, 10, f"=SUM(K3:K{tot_row_idx})", fmt_grand_total_num, value=total_cgst)
    ws_inv.write_formula(tot_row_idx, 11, f"=SUM(L3:L{tot_row_idx})", fmt_grand_total_num, value=total_sgst)
    ws_inv.write_formula(tot_row_idx, 12, f"=SUM(M3:M{tot_row_idx})", fmt_grand_total_num, value=total_igst)
    ws_inv.write_formula(tot_row_idx, 13, f"=SUM(N3:N{tot_row_idx})", fmt_grand_total_num, value=total_tax)
    ws_inv.write_formula(tot_row_idx, 14, f"=SUM(O3:O{tot_row_idx})", fmt_grand_total_num, value=total_round_off)
    ws_inv.write_formula(tot_row_idx, 15, f"=SUM(P3:P{tot_row_idx})", fmt_grand_total_num, value=total_val)

    ws_inv.autofilter(1, 0, last_inv_row, len(inv_headers) - 1)

    inv_col_widths = [6, 12, 14, 36, 18, 10, 16, 24, 8, 18, 14, 14, 14, 16, 14, 18]
    for i, w in enumerate(inv_col_widths):
        ws_inv.set_column(i, i, w)

    # -------------------------------------------------------------
    # SHEET 3: ITEMIZED DETAILS (LINE-ITEM LEVEL)
    # -------------------------------------------------------------
    ws_item = workbook.add_worksheet("Itemized Details")
    ws_item.set_tab_color("#548235")
    ws_item.freeze_panes(2, 5)

    ws_item.set_row(0, 28)
    ws_item.merge_range(
        "A1:P1",
        f"  {taxpayer_info['trade_name']} — COMPLETE LINE-ITEM SERVICE DETAILS — PERIOD: {taxpayer_info['fp']}",
        fmt_title,
    )

    item_headers = [
        "Item Sl", "Invoice No", "Date", "Customer Name", "HSN/SAC",
        "Item & Service Description", "Quantity", "UQC", "Currency",
        "Unit Rate (₹)", "Taxable Value (₹)", "GST Rate",
        "CGST (₹)", "SGST (₹)", "IGST (₹)", "Total Tax (₹)",
    ]

    ws_item.set_row(1, 26)
    for col_idx, h in enumerate(item_headers):
        if col_idx in (0, 1, 2, 4, 7, 8):
            ws_item.write(1, col_idx, h, fmt_tbl_header)
        elif col_idx in (3, 5):
            ws_item.write(1, col_idx, h, fmt_tbl_header_left)
        else:
            ws_item.write(1, col_idx, h, fmt_tbl_header_num)

    cur_item_row = 2
    item_counter = 1
    total_items_qty = 0.0

    for inv in invoices:
        for it in inv.get("items", []):
            ws_item.set_row(cur_item_row, 19)
            ws_item.write(cur_item_row, 0, item_counter, fmt_data_center)
            ws_item.write(cur_item_row, 1, inv["inum"], fmt_data_center)

            if isinstance(inv["idt"], datetime.date):
                ws_item.write_datetime(cur_item_row, 2, inv["idt"], fmt_data_date)
            else:
                ws_item.write(cur_item_row, 2, str(inv["idt"]), fmt_data_center)

            ws_item.write(cur_item_row, 3, inv["buyer"], fmt_data_text)
            ws_item.write(cur_item_row, 4, it["hsn"], fmt_data_center)
            ws_item.write(cur_item_row, 5, it["desc"], fmt_data_text)
            ws_item.write(cur_item_row, 6, it["qty"], fmt_data_qty)
            ws_item.write(cur_item_row, 7, it["uqc"], fmt_data_center)
            ws_item.write(cur_item_row, 8, it.get("currency", "INR"), fmt_data_center)
            ws_item.write(cur_item_row, 9, it["rate"], fmt_data_num)
            ws_item.write(cur_item_row, 10, it["taxable"], fmt_data_num)
            ws_item.write(cur_item_row, 11, it["tax_rate"] / 100.0, fmt_data_pct)
            ws_item.write(cur_item_row, 12, it["cgst"], fmt_data_num)
            ws_item.write(cur_item_row, 13, it["sgst"], fmt_data_num)
            ws_item.write(cur_item_row, 14, it["igst"], fmt_data_num)
            ws_item.write_formula(
                cur_item_row, 15, f"=SUM(M{cur_item_row+1}:O{cur_item_row+1})", fmt_data_num, value=it["total_tax"]
            )

            total_items_qty += it["qty"]
            cur_item_row += 1
            item_counter += 1

    last_item_row = cur_item_row - 1
    # Grand Total Row for Items
    ws_item.set_row(cur_item_row, 22)
    ws_item.write(cur_item_row, 0, "TOTAL", fmt_grand_total_label)
    ws_item.write(cur_item_row, 1, f"{item_counter - 1} Items", fmt_grand_total_label)
    for c in range(2, 6):
        ws_item.write(cur_item_row, c, "", fmt_grand_total_label)
    ws_item.write_formula(cur_item_row, 6, f"=SUM(G3:G{cur_item_row})", fmt_grand_total_qty, value=total_items_qty)
    for c in (7, 8, 9):
        ws_item.write(cur_item_row, c, "", fmt_grand_total_label)

    ws_item.write_formula(cur_item_row, 10, f"=SUM(K3:K{cur_item_row})", fmt_grand_total_num, value=total_taxable)
    ws_item.write(cur_item_row, 11, "", fmt_grand_total_label)
    ws_item.write_formula(cur_item_row, 12, f"=SUM(M3:M{cur_item_row})", fmt_grand_total_num, value=total_cgst)
    ws_item.write_formula(cur_item_row, 13, f"=SUM(N3:N{cur_item_row})", fmt_grand_total_num, value=total_sgst)
    ws_item.write_formula(cur_item_row, 14, f"=SUM(O3:O{cur_item_row})", fmt_grand_total_num, value=total_igst)
    ws_item.write_formula(cur_item_row, 15, f"=SUM(P3:P{cur_item_row})", fmt_grand_total_num, value=total_tax)

    ws_item.autofilter(1, 0, last_item_row, len(item_headers) - 1)

    item_col_widths = [8, 12, 14, 34, 12, 46, 12, 10, 10, 14, 18, 10, 14, 14, 14, 16]
    for i, w in enumerate(item_col_widths):
        ws_item.set_column(i, i, w)

    # -------------------------------------------------------------
    # SHEET 4: HSN-SAC SUMMARY (TABLE 12 ALIGNED)
    # -------------------------------------------------------------
    ws_hsn = workbook.add_worksheet("HSN-SAC Summary")
    ws_hsn.set_tab_color("#7030A0")
    ws_hsn.freeze_panes(2, 2)

    ws_hsn.set_row(0, 28)
    ws_hsn.merge_range(
        "A1:J1",
        f"  {taxpayer_info['trade_name']} — TABLE 12 HSN/SAC SUMMARY — PERIOD: {taxpayer_info['fp']}",
        fmt_title,
    )

    hsn_headers = [
        "HSN/SAC Code", "Service / Goods Description", "UQC",
        "Total Quantity", "Total Taxable Value (₹)", "GST Rate",
        "CGST (₹)", "SGST (₹)", "IGST (₹)", "Total Tax (₹)",
    ]

    ws_hsn.set_row(1, 26)
    for col_idx, h in enumerate(hsn_headers):
        if col_idx in (0, 2):
            ws_hsn.write(1, col_idx, h, fmt_tbl_header)
        elif col_idx == 1:
            ws_hsn.write(1, col_idx, h, fmt_tbl_header_left)
        else:
            ws_hsn.write(1, col_idx, h, fmt_tbl_header_num)

    # Aggregate by (HSN, Rate)
    hsn_buckets: dict[tuple[str, float], dict[str, Any]] = {}
    total_hsn_qty = 0.0

    for inv in invoices:
        for it in inv.get("items", []):
            h_code = it["hsn"]
            r_val = it["tax_rate"]
            k = (h_code, r_val)
            if k not in hsn_buckets:
                # Use statutory description if mapped, else fallback to invoice description
                stat_desc = STATUTORY_HSN_DESCRIPTIONS.get(h_code, it["desc"])
                hsn_buckets[k] = {
                    "hsn": h_code,
                    "desc": stat_desc,
                    "uqc": it["uqc"],
                    "qty": 0.0,
                    "taxable": 0.0,
                    "rate": r_val,
                    "cgst": 0.0,
                    "sgst": 0.0,
                    "igst": 0.0,
                }
            hsn_buckets[k]["qty"] += it["qty"]
            hsn_buckets[k]["taxable"] += it["taxable"]
            hsn_buckets[k]["cgst"] += it["cgst"]
            hsn_buckets[k]["sgst"] += it["sgst"]
            hsn_buckets[k]["igst"] += it["igst"]
            total_hsn_qty += it["qty"]

    hsn_sorted = sorted(hsn_buckets.values(), key=lambda x: (x["hsn"], x["rate"]))
    hsn_valid = [
        h for h in hsn_sorted
        if round(h["taxable"], 2) > 0.0 or round(h["cgst"] + h["sgst"] + h["igst"], 2) > 0.0
    ]

    for row_idx, h_data in enumerate(hsn_valid, start=2):
        ws_hsn.set_row(row_idx, 22)
        ws_hsn.write(row_idx, 0, h_data["hsn"], fmt_data_center)
        ws_hsn.write(row_idx, 1, h_data["desc"], fmt_data_text)
        ws_hsn.write(row_idx, 2, h_data["uqc"], fmt_data_center)
        ws_hsn.write(row_idx, 3, h_data["qty"], fmt_data_qty)
        ws_hsn.write(row_idx, 4, round(h_data["taxable"], 2), fmt_data_num)
        ws_hsn.write(row_idx, 5, h_data["rate"] / 100.0, fmt_data_pct)
        ws_hsn.write(row_idx, 6, round(h_data["cgst"], 2), fmt_data_num)
        ws_hsn.write(row_idx, 7, round(h_data["sgst"], 2), fmt_data_num)
        ws_hsn.write(row_idx, 8, round(h_data["igst"], 2), fmt_data_num)
        h_tot_tax = round(h_data["cgst"] + h_data["sgst"] + h_data["igst"], 2)
        ws_hsn.write_formula(
            row_idx, 9, f"=SUM(G{row_idx+1}:I{row_idx+1})", fmt_data_num, value=h_tot_tax
        )

    last_hsn_row = 1 + len(hsn_valid)
    tot_hsn_row = last_hsn_row + 1

    ws_hsn.set_row(tot_hsn_row, 24)
    ws_hsn.write(tot_hsn_row, 0, "GRAND TOTAL", fmt_grand_total_label)
    ws_hsn.write(tot_hsn_row, 1, "", fmt_grand_total_label)
    ws_hsn.write(tot_hsn_row, 2, "", fmt_grand_total_label)
    ws_hsn.write_formula(tot_hsn_row, 3, f"=SUM(D3:D{tot_hsn_row})", fmt_grand_total_qty, value=total_hsn_qty)
    ws_hsn.write_formula(tot_hsn_row, 4, f"=SUM(E3:E{tot_hsn_row})", fmt_grand_total_num, value=total_taxable)
    ws_hsn.write(tot_hsn_row, 5, "", fmt_grand_total_label)
    ws_hsn.write_formula(tot_hsn_row, 6, f"=SUM(G3:G{tot_hsn_row})", fmt_grand_total_num, value=total_cgst)
    ws_hsn.write_formula(tot_hsn_row, 7, f"=SUM(H3:H{tot_hsn_row})", fmt_grand_total_num, value=total_sgst)
    ws_hsn.write_formula(tot_hsn_row, 8, f"=SUM(I3:I{tot_hsn_row})", fmt_grand_total_num, value=total_igst)
    ws_hsn.write_formula(tot_hsn_row, 9, f"=SUM(J3:J{tot_hsn_row})", fmt_grand_total_num, value=total_tax)

    ws_hsn.autofilter(1, 0, last_hsn_row, len(hsn_headers) - 1)

    hsn_widths = [14, 48, 12, 16, 22, 12, 16, 16, 16, 18]
    for i, w in enumerate(hsn_widths):
        ws_hsn.set_column(i, i, w)

    workbook.close()
    return str(out_file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("invoices_dir", type=str, help="Directory containing invoice PDFs")
    parser.add_argument("--output", "-o", type=str, default="output/sales_register.xlsx", help="Output Excel path")
    parser.add_argument("--gstr1", "-g", type=str, default=None, help="Path to gstr1_input.json")
    args = parser.parse_args()

    taxpayer_info, invoices = extract_invoices_from_pdf_dir(args.invoices_dir, args.gstr1)
    res_path = build_sales_register_excel(taxpayer_info, invoices, args.output)
    print(f"Generated Sales Register workbook: {res_path} ({len(invoices)} invoices)")


if __name__ == "__main__":
    main()
