"""Pytest suite for Multi-Page PDF to Image Page-by-Page Splitter."""

import os
import pytest
from scripts.ingest_pdf_vision import convert_multipage_pdf, batch_convert_all_documents
from scripts.generate_pdf_statement import generate_pdf



def test_multipage_pdf_page_by_page_splitting(tmp_path):
    pytest.importorskip("weasyprint")
    sample_g3b = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {"txval": 100000.0, "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
        }
    }
    sample_pdf = str(tmp_path / "invoice_multi.pdf")
    generate_pdf(sample_g3b, sample_pdf)

    # Render into structured images
    img_base_dir = str(tmp_path / "images")
    res = convert_multipage_pdf(sample_pdf, base_output_dir=img_base_dir, dpi=150)

    assert res["total_pages"] >= 1
    assert len(res["pages"]) == res["total_pages"]
    assert res["doc_name"] == "invoice_multi"

    for p in res["pages"]:
        assert p["page_number"] >= 1
        assert os.path.exists(p["image_path"])
        assert p["image_filename"].startswith("page_")
        assert p["width"] > 0
        assert p["height"] > 0
        assert p["extraction_strategy"] in ("DIGITAL_TEXT", "MULTIMODAL_AI_VISION")


def test_batch_convert_multi_document_manifest(tmp_path):
    pytest.importorskip("weasyprint")
    docs_dir = str(tmp_path / "docs")
    os.makedirs(docs_dir, exist_ok=True)

    sample_g3b = {
        "gstin": "27AAAAA0000A1Z2",
        "ret_period": "042026",
        "outward_supplies": {
            "taxable": {"txval": 50000.0, "camt": 4500.0, "samt": 4500.0}
        }
    }
    pdf1 = os.path.join(docs_dir, "vendor_bill_1.pdf")
    pdf2 = os.path.join(docs_dir, "vendor_bill_2.pdf")
    generate_pdf(sample_g3b, pdf1)
    generate_pdf(sample_g3b, pdf2)

    out_img_dir = str(tmp_path / "batch_images")
    manifest = batch_convert_all_documents(docs_dir, output_dir=out_img_dir, dpi=150, force_image=True)

    assert manifest["total_pdf_documents"] == 2
    assert manifest["total_rendered_page_images"] >= 2
    assert manifest["force_image_mode"] is True
    assert len(manifest["documents"]) == 2
    assert os.path.exists(os.path.join(out_img_dir, "image_manifest.json"))
    for doc in manifest["documents"]:
        for page in doc["pages"]:
            assert page["extraction_strategy"] == "FORCED_IMAGE_VISION"


def test_ingest_relative_paths_and_dpi_cap(tmp_path):
    import pymupdf, json
    doc=pymupdf.open()
    doc.new_page()
    pdf=tmp_path/"a.pdf"
    doc.save(str(pdf))
    doc.close()
    from scripts.ingest_pdf_vision import batch_convert_all_documents
    out=tmp_path/"out"
    res=batch_convert_all_documents(str(pdf), output_dir=str(out), dpi=999)
    mf=json.loads((out/"image_manifest.json").read_text())
    assert mf["dpi"] <=300
    assert not mf["documents"][0]["original_pdf"].startswith("/")
    assert res["dpi"] <=300
