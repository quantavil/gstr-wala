"""Pytest suite verifying strict GSTN Official Offline Utility v3.x schema compliance."""

import json
import os

from scripts.bridge_gstr1_to_gstr3b import bridge_gstr1_and_2b_to_3b
from scripts.generate_gstr1_json import generate_portal_gstr1
from scripts.generate_gstr3b_json import generate_portal_gstr3b
from scripts.reconcile_gstr2b import flatten_gstr2b, reconcile

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_official_gstr1_offline_format():
    with open(os.path.join(FIXTURES_DIR, "official_gstn_gstr1.json")) as f:
        g1_data = json.load(f)

    portal_payload = generate_portal_gstr1(g1_data)

    # Assert mandatory official GSTN root keys
    for key in ["gstin", "fp", "gt", "cur_gt", "b2b", "b2cl", "b2cs", "cdnr", "exp", "hsn", "doc_issue"]:
        assert key in portal_payload

    # Check B2B structure
    assert len(portal_payload["b2b"]) == 2
    for b2b_entry in portal_payload["b2b"]:
        assert "ctin" in b2b_entry
        assert "inv" in b2b_entry
        for inv in b2b_entry["inv"]:
            assert "inum" in inv
            assert "idt" in inv
            assert "val" in inv
            assert "pos" in inv
            assert "itms" in inv

    # Check CDNR (Table 9B)
    assert len(portal_payload["cdnr"]) == 1
    assert portal_payload["cdnr"][0]["ctin"] == "29AAAAA0000A1ZY"
    assert portal_payload["cdnr"][0]["nt"][0]["nt_num"] == "CDN-2026-001"
    assert portal_payload["cdnr"][0]["nt"][0]["ntty"] == "C"

    # Check Table 12 HSN data
    assert len(portal_payload["hsn"]["data"]) >= 5


def test_official_gstr2b_download_parsing():
    with open(os.path.join(FIXTURES_DIR, "official_gstn_gstr2b.json")) as f:
        g2b_data = json.load(f)

    records = flatten_gstr2b(g2b_data)

    # Must find B2B, CDNR, ISD, and IMPG
    sections = {r["section"] for r in records}
    assert "B2B" in sections
    assert "CDNR" in sections
    assert "ISD" in sections
    assert "IMPG" in sections

    # IMPG check
    impg_recs = [r for r in records if r["section"] == "IMPG"]
    assert len(impg_recs) == 1
    assert impg_recs[0]["inum"] == "BOE-887766"
    assert impg_recs[0]["iamt"] == 90000.0


def test_full_bridge_and_gstr3b_generation():
    with open(os.path.join(FIXTURES_DIR, "official_gstn_gstr1.json")) as f:
        g1_data = json.load(f)
    with open(os.path.join(FIXTURES_DIR, "official_gstn_gstr2b.json")) as f:
        g2b_data = json.load(f)

    # Empty purchase register to check bridging
    recon_data = reconcile([], g2b_data)
    g3b_input = bridge_gstr1_and_2b_to_3b(g1_data, recon_data)

    g3b_portal = generate_portal_gstr3b(g3b_input)
    assert g3b_portal["gstin"] == "27AAAAA0000A1Z2"
    assert g3b_portal["ret_period"] == "042026"
    assert "sup_details" in g3b_portal
    assert "itc_elg" in g3b_portal
    assert "tx_pmt" in g3b_portal
