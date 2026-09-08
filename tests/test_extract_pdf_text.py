import json

import pymupdf
import pytest

from scripts.extract_pdf_text import extract_batch


def make_pdf(path, text):
    with pymupdf.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
        doc.save(path)


def test_full_text_and_coordinates_without_images(tmp_path):
    source = tmp_path / "invoice.pdf"
    make_pdf(source, "Invoice 190\n" + "Taxable 40000\n" * 30 + "TOTAL 47200")
    output = tmp_path / "text.json"
    result = extract_batch(source, output)
    page = result["documents"][0]["pages"][0]
    assert len(page["text"]) > 250
    assert "TOTAL 47200" in page["text"]
    assert page["words"]
    assert result["ocr_used"] is False
    assert json.loads(output.read_text())["documents"][0]["sha256"]
    assert not list(tmp_path.glob("*.png"))
    with pytest.raises(FileExistsError):
        extract_batch(source, output)


def test_blank_page_fails_entire_batch(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    make_pdf(source / "a.pdf", "Invoice 190")
    make_pdf(source / "b.pdf", "")
    output = tmp_path / "text.json"
    with pytest.raises(ValueError, match="OCR is disabled"):
        extract_batch(source, output)
    assert not output.exists()


def test_empty_folder_rejected(tmp_path):
    with pytest.raises(ValueError, match="containing PDFs"):
        extract_batch(tmp_path, tmp_path / "text.json")
