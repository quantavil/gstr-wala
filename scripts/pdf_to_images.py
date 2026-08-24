#!/usr/bin/env python3
"""Multi-Page PDF to Image Converter for AI Vision Ingestion.

Features:
  1. Multi-Page Splitting: Automatically iterates through every page (Page 1, 2, 3... N).
  2. Clean Folder Organization: Creates a dedicated subfolder per document:
     `work/images/<doc_name>/page_001.png`
     `work/images/<doc_name>/page_002.png`
  3. High-Fidelity Rendering: Uses `pypdfium2` (Google Chrome PDFium C++ engine) at configurable DPI (150–300 DPI).
  4. Hybrid Extraction: Extracts digital text/tables via `pdfplumber` alongside rendered images.
  5. Manifest Index: Generates `work/images/image_manifest.json` with page mapping and image links.

Usage:
  python3 scripts/pdf_to_images.py <invoice.pdf|docs_folder> [output_dir] [--dpi 200]
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pypdfium2 as pdfium
import pdfplumber


def sanitize_filename(name: str) -> str:
    """Sanitizes document names for clean folder structures."""
    return re.sub(r"[^A-Za-z0-9_\-\.]", "_", name).strip("_")


def convert_multipage_pdf(
    pdf_path: str,
    base_output_dir: str = "work/images",
    dpi: int = 200,
    extract_text: bool = True
) -> Dict[str, Any]:
    """Splits and renders every page of a multi-page PDF into dedicated image files."""
    doc_raw_name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc_slug = sanitize_filename(doc_raw_name)
    doc_output_dir = os.path.join(base_output_dir, doc_slug)
    os.makedirs(doc_output_dir, exist_ok=True)

    pdf = pdfium.PdfDocument(pdf_path)
    num_pages = len(pdf)

    # Extract digital text per page if present
    extracted_texts = []
    if extract_text:
        try:
            with pdfplumber.open(pdf_path) as plum_pdf:
                for p in plum_pdf.pages:
                    extracted_texts.append(p.extract_text() or "")
        except Exception:
            extracted_texts = [""] * num_pages

    rendered_pages = []

    # Render every single page: Page 1, Page 2, ... Page N
    for page_idx in range(num_pages):
        page_num = page_idx + 1
        page = pdf[page_idx]

        # 72 DPI is standard base -> scale factor
        scale = dpi / 72.0
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()

        img_filename = f"page_{page_num:03d}.png"
        img_path = os.path.join(doc_output_dir, img_filename)
        pil_image.save(img_path, format="PNG", optimize=True)

        text_content = extracted_texts[page_idx] if page_idx < len(extracted_texts) else ""

        rendered_pages.append({
            "page_number": page_num,
            "image_filename": img_filename,
            "image_path": os.path.abspath(img_path),
            "image_relative_path": os.path.relpath(img_path, os.path.abspath(".")),
            "width": pil_image.width,
            "height": pil_image.height,
            "dpi": dpi,
            "has_digital_text": bool(text_content.strip()),
            "text_snippet": text_content[:250].strip() if text_content else ""
        })

    return {
        "doc_name": doc_raw_name,
        "doc_slug": doc_slug,
        "original_pdf": os.path.abspath(pdf_path),
        "total_pages": num_pages,
        "doc_output_dir": os.path.abspath(doc_output_dir),
        "pages": rendered_pages
    }


def batch_convert_all_documents(
    input_path: str,
    output_dir: str = "work/images",
    dpi: int = 200
) -> Dict[str, Any]:
    """Scans and batch processes all single and multi-page PDFs."""
    pdf_files = []
    if os.path.isdir(input_path):
        for root, _, files in os.walk(input_path):
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(root, f))
    elif os.path.isfile(input_path) and input_path.lower().endswith(".pdf"):
        pdf_files.append(input_path)

    documents = []
    total_images_count = 0

    for pdf_f in sorted(pdf_files):
        try:
            doc_result = convert_multipage_pdf(pdf_f, base_output_dir=output_dir, dpi=dpi)
            documents.append(doc_result)
            total_images_count += doc_result["total_pages"]
        except Exception as e:
            print(f"Warning: Failed to convert '{pdf_f}': {e}")

    manifest = {
        "total_pdf_documents": len(pdf_files),
        "total_rendered_page_images": total_images_count,
        "dpi": dpi,
        "base_output_dir": os.path.abspath(output_dir),
        "documents": documents
    }

    manifest_path = os.path.join(output_dir, "image_manifest.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f_out:
        json.dump(manifest, f_out, indent=2)

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Multi-Page PDF to Image Page-by-Page Splitter for AI Vision")
    parser.add_argument("input_path", help="PDF file or directory containing PDFs")
    parser.add_argument("output_dir", nargs="?", default="work/images", help="Output base directory")
    parser.add_argument("--dpi", type=int, default=200, help="Image DPI resolution (default: 200)")

    args = parser.parse_args()

    if not os.path.exists(args.input_path):
        sys.exit(f"Error: Input path '{args.input_path}' not found.")

    res = batch_convert_all_documents(args.input_path, args.output_dir, dpi=args.dpi)

    print("=" * 75)
    print(" MULTI-PAGE PDF TO IMAGE SPLITTER (Page 1, 2, 3... Visual Ingestion)")
    print("=" * 75)
    print(f"Total PDF Documents: {res['total_pdf_documents']}")
    print(f"Total Rendered Images: {res['total_rendered_page_images']}")
    print(f"Output Directory: {res['base_output_dir']}")
    print(f"Manifest File: {os.path.join(res['base_output_dir'], 'image_manifest.json')}")
    print("=" * 75)

    for doc in res["documents"]:
        print(f"\n📄 Document: {doc['doc_name']} ({doc['total_pages']} pages)")
        print(f"   Folder: {doc['doc_output_dir']}")
        for p in doc["pages"]:
            status_text = " [Digital Text]" if p["has_digital_text"] else " [Scanned/Image]"
            print(f"   • Page {p['page_number']}: {p['image_filename']} ({p['width']}x{p['height']}px){status_text}")


if __name__ == "__main__":
    main()
