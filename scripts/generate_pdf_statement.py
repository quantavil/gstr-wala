#!/usr/bin/env python3
"""Generates audit-ready, printable CA Tax Audit & Filing Statements via Jinja2 & WeasyPrint.

Outputs:
  - output/gstr3b_statement.pdf / .html

Usage:
  python3 scripts/generate_pdf_statement.py <gstr3b_input.json> [output_pdf_path]

"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Any, Dict
from jinja2 import Template
from scripts.itc_optimizer import optimize_from_input_dict

HTML_TEMPLATE_GSTR3B = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GSTR-3B Tax Computation & Filing Statement</title>
<style>
  @page { size: A4; margin: 15mm; }
  body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #222; font-size: 11pt; line-height: 1.4; }
  .header { border-bottom: 2px solid #1a365d; padding-bottom: 8px; margin-bottom: 15px; }
  .header h1 { margin: 0; color: #1a365d; font-size: 18pt; }
  .header p { margin: 3px 0 0 0; color: #4a5568; font-size: 9.5pt; }
  .meta-table { width: 100%; margin-bottom: 15px; border-collapse: collapse; }
  .meta-table td { padding: 4px 8px; font-size: 10pt; }
  .meta-label { font-weight: bold; color: #2d3748; width: 25%; }
  .section-title { font-size: 12pt; font-weight: bold; color: #1a365d; border-bottom: 1px solid #cbd5e0; padding-bottom: 4px; margin-top: 15px; margin-bottom: 8px; }
  table.data-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; }
  table.data-table th { background-color: #2b6cb0; color: #fff; font-weight: 600; text-align: left; padding: 6px 8px; font-size: 9.5pt; border: 1px solid #2b6cb0; }
  table.data-table td { padding: 5px 8px; border: 1px solid #e2e8f0; font-size: 9.5pt; }
  table.data-table tr:nth-child(even) { background-color: #f7fafc; }
  .num { text-align: right; font-family: 'Courier New', Courier, monospace; font-weight: bold; }
  .challan-box { background-color: #ebf8ff; border: 1px solid #bee3f8; border-left: 4px solid #3182ce; padding: 10px; margin-top: 15px; border-radius: 4px; }
  .challan-title { font-weight: bold; color: #2b6cb0; margin-bottom: 5px; font-size: 11pt; }
  .footer { margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 8px; font-size: 8.5pt; color: #718096; text-align: center; }
  .stamp-box { float: right; width: 200px; height: 70px; border: 1px dashed #a0aec0; margin-top: 15px; text-align: center; line-height: 70px; color: #a0aec0; font-size: 9pt; }
</style>
</head>
<body>

<div class="header">
  <h1>FORM GSTR-3B SUMMARY STATEMENT</h1>
  <p>Certified Computation as per Section 39 of CGST Act, 2017 & Rule 88A Optimization</p>
</div>

<table class="meta-table">
  <tr>
    <td class="meta-label">Taxpayer GSTIN:</td>
    <td><strong>{{ gstin }}</strong></td>
    <td class="meta-label">Return Period:</td>
    <td><strong>{{ ret_period }}</strong></td>
  </tr>
  <tr>
    <td class="meta-label">Statutory Due Date:</td>
    <td>{{ due_date }}</td>
    <td class="meta-label">Filing Date:</td>
    <td>{{ filing_date }}</td>
  </tr>
</table>

<div class="section-title">1. Table 3.1: Details of Outward Supplies and Inward Reverse Charge</div>
<table class="data-table">
  <thead>
    <tr>
      <th>Nature of Supply</th>
      <th class="num">Taxable Value (₹)</th>
      <th class="num">IGST (₹)</th>
      <th class="num">CGST (₹)</th>
      <th class="num">SGST (₹)</th>
      <th class="num">Cess (₹)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>3.1(a) Outward Taxable Supplies</td>
      <td class="num">{{ "%.2f"|format(t_txval) }}</td>
      <td class="num">{{ "%.2f"|format(t_iamt) }}</td>
      <td class="num">{{ "%.2f"|format(t_camt) }}</td>
      <td class="num">{{ "%.2f"|format(t_samt) }}</td>
      <td class="num">{{ "%.2f"|format(t_csamt) }}</td>
    </tr>
    <tr>
      <td>3.1(b) Zero-Rated Supplies</td>
      <td class="num">{{ "%.2f"|format(z_txval) }}</td>
      <td class="num">{{ "%.2f"|format(z_iamt) }}</td>
      <td class="num">-</td>
      <td class="num">-</td>
      <td class="num">{{ "%.2f"|format(z_csamt) }}</td>
    </tr>
    <tr>
      <td>3.1(d) Inward Supplies (RCM - 100% Cash)</td>
      <td class="num">{{ "%.2f"|format(rcm_txval) }}</td>
      <td class="num">{{ "%.2f"|format(rcm_iamt) }}</td>
      <td class="num">{{ "%.2f"|format(rcm_camt) }}</td>
      <td class="num">{{ "%.2f"|format(rcm_samt) }}</td>
      <td class="num">{{ "%.2f"|format(rcm_csamt) }}</td>
    </tr>
  </tbody>
</table>

<div class="section-title">2. Table 4: Eligible Input Tax Credit (ITC) Summary</div>
<table class="data-table">
  <thead>
    <tr>
      <th>ITC Schedule</th>
      <th class="num">IGST (₹)</th>
      <th class="num">CGST (₹)</th>
      <th class="num">SGST (₹)</th>
      <th class="num">Cess (₹)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>4(A)(5) All Other ITC (GSTR-2B Matched)</td>
      <td class="num">{{ "%.2f"|format(itc_avl_i) }}</td>
      <td class="num">{{ "%.2f"|format(itc_avl_c) }}</td>
      <td class="num">{{ "%.2f"|format(itc_avl_s) }}</td>
      <td class="num">{{ "%.2f"|format(itc_avl_cs) }}</td>
    </tr>
    <tr>
      <td>4(B)(1) Permanent Reversal (Sec 17(5))</td>
      <td class="num">{{ "%.2f"|format(itc_rev_i) }}</td>
      <td class="num">{{ "%.2f"|format(itc_rev_c) }}</td>
      <td class="num">{{ "%.2f"|format(itc_rev_s) }}</td>
      <td class="num">{{ "%.2f"|format(itc_rev_cs) }}</td>
    </tr>
    <tr style="font-weight:bold; background-color:#edf2f7;">
      <td>Table 4(C) Net Available ITC</td>
      <td class="num">{{ "%.2f"|format(net_itc_i) }}</td>
      <td class="num">{{ "%.2f"|format(net_itc_c) }}</td>
      <td class="num">{{ "%.2f"|format(net_itc_s) }}</td>
      <td class="num">{{ "%.2f"|format(net_itc_cs) }}</td>
    </tr>
  </tbody>
</table>

<div class="section-title">3. Table 6.1: Rule 88A Optimal Tax Payment & Set-Off</div>
<table class="data-table">
  <thead>
    <tr>
      <th>Tax Head</th>
      <th class="num">Liability (₹)</th>
      <th class="num">Paid via IGST Cr</th>
      <th class="num">Paid via CGST Cr</th>
      <th class="num">Paid via SGST Cr</th>
      <th class="num">Paid in Cash</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Integrated Tax (IGST)</td>
      <td class="num">{{ "%.2f"|format(m.igst_liability.total) }}</td>
      <td class="num">{{ "%.2f"|format(m.igst_liability.paid_by_igst_credit) }}</td>
      <td class="num">{{ "%.2f"|format(m.igst_liability.paid_by_cgst_credit) }}</td>
      <td class="num">{{ "%.2f"|format(m.igst_liability.paid_by_sgst_credit) }}</td>
      <td class="num">{{ "%.2f"|format(m.igst_liability.paid_by_cash) }}</td>
    </tr>
    <tr>
      <td>Central Tax (CGST)</td>
      <td class="num">{{ "%.2f"|format(m.cgst_liability.total) }}</td>
      <td class="num">{{ "%.2f"|format(m.cgst_liability.paid_by_igst_credit) }}</td>
      <td class="num">{{ "%.2f"|format(m.cgst_liability.paid_by_cgst_credit) }}</td>
      <td class="num">-</td>
      <td class="num">{{ "%.2f"|format(m.cgst_liability.paid_by_cash) }}</td>
    </tr>
    <tr>
      <td>State/UT Tax (SGST)</td>
      <td class="num">{{ "%.2f"|format(m.sgst_liability.total) }}</td>
      <td class="num">{{ "%.2f"|format(m.sgst_liability.paid_by_igst_credit) }}</td>
      <td class="num">-</td>
      <td class="num">{{ "%.2f"|format(m.sgst_liability.paid_by_sgst_credit) }}</td>
      <td class="num">{{ "%.2f"|format(m.sgst_liability.paid_by_cash) }}</td>
    </tr>
  </tbody>
</table>

<div class="challan-box">
  <div class="challan-title">Challan PMT-06 Net Deposit Required: ₹{{ "%.2f"|format(challan.total_challan_amount) }}</div>
  <div>IGST: ₹{{ "%.2f"|format(challan.iamt) }} | CGST: ₹{{ "%.2f"|format(challan.camt) }} | SGST: ₹{{ "%.2f"|format(challan.samt) }} | Cess: ₹{{ "%.2f"|format(challan.csamt) }}</div>
</div>

<div class="stamp-box">
  Authorized Signatory
</div>

<div style="clear:both;"></div>

<div class="footer">
  Generated deterministically by gstr-wala Engine Suite • GST Portal Offline Utility v3.x Compatible
</div>

</body>
</html>
"""


def generate_pdf(g3b_data: Dict[str, Any], output_pdf_path: str) -> bool:
    """Renders HTML via Jinja2 and converts to PDF via WeasyPrint."""
    opt = optimize_from_input_dict(g3b_data)
    m = opt["setoff_matrix"]
    c = opt["challan_pmt06"]

    # Handle canonical vs portal format
    outward = g3b_data.get("outward_supplies", {})
    sup_det = g3b_data.get("sup_details", {})
    taxable = outward.get("taxable", sup_det.get("osup_det", {}))
    zero = outward.get("zero_rated", sup_det.get("osup_zero", {}))
    rcm = outward.get("rcm_inward", sup_det.get("isup_rev", {}))

    itc = g3b_data.get("itc", {})
    itc_elg = g3b_data.get("itc_elg", {})
    avail = itc.get("available", {}).get("all_other", {})
    rev = itc.get("reversed", {}).get("permanent_17_5_rules", {})

    avl_i = float(avail.get("iamt", 0.0))
    avl_c = float(avail.get("camt", 0.0))
    avl_s = float(avail.get("samt", 0.0))
    avl_cs = float(avail.get("csamt", 0.0))

    rev_i = float(rev.get("iamt", 0.0))
    rev_c = float(rev.get("camt", 0.0))
    rev_s = float(rev.get("samt", 0.0))
    rev_cs = float(rev.get("csamt", 0.0))

    template = Template(HTML_TEMPLATE_GSTR3B)
    rendered_html = template.render(
        gstin=g3b_data.get("gstin", ""),
        ret_period=g3b_data.get("ret_period", ""),
        due_date=g3b_data.get("due_date", "20-05-2026"),
        filing_date=g3b_data.get("filing_date", "20-05-2026"),
        t_txval=float(taxable.get("txval", 0.0)),
        t_iamt=float(taxable.get("iamt", 0.0)),
        t_camt=float(taxable.get("camt", 0.0)),
        t_samt=float(taxable.get("samt", 0.0)),
        t_csamt=float(taxable.get("csamt", 0.0)),
        z_txval=float(zero.get("txval", 0.0)),
        z_iamt=float(zero.get("iamt", 0.0)),
        z_csamt=float(zero.get("csamt", 0.0)),
        rcm_txval=float(rcm.get("txval", 0.0)),
        rcm_iamt=float(rcm.get("iamt", 0.0)),
        rcm_camt=float(rcm.get("camt", 0.0)),
        rcm_samt=float(rcm.get("samt", 0.0)),
        rcm_csamt=float(rcm.get("csamt", 0.0)),
        itc_avl_i=avl_i,
        itc_avl_c=avl_c,
        itc_avl_s=avl_s,
        itc_avl_cs=avl_cs,
        itc_rev_i=rev_i,
        itc_rev_c=rev_c,
        itc_rev_s=rev_s,
        itc_rev_cs=rev_cs,
        net_itc_i=max(0.0, avl_i - rev_i),
        net_itc_c=max(0.0, avl_c - rev_c),
        net_itc_s=max(0.0, avl_s - rev_s),
        net_itc_cs=max(0.0, avl_cs - rev_cs),
        m=m,
        challan=c
    )

    html_path = output_pdf_path.replace(".pdf", ".html")
    os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    try:
        from weasyprint import HTML
        HTML(string=rendered_html).write_pdf(output_pdf_path)
        print(f"SUCCESS: Generated PDF Filing Statement -> '{output_pdf_path}'")
        return True
    except Exception as e:
        print(f"Notice: Saved HTML statement -> '{html_path}' (Weasyprint note: {e})")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_pdf_report.py <gstr3b_input.json> [output_pdf_path]")
        sys.exit(1)

    input_file = sys.argv[1]
    out_pdf = sys.argv[2] if len(sys.argv) > 2 else "output/gstr3b_statement.pdf"

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    generate_pdf(data, out_pdf)


if __name__ == "__main__":
    main()
