#!/usr/bin/env python3
"""Live Statutory Compliance Discovery Engine for Indian GST.

Features:
  1. Scans regulatory triggers from CBIC notifications & GSTN advisories:
     - Rate revisions & Slabs
     - B2CL / B2CS threshold changes
     - HSN reporting mandates (Table 12)
     - Due date extensions & Amnesty schemes
     - Late fee rationalization & interest caps
     - DRC-01B / DRC-01C mismatch threshold updates
  2. Formulates structured delta proposals for `scripts/compliance_radar.py`.

Usage:
  python3 scripts/discover_statutory_rules.py [--live] [--save-patch delta.json]
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

# Ensure root directory is on sys.path for standalone script invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.compliance_radar import load_rules_manifest

GST_PORTAL_NEWS_URL = "https://www.gst.gov.in/newsandupdates"

COMPLIANCE_KEYWORDS = {
    "threshold": "Threshold Revision (e.g. B2CL, E-Invoice, AATO)",
    "rate": "Tax Rate Change / Slabs",
    "table 12": "HSN Table 12 Reporting Mandate",
    "hsn": "HSN / SAC Code Requirement",
    "drc-01b": "DRC-01B Liability Mismatch Surveillance",
    "drc-01c": "DRC-01C ITC Mismatch Surveillance",
    "rule 88c": "Rule 88C Outward Tax Intimation",
    "rule 88d": "Rule 88D Inward ITC Intimation",
    "late fee": "Section 47 Late Fee Cap Rationalization",
    "interest": "Section 50 Daily Interest Rate",
    "due date": "Statutory Return Due Date Extension",
    "b2cl": "B2CL Invoice Reporting Threshold",
    "gstr-1a": "GSTR-1A Intra-Month Amendment Facility",
    "gstr-2b": "GSTR-2B ITC Matching & Generation Rules"
}

CANONICAL_KNOWN_ADVISORIES = [
    {
        "title": "CBIC Notification No. 12/2024-Central Tax: Reduction of B2CL threshold from Rs. 2.5 Lakh to Rs. 1.0 Lakh",
        "url": "https://taxinformation.cbic.gov.in/content-page/notification-detail/12-2024-CT",
        "source": "CBIC Central Tax Notification",
        "source_of_truth": "bundled_snapshot"
    },
    {
        "title": "GSTN Advisory: Mandatory bifurcation of Table 12 HSN Summary into Table 12A (B2B) and Table 12B (B2C)",
        "url": "https://www.gst.gov.in/newsandupdates/read/652",
        "source": "GSTN Official Advisory",
        "source_of_truth": "bundled_snapshot"
    },
    {
        "title": "GSTN Advisory: Automated Liability Intimation (DRC-01B under Rule 88C) and ITC Intimation (DRC-01C under Rule 88D)",
        "url": "https://www.gst.gov.in/newsandupdates/read/653",
        "source": "GSTN Systems Advisory",
        "source_of_truth": "bundled_snapshot"
    },
    {
        "title": "Advisory on Form GSTR-1A: New facility to amend/add outward supplies after GSTR-1 before filing GSTR-3B",
        "url": "https://www.gst.gov.in/newsandupdates/read/654",
        "source": "GSTN Systems Advisory",
        "source_of_truth": "bundled_snapshot"
    }
]


def fetch_portal_advisories(live: bool = False) -> tuple[list[dict[str, str]], str]:
    """Fetches latest advisories. If live=False, skips network entirely and uses bundled snapshot."""
    if not live:
        return list(CANONICAL_KNOWN_ADVISORIES), "bundled_snapshot"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    items: list[dict[str, str]] = []
    live_ok = False
    try:
        req = urllib.request.Request(GST_PORTAL_NEWS_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")

        matches = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE)
        for link, title in matches:
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            if len(clean_title) > 20 and not clean_title.startswith("View All") and "advisory" in clean_title.lower():
                full_link = link if link.startswith("http") else f"https://www.gst.gov.in{link}"
                items.append({
                    "title": clean_title,
                    "url": full_link,
                    "source": "GSTN Official News & Updates",
                    "source_of_truth": "live_feed"
                })
        if items:
            live_ok = True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"WARNING: live fetch failed ({e}) — showing bundled snapshot")

    # Merge canonical benchmark advisories
    items.extend(CANONICAL_KNOWN_ADVISORIES)
    return items, "live_synced" if live_ok else "bundled_snapshot"


def scan_for_regulatory_updates(advisories: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Analyzes raw advisories and extracts actionable statutory triggers."""
    updates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for adv in advisories:
        title = adv["title"]
        if title in seen:
            continue
        seen.add(title)

        title_lower = title.lower()
        matched_categories = []
        for kw, cat in COMPLIANCE_KEYWORDS.items():
            if kw in title_lower:
                matched_categories.append(cat)

        if matched_categories:
            updates.append({
                "title": title,
                "url": adv["url"],
                "source": adv["source"],
                "source_of_truth": adv.get("source_of_truth", "bundled_snapshot"),
                "categories": matched_categories,
                "requires_review": True
            })
    return updates


def run_discovery(live: bool = False, save_patch: str | None = None) -> None:
    print("=" * 75)
    print(" gstr-wala: STATUTORY COMPLIANCE DISCOVERY RADAR")
    print("=" * 75)
    if live:
        print("Scanning: [GSTN Portal News, CBIC Notifications, GST Council Advisories] (LIVE HTTP)...")
    else:
        print("Scanning: [Bundled Statutory Compliance Snapshot] (OFFLINE)...")

    manifest = load_rules_manifest()
    print(f"Active Compliance Manifest: v{manifest.get('manifest_version')} (Last Synced: {manifest.get('last_synced')})\n")

    advisories, mode = fetch_portal_advisories(live=live)
    regulatory_updates = scan_for_regulatory_updates(advisories)

    print(f"Analyzed advisories ({mode}). Identified {len(regulatory_updates)} active regulatory mandates:\n")

    for idx, upd in enumerate(regulatory_updates, 1):
        print(f"[{idx}] {upd['title']}")
        print(f"    • Triggers: {', '.join(upd['categories'])}")
        print(f"    • Source: {upd['url']} [{upd.get('source_of_truth', 'bundled_snapshot')}]")

    if save_patch:
        patch_payload = {
            "patch_id": f"AUTO_DISCOVERY_{len(regulatory_updates)}_TRIGGERS",
            "authority": "GSTN Live Advisory Radar" if mode == "live_synced" else "Bundled Snapshot",
            "discovered_triggers": regulatory_updates
        }
        with open(save_patch, "w", encoding="utf-8") as f:
            json.dump(patch_payload, f, indent=2)
        print(f"\n✓ Saved compliance discovery patch -> '{save_patch}'")

    print("\n" + "=" * 75)
    if mode == "live_synced":
        print(" DISCOVERY STATUS: Live Synced with GSTN Portal.")
    else:
        print(" DISCOVERY STATUS: Bundled Snapshot (Offline Mode).")
    print("=" * 75)


def main() -> None:
    parser = argparse.ArgumentParser(description="gstr-wala Live Statutory Discovery Engine")
    parser.add_argument("--live", action="store_true", help="Fetch live advisories via HTTP")
    parser.add_argument("--save-patch", help="Path to save candidate patch JSON")
    args = parser.parse_args()

    run_discovery(args.live, args.save_patch)


if __name__ == "__main__":
    main()
