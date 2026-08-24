#!/usr/bin/env python3
"""Generates comprehensive CA-grade Markdown filing packs for GSTR-1, GSTR-3B, and GSTR-2B.

Outputs:
  - output/gstr1-filing-pack.md
  - output/gstr3b-filing-pack.md
  - output/reconciliation-report.md

Usage:
  python3 scripts/generate_filing_pack.py <gstr1_input.json> <gstr3b_input.json> <reconciliation.json> [output_dir]
"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict, List
from scripts.gst_engine import compute_gstr1_tables, format_table
from scripts.itc_optimizer import optimize_from_input_dict


def generate_gstr1_filing_pack(g1_data: Dict[str, Any], output_path: str):
    """Generates human-readable, audit-ready GSTR-1 filing pack."""
    comp = compute_gstr1_tables(g1_data)
    s = comp["summary"]

    lines = [
        f"# GSTR-1 Filing Pack: {comp['gstin']} (Period: {comp['fp']})",
        "",
        "> **Notice:** This filing pack is generated deterministically by `gstr-wala`. Verify all figures against your accounting system before portal upload.",
        "",
        "## 1. Outward Supplies Executive Summary",
        "",
        format_table(
            ["Table / Section", "Count / Lines", "Taxable Value (₹)", "IGST (₹)", "CGST (₹)", "SGST (₹)", "Cess (₹)", "Total Tax (₹)"],
            [
                ["Table 4: B2B Invoices", s["b2b_count"], f"{sum(sum(i.get('txval',0) for i in inv.get('items',[])) for inv in comp['table_4_b2b']):,.2f}", f"{sum(sum(i.get('iamt',0) for i in inv.get('items',[])) for inv in comp['table_4_b2b']):,.2f}", f"{sum(sum(i.get('camt',0) for i in inv.get('items',[])) for inv in comp['table_4_b2b']):,.2f}", f"{sum(sum(i.get('samt',0) for i in inv.get('items',[])) for inv in comp['table_4_b2b']):,.2f}", f"{sum(sum(i.get('csamt',0) for i in inv.get('items',[])) for inv in comp['table_4_b2b']):,.2f}", "-"],
                ["Table 5: B2CL (> ₹1L)", s["b2cl_count"], f"{sum(sum(i.get('txval',0) for i in inv.get('items',[])) for inv in comp['table_5_b2cl']):,.2f}", f"{sum(sum(i.get('iamt',0) for i in inv.get('items',[])) for inv in comp['table_5_b2cl']):,.2f}", "-", "-", f"{sum(sum(i.get('csamt',0) for i in inv.get('items',[])) for inv in comp['table_5_b2cl']):,.2f}", "-"],
                ["Table 7: B2CS (Small)", s["b2cs_lines"], f"{sum(r['txval'] for r in comp['table_7_b2cs']):,.2f}", f"{sum(r['iamt'] for r in comp['table_7_b2cs']):,.2f}", f"{sum(r['camt'] for r in comp['table_7_b2cs']):,.2f}", f"{sum(r['samt'] for r in comp['table_7_b2cs']):,.2f}", f"{sum(r['csamt'] for r in comp['table_7_b2cs']):,.2f}", "-"],
                ["Table 6: Exports", s["export_count"], "-", "-", "-", "-", "-", "-"],
                ["TOTAL RETURN AGGREGATE", s["total_invoices"], f"{s['total_taxable']:,.2f}", f"{s['total_igst']:,.2f}", f"{s['total_cgst']:,.2f}", f"{s['total_sgst']:,.2f}", f"{s['total_cess']:,.2f}", f"{s['total_tax']:,.2f}"]
            ]
        ),
        "",
        "## 2. Table 12: HSN Summary (12A B2B & 12B B2C)",
        ""
    ]

    if comp["table_12_hsn"]:
        hsn_rows = [
            [h["source_type"], h["hsn_sc"], h["desc"], h["uqc"], h["qty"], f"₹{h['txval']:,.2f}", f"{h['rt']}%", f"₹{h['iamt']:,.2f}", f"₹{h['camt']:,.2f}", f"₹{h['samt']:,.2f}"]
            for h in comp["table_12_hsn"]
        ]
        lines.append(format_table(["Type", "HSN/SAC", "Description", "UQC", "Qty", "Taxable (₹)", "Rate", "IGST (₹)", "CGST (₹)", "SGST (₹)"], hsn_rows))

    lines.extend([
        "",
        "## 3. Table 13: Documents Summary Trail",
        ""
    ])

    if comp["table_13_docs"]:
        doc_rows = [
            [d.get("doc_num", 1), d.get("from", ""), d.get("to", ""), d.get("totnum", 0), d.get("canc", 0), d.get("net_issue", 0)]
            for d in comp["table_13_docs"]
        ]
        lines.append(format_table(["Doc Type No.", "From Serial", "To Serial", "Total Issued", "Cancelled", "Net Issued"], doc_rows))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def generate_gstr3b_filing_pack(g3b_data: Dict[str, Any], output_path: str):
    """Generates human-readable, audit-ready GSTR-3B filing pack."""
    opt = optimize_from_input_dict(g3b_data)
    m = opt["setoff_matrix"]
    c = opt["challan_pmt06"]

    outward = g3b_data.get("outward_supplies", {})
    taxable = outward.get("taxable", {})
    itc = g3b_data.get("itc", {})
    avail = itc.get("available", {})
    rev = itc.get("reversed", {})

    lines = [
        f"# GSTR-3B Filing Pack: {g3b_data.get('gstin', '')} (Period: {g3b_data.get('ret_period', '')})",
        "",
        f"- **Due Date:** {g3b_data.get('due_date', 'N/A')}",
        f"- **Filing Date:** {g3b_data.get('filing_date', 'N/A')}",
        "",
        "## 1. Table 3.1: Tax on Outward and Reverse Charge Supplies",
        "",
        format_table(
            ["Nature of Supply", "Taxable Value (₹)", "IGST (₹)", "CGST (₹)", "SGST (₹)", "Cess (₹)"],
            [
                ["3.1(a) Outward Taxable Supplies", f"{float(taxable.get('txval',0)):,.2f}", f"{float(taxable.get('iamt',0)):,.2f}", f"{float(taxable.get('camt',0)):,.2f}", f"{float(taxable.get('samt',0)):,.2f}", f"{float(taxable.get('csamt',0)):,.2f}"],
                ["3.1(b) Zero-Rated Supplies", f"{float(outward.get('zero_rated',{}).get('txval',0)):,.2f}", f"{float(outward.get('zero_rated',{}).get('iamt',0)):,.2f}", "-", "-", f"{float(outward.get('zero_rated',{}).get('csamt',0)):,.2f}"],
                ["3.1(c) Nil & Exempted", f"{float(outward.get('nil_exempt',{}).get('txval',0)):,.2f}", "-", "-", "-", "-"],
                ["3.1(d) Inward Supplies (RCM)", f"{float(outward.get('rcm_inward',{}).get('txval',0)):,.2f}", f"{float(outward.get('rcm_inward',{}).get('iamt',0)):,.2f}", f"{float(outward.get('rcm_inward',{}).get('camt',0)):,.2f}", f"{float(outward.get('rcm_inward',{}).get('samt',0)):,.2f}", f"{float(outward.get('rcm_inward',{}).get('csamt',0)):,.2f}"]
            ]
        ),
        "",
        "## 2. Table 4: Eligible Input Tax Credit (ITC)",
        "",
        format_table(
            ["Schedule", "IGST (₹)", "CGST (₹)", "SGST (₹)", "Cess (₹)"],
            [
                ["4(A)(1) Import of Goods", f"{float(avail.get('import_goods',{}).get('iamt',0)):,.2f}", "-", "-", f"{float(avail.get('import_goods',{}).get('csamt',0)):,.2f}"],
                ["4(A)(4) ISD Inward", f"{float(avail.get('isd',{}).get('iamt',0)):,.2f}", f"{float(avail.get('isd',{}).get('camt',0)):,.2f}", f"{float(avail.get('isd',{}).get('samt',0)):,.2f}", f"{float(avail.get('isd',{}).get('csamt',0)):,.2f}"],
                ["4(A)(5) All Other ITC (GSTR-2B)", f"{float(avail.get('all_other',{}).get('iamt',0)):,.2f}", f"{float(avail.get('all_other',{}).get('camt',0)):,.2f}", f"{float(avail.get('all_other',{}).get('samt',0)):,.2f}", f"{float(avail.get('all_other',{}).get('csamt',0)):,.2f}"],
                ["4(B)(1) Permanent Reversals (17(5))", f"{float(rev.get('permanent_17_5_rules',{}).get('iamt',0)):,.2f}", f"{float(rev.get('permanent_17_5_rules',{}).get('camt',0)):,.2f}", f"{float(rev.get('permanent_17_5_rules',{}).get('samt',0)):,.2f}", f"{float(rev.get('permanent_17_5_rules',{}).get('csamt',0)):,.2f}"],
                ["4(B)(2) Temporary Reversals (Rule 37)", f"{float(rev.get('temporary_others',{}).get('iamt',0)):,.2f}", f"{float(rev.get('temporary_others',{}).get('camt',0)):,.2f}", f"{float(rev.get('temporary_others',{}).get('samt',0)):,.2f}", f"{float(rev.get('temporary_others',{}).get('csamt',0)):,.2f}"]
            ]
        ),
        "",
        "## 3. Table 6.1: Rule 88A Optimal Tax Set-Off Matrix",
        "",
        format_table(
            ["Tax Head", "Total Tax Liability", "Paid via IGST Cr", "Paid via CGST Cr", "Paid via SGST Cr", "Paid via Cash"],
            [
                ["Integrated Tax (IGST)", f"₹{m['igst_liability']['total']:,.2f}", f"₹{m['igst_liability']['paid_by_igst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_cgst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_sgst_credit']:,.2f}", f"₹{m['igst_liability']['paid_by_cash']:,.2f}"],
                ["Central Tax (CGST)", f"₹{m['cgst_liability']['total']:,.2f}", f"₹{m['cgst_liability']['paid_by_igst_credit']:,.2f}", f"₹{m['cgst_liability']['paid_by_cgst_credit']:,.2f}", "-", f"₹{m['cgst_liability']['paid_by_cash']:,.2f}"],
                ["State/UT Tax (SGST)", f"₹{m['sgst_liability']['total']:,.2f}", f"₹{m['sgst_liability']['paid_by_igst_credit']:,.2f}", "-", f"₹{m['sgst_liability']['paid_by_sgst_credit']:,.2f}", f"₹{m['sgst_liability']['paid_by_cash']:,.2f}"],
                ["Cess", f"₹{m['cess_liability']['total']:,.2f}", "-", "-", "-", f"₹{m['cess_liability']['paid_by_cash']:,.2f}"]
            ]
        ),
        "",
        "## 4. Challan PMT-06 Deposit Requirement",
        "",
        format_table(
            ["Tax Head", "Cash Amount to Deposit (₹)"],
            [
                ["IGST Cash", f"₹{c['iamt']:,.2f}"],
                ["CGST Cash", f"₹{c['camt']:,.2f}"],
                ["SGST Cash", f"₹{c['samt']:,.2f}"],
                ["Cess Cash", f"₹{c['csamt']:,.2f}"],
                ["TOTAL CHALLAN TO DEPOSIT", f"₹{c['total_challan_amount']:,.2f}"]
            ]
        )
    ]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def generate_reconciliation_report(recon_data: Dict[str, Any], output_path: str):
    """Generates human-readable, audit-ready GSTR-2B reconciliation report."""
    s = recon_data.get("summary", {})
    t4 = recon_data.get("gstr3b_table_4_auto_population", {})
    det = recon_data.get("details", {})

    lines = [
        "# GSTR-2B vs Books Reconciliation Audit Report",
        "",
        "## 1. Executive Reconciliation Summary",
        "",
        format_table(
            ["Category", "Invoice Count", "Description"],
            [
                ["Exact Matched Invoices", s.get("exact_matched_count", 0), "100% match on GSTIN, Invoice No, and Tax values"],
                ["Tolerance Matched Invoices", s.get("tolerance_matched_count", 0), "Matched within +/- ₹1 rounding tolerance"],
                ["Value Mismatches", s.get("value_mismatch_count", 0), "Discrepancy > ₹1 (Restricted claim)"],
                ["In Books Only", s.get("in_books_only_count", 0), "Supplier not filed GSTR-1 yet (Rule 36(4) Deferred)"],
                ["In 2B Only", s.get("in_2b_only_count", 0), "Unrecorded purchases or incorrect GSTIN"],
                ["Section 17(5) Blocked Credit", s.get("blocked_17_5_count", 0), "Permanent reversal in Table 4(B)(1)"],
                ["Rule 37 Reversals", s.get("rule_37_count", 0), "Unpaid > 180 days (Temporary reversal in 4(B)(2))"]
            ]
        ),
        "",
        "## 2. Invoices Missing in GSTR-2B (Deferred under Rule 36(4))",
        ""
    ]

    in_books = det.get("in_books_only", [])
    if in_books:
        bk_rows = [
            [b.get("ctin", ""), b.get("inum", ""), b.get("idt", ""), f"₹{float(b.get('txval',0)):,.2f}", f"₹{float(b.get('iamt',0))+float(b.get('camt',0))+float(b.get('samt',0)):,.2f}"]
            for b in in_books
        ]
        lines.append(format_table(["Supplier GSTIN", "Invoice No.", "Date", "Taxable (₹)", "Total Tax (₹)"], bk_rows))
    else:
        lines.append("No missing invoices. All purchase register invoices reflect in GSTR-2B.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 generate_filing_pack.py <gstr1_input.json> <gstr3b_input.json> <reconciliation.json> [output_dir]")
        sys.exit(1)

    g1_file = sys.argv[1]
    g3b_file = sys.argv[2]
    recon_file = sys.argv[3]
    out_dir = sys.argv[4] if len(sys.argv) > 4 else "output"

    with open(g1_file, "r", encoding="utf-8") as f:
        g1_data = json.load(f)
    with open(g3b_file, "r", encoding="utf-8") as f:
        g3b_data = json.load(f)
    with open(recon_file, "r", encoding="utf-8") as f:
        recon_data = json.load(f)

    generate_gstr1_filing_pack(g1_data, os.path.join(out_dir, "gstr1_filing_pack.md"))
    generate_gstr3b_filing_pack(g3b_data, os.path.join(out_dir, "gstr3b_filing_pack.md"))
    generate_reconciliation_report(recon_data, os.path.join(out_dir, "reconciliation_report.md"))


    print(f"SUCCESS: Generated all CA Filing Packs in directory -> '{out_dir}/'")


if __name__ == "__main__":
    main()
