"""Local digital-PDF extraction. No OCR, rendering, or tax-field inference."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pymupdf


def extract_document(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError(f"PDF exceeds 50 MB: {path.name}")
    raw = path.read_bytes()
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError(f"Encrypted PDF requires an unlocked copy: {path.name}")
        if not 0 < len(doc) <= 500:
            raise ValueError(f"PDF must contain 1-500 pages: {path.name}")
        pages = []
        for number, page in enumerate(doc, 1):
            text = page.get_text("text", sort=True).strip()
            if not text:
                raise ValueError(f"No embedded text: {path.name}, page {number}; OCR is disabled")
            pages.append({"page_number": number, "text": text,
                          "words": page.get_text("words", sort=True)})
    return {"source": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "pages": pages}


def extract_batch(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    paths = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf") if source.is_dir() else [source]
    if not paths or any(not p.is_file() or p.suffix.lower() != ".pdf" for p in paths):
        raise ValueError("Provide a PDF or a folder containing PDFs")
    result = {"status": "EXTRACTED_TEXT_REQUIRES_FIELD_REVIEW", "ocr_used": False,
              "documents": [extract_document(p) for p in paths]}
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(payload)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract_batch(args.source, args.output)


if __name__ == "__main__":
    main()
