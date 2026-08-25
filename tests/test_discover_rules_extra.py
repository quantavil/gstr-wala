"""Coverage for discover_statutory_rules (Plan 12)."""

import json

from scripts.discover_statutory_rules import (
    fetch_portal_advisories,
    run_discovery,
    scan_for_regulatory_updates,
)


def test_fetch_bundled_snapshot():
    advisories, mode = fetch_portal_advisories(live=False)
    assert mode == "bundled_snapshot"
    assert len(advisories) >= 4
    assert any("B2CL" in a["title"] for a in advisories)


def test_scan_regulatory_updates_dedup():
    advisories = [
        {"title": "CBIC Threshold Revision for B2CL and Rate Change", "url": "http://example.com/a", "source": "Test"},
        {"title": "CBIC Threshold Revision for B2CL and Rate Change", "url": "http://example.com/a", "source": "Test"},
        {"title": "Unrelated random news item with no keywords at all", "url": "http://example.com/b", "source": "Test"},
    ]
    updates = scan_for_regulatory_updates(advisories)
    # deduped, only first qualifies (has threshold/rate)
    assert len(updates) == 1
    assert updates[0]["requires_review"] is True
    assert len(updates[0]["categories"]) >= 1


def test_run_discovery_save_patch(tmp_path, capsys):
    patch_path = str(tmp_path / "discover_patch.json")
    run_discovery(live=False, save_patch=patch_path)
    out = capsys.readouterr().out
    assert "STATUTORY COMPLIANCE DISCOVERY RADAR" in out
    data = json.loads(open(patch_path).read())
    assert "discovered_triggers" in data
    assert "patch_id" in data
