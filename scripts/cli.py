#!/usr/bin/env python3
"""Typer & Rich-powered interactive CLI for gstr-wala.

Usage:
  gstr-wala pipeline --sales sales.json --purchases purchases.json --gstr2b gstr2b.json
  gstr-wala validate <file>
  gstr-wala reconcile <purchases> <gstr2b> [--fast]
  gstr-wala ingest-pdf <docs_folder> [--output-dir work/images] [--force-image]
  gstr-wala report <gstr3b_input> [output_pdf]
"""

import json
import os
import sys

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scripts.bridge_gstr1_to_gstr3b import (
    bridge_gstr1_and_2b_to_3b,
    check_drc_mismatch_risks,
)
from scripts.constants import detect_return_type
from scripts.generate_filing_pack import (
    generate_gstr1_filing_pack,
    generate_gstr3b_filing_pack,
    generate_reconciliation_report,
    validate_against_schema,
)
from scripts.generate_gstr1_json import generate_portal_gstr1
from scripts.generate_gstr3b_json import generate_portal_gstr3b
from scripts.generate_pdf_statement import generate_pdf
from scripts.gst_engine import compute_gstr1_tables
from scripts.ingest_pdf_vision import batch_convert_all_documents
from scripts.reconcile_fast import reconcile_polars_rapidfuzz
from scripts.reconcile_gstr2b import flatten_gstr2b, reconcile
from scripts.utils import safe_float
from scripts.validate_gst_input import validate_gstr1_input, validate_gstr3b_input

app = typer.Typer(
    name="gstr-wala",
    help="Deterministic AI Agent & Python Engine Suite for Indian GST Compliance",
    add_completion=False
)
console = Console()


@app.command()
def pipeline(
    sales: str = typer.Option(..., "--sales", "-s", help="Path to Sales Register JSON"),
    purchases: str = typer.Option(..., "--purchases", "-p", help="Path to Purchase Register JSON"),
    gstr2b: str = typer.Option(..., "--gstr2b", "-b", help="Path to official GSTR-2B JSON"),
    output_dir: str = typer.Option("output", "--output-dir", "-o", help="Output directory for filing packs"),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Generate printable CA PDF statement")
) -> None:
    """Executes the complete deterministic end-to-end GST return pipeline."""
    console.print(Panel.fit(
        "[bold green]gstr-wala[/bold green] [cyan]• Indian GST Return Filing Pipeline[/cyan]\n"
        "[dim]Deterministic Python Engines • Rule 88A Optimization • Zero External Data Leaks[/dim]",
        border_style="green"
    ))

    os.makedirs(output_dir, exist_ok=True)

    # 1. Ingest Sales
    console.print("\n[bold yellow]Step 1/6:[/bold yellow] Ingesting and Validating Sales Register...")
    with open(sales, encoding="utf-8") as f:
        g1_data = json.load(f)
    v1 = validate_gstr1_input(g1_data)
    if not v1.is_valid:
        console.print("[bold red]Validation Failed:[/bold red]")
        for e in v1.errors:
            console.print(f"  [red]✗[/red] {e}")
        raise typer.Exit(1)
    console.print(f"  [green]✓[/green] Validated {len(g1_data.get('invoices', []))} sales invoices.")

    # 2. Reconcile Purchases
    console.print("\n[bold yellow]Step 2/6:[/bold yellow] Reconciling Purchase Register against GSTR-2B...")
    with open(purchases, encoding="utf-8") as f:
        pr_data = json.load(f)
    with open(gstr2b, encoding="utf-8") as f:
        g2b_data = json.load(f)

    pr_list = pr_data.get("purchases", pr_data) if isinstance(pr_data, dict) else pr_data
    recon_res = reconcile(pr_list, g2b_data)
    recon_out = os.path.join(output_dir, "reconciliation.json")
    with open(recon_out, "w", encoding="utf-8") as f:
        json.dump(recon_res, f, indent=2)

    s = recon_res["summary"]
    console.print(f"  [green]✓[/green] Matched: [bold]{s['exact_matched_count']}[/bold] exact, [bold]{s['tolerance_matched_count']}[/bold] tolerance.")
    console.print(f"  [green]✓[/green] Deferred (Missing in 2B): [bold]{s['in_books_only_count']}[/bold], Blocked (17(5)): [bold]{s['blocked_17_5_count']}[/bold].")

    # 3. Generate GSTR-1 Portal JSON
    console.print("\n[bold yellow]Step 3/6:[/bold yellow] Computing GSTR-1 & Generating Offline Portal JSON...")
    g1_portal = generate_portal_gstr1(g1_data)
    g1_out = os.path.join(output_dir, "gstr1_portal.json")
    with open(g1_out, "w", encoding="utf-8") as f:
        json.dump(g1_portal, f, indent=2)
    console.print(f"  [green]✓[/green] Written: [cyan]{g1_out}[/cyan]")

    # 4. Bridge to GSTR-3B & DRC Check
    console.print("\n[bold yellow]Step 4/6:[/bold yellow] Auto-Populating GSTR-3B & Scanning DRC-01B/C Risks...")
    g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_res)
    g3b_in_path = os.path.join(output_dir, "gstr3b_input.json")
    with open(g3b_in_path, "w", encoding="utf-8") as f:
        json.dump(g3b_input, f, indent=2)

    comp1 = compute_gstr1_tables(g1_data)
    t4_pop = recon_res.get("gstr3b_table_4_auto_population", {})
    tot_2b_itc = sum(
        safe_float(t4_pop.get(k, {}).get("total", 0.0))
        for k in ("table_4_a_1_import_goods", "table_4_a_3_rcm_inward", "table_4_a_4_isd", "table_4_a_5_all_other_itc")
    )
    drc_res = check_drc_mismatch_risks(comp1["summary"], g3b_input, tot_2b_itc)
    console.print(f"  [green]✓[/green] DRC-01B Outward Risk: {drc_res['drc_01b_liability_mismatch']['warning']}")
    console.print(f"  [green]✓[/green] DRC-01C Inward ITC Risk: {drc_res['drc_01c_itc_mismatch']['warning']}")

    # 5. Optimize Rule 88A & GSTR-3B Portal JSON
    console.print("\n[bold yellow]Step 5/6:[/bold yellow] Solving Rule 88A Linear Set-Off & Generating GSTR-3B JSON...")
    g3b_portal = generate_portal_gstr3b(g3b_input)
    g3b_out = os.path.join(output_dir, "gstr3b_portal.json")
    with open(g3b_out, "w", encoding="utf-8") as f:
        json.dump(g3b_portal, f, indent=2)
    console.print(f"  [green]✓[/green] Written: [cyan]{g3b_out}[/cyan]")

    # 6. CA Filing Packs & Schema Validation & PDF
    console.print("\n[bold yellow]Step 6/6:[/bold yellow] Validating Portal Schemas & Generating CA Filing Packs...")
    schema_g1 = os.path.join(os.path.dirname(__file__), "..", "schemas", "gstr1_portal_schema.json")
    schema_g3b = os.path.join(os.path.dirname(__file__), "..", "schemas", "gstr3b_portal_schema.json")
    errs_g1 = validate_against_schema(g1_portal, schema_g1)
    errs_g3b = validate_against_schema(g3b_portal, schema_g3b)
    if errs_g1 or errs_g3b:
        console.print("[bold red]Portal Schema Validation Failed:[/bold red]")
        for err in errs_g1:
            console.print(f"  [red]✗ GSTR-1 Schema Error:[/red] {err}")
        for err in errs_g3b:
            console.print(f"  [red]✗ GSTR-3B Schema Error:[/red] {err}")
        raise typer.Exit(1)
    console.print("  [green]✓[/green] GSTR-1 and GSTR-3B Portal JSONs strictly conform to canonical schemas.")

    generate_gstr1_filing_pack(g1_data, os.path.join(output_dir, "gstr1_filing_pack.md"))
    generate_gstr3b_filing_pack(g3b_input, os.path.join(output_dir, "gstr3b_filing_pack.md"))
    generate_reconciliation_report(recon_res, os.path.join(output_dir, "reconciliation_report.md"))

    pdf_ok = False
    if pdf:
        pdf_path = os.path.join(output_dir, "gstr3b_statement.pdf")
        pdf_ok = generate_pdf(g3b_input, pdf_path)
        if not pdf_ok:
            console.print("  [yellow]![/yellow] Warning: PDF statement generation failed or skipped; HTML version saved.")

    # Rich Summary Table
    table = Table(title="[bold green]Filing Outputs Generated Successfully[/bold green]", border_style="cyan")
    table.add_column("Artifact", style="bold")
    table.add_column("Path", style="cyan")
    table.add_column("Action", style="magenta")

    table.add_row("GSTR-1 Portal JSON", g1_out, "Upload to GST Portal Offline Tool")
    table.add_row("GSTR-3B Portal JSON", g3b_out, "Upload / Verify on GST Portal")
    table.add_row("GSTR-1 Summary Pack", os.path.join(output_dir, "gstr1_filing_pack.md"), "Client / CA Review")
    table.add_row("GSTR-3B Summary Pack", os.path.join(output_dir, "gstr3b_filing_pack.md"), "Challan & Offset Review")
    table.add_row("2B Reconciliation Audit", os.path.join(output_dir, "reconciliation_report.md"), "Vendor Follow-up")
    if pdf and pdf_ok:
        table.add_row("PDF Statement", os.path.join(output_dir, "gstr3b_statement.pdf"), "Printable Tax Audit Record")

    console.print("\n", table)


@app.command()
def validate(file_path: str = typer.Argument(..., help="Path to GSTR-1 or GSTR-3B JSON input")) -> None:
    """Strictly validates a sales, purchase, or return input JSON."""
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    try:
        ret_type = detect_return_type(data)
    except ValueError as e:
        console.print(f"[bold red]✗ Validation FAILED:[/bold red] {e}")
        raise typer.Exit(1) from None

    if ret_type == "GSTR-1":
        res = validate_gstr1_input(data)
    else:
        res = validate_gstr3b_input(data)

    if res.is_valid:
        console.print("[bold green]✓ Validation PASSED: All statutory format and checksum checks hold.[/bold green]")
    else:
        console.print(f"[bold red]✗ Validation FAILED with {len(res.errors)} error(s):[/bold red]")
        for err in res.errors:
            console.print(f"  [red]•[/red] {err}")
        raise typer.Exit(1)


@app.command(name="reconcile")
@app.command(name="reconcile-cmd", hidden=True)
def reconcile_command(
    purchases: str = typer.Argument(..., help="Purchase Register JSON"),
    gstr2b: str = typer.Argument(..., help="GSTR-2B JSON"),
    fast: bool = typer.Option(False, "--fast", help="Use Rust/C++ accelerated Polars + RapidFuzz engine"),
    cutoff: str = typer.Option(None, "--cutoff", help="Section 16(4) evaluation cutoff date (DD-MM-YYYY); defaults to return-period due date")
) -> None:
    """Reconciles Purchase Register against GSTR-2B."""
    with open(purchases, encoding="utf-8") as f:
        pr = json.load(f)
    with open(gstr2b, encoding="utf-8") as f:
        g2b = json.load(f)

    pr_list = pr.get("purchases", pr) if isinstance(pr, dict) else pr

    if fast:
        g2b_flat = flatten_gstr2b(g2b)
        res = reconcile_polars_rapidfuzz(pr_list, g2b_flat)
        console.print(json.dumps(res, indent=2))
    else:
        res = reconcile(pr_list, g2b, _16_4_cutoff=cutoff)
        console.print(json.dumps(res, indent=2))


@app.command(name="ingest-pdf")
@app.command(name="pdf-to-images", hidden=True)
@app.command(name="pdf-to-images-cmd", hidden=True)
def ingest_pdf(
    input_path: str = typer.Argument(..., help="Path to PDF file or directory of PDFs"),
    output_dir: str = typer.Option("work/images", "--output-dir", "-o", help="Output directory for rendered images"),
    dpi: int = typer.Option(200, "--dpi", help="Image rendering resolution in DPI"),
    force_image: bool = typer.Option(False, "--force-image", "-f", help="Force image vision mode for all pages")
) -> None:
    """Batch rasterizes multi-page PDF invoices into structured Page 1, 2, 3... images for AI vision."""
    res = batch_convert_all_documents(input_path, output_dir=output_dir, dpi=dpi, force_image=force_image)
    console.print(f"[bold green]✓ Converted {res['total_pdf_documents']} PDF(s) into {res['total_rendered_page_images']} high-res page images in '{output_dir}/'[/bold green]")


@app.command()
def report(
    gstr3b_input: str = typer.Argument(..., help="GSTR-3B Input JSON"),
    output_pdf: str = typer.Argument("output/gstr3b_statement.pdf", help="Output PDF path")
) -> None:
    """Renders printable CA tax audit and filing statements via Jinja2 & WeasyPrint."""
    with open(gstr3b_input, encoding="utf-8") as f:
        data = json.load(f)
    generate_pdf(data, output_pdf)


if __name__ == "__main__":
    app()
