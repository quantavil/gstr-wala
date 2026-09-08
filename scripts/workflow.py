"""Shared input contracts and atomic publication for local preparation runs."""

import functools
import hashlib
import inspect
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.models import validate_date_str, validate_gstin_str
from scripts.utils import safe_float_strict

HEADS = ("iamt", "camt", "samt", "csamt")
MONEY_FIELDS = (*HEADS, "txval", "val", "rt", "unpaid_value")
BOOL_FIELDS = ("is_blocked_17_5", "rcm_paid", "rule_37_reversal", "previously_claimed")


def validate_tree(value: Any, path: str = "input") -> None:
    """Reject credentials, non-finite money, invalid booleans and malformed nodes."""
    if isinstance(value, dict):
        for key, item in value.items():
            label = f"{path}.{key}"
            if any(s in key.lower() for s in ("password", "passwd", "otp", "secret", "api_key", "auth_token", "private_key")):
                raise ValueError(f"{label}: credentials must not appear in tax data")
            if key in MONEY_FIELDS:
                if item is None or isinstance(item, bool):
                    raise ValueError(f"{label}: expected a finite amount")
                safe_float_strict(item)
            if key in BOOL_FIELDS and not isinstance(item, bool):
                raise ValueError(f"{label}: expected true or false, not a string")
            validate_tree(item, label)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"{path}[{index}]: expected a record object")
            validate_tree(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: expected a finite number")


def require_return(data: Any) -> None:
    from scripts.validate_gst_input import validate_gst_payload

    validate_tree(data)
    result = validate_gst_payload(data)
    if not result.is_valid:
        raise ValueError("; ".join(result.errors))


def purchase_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("purchases", data.get("invoices"))
    if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
        raise ValueError("Purchase register must be an array or an object with a purchases/invoices array")
    validate_tree(data, "purchases")
    seen = set()
    for index, record in enumerate(data):
        for key in ("ctin", "inum", "idt", "txval"):
            if key not in record or record[key] in (None, ""):
                raise ValueError(f"Purchase row {index + 1}: missing {key}")
        if not any(head in record for head in HEADS):
            raise ValueError(f"Purchase row {index + 1}: missing tax amount columns")
        if record["ctin"] != "ICEGATE" and record.get("rchrg") != "Y":
            validate_gstin_str(record["ctin"])
        validate_date_str(record["idt"])
        identity = (record["ctin"], record["inum"], record["idt"], record.get("port_code", ""))
        if identity in seen:
            raise ValueError(f"Duplicate purchase document {identity}; consolidate invoice lines")
        seen.add(identity)
    return data


def validate_2b(data: Any, gstin: str | None = None, period: str | None = None) -> None:
    if not isinstance(data, dict):
        raise ValueError("GSTR-2B must be an object")
    validate_tree(data, "gstr2b")
    nested = data.get("data", {})
    if not isinstance(nested, dict):
        raise ValueError("GSTR-2B data must be an object")
    block = nested.get("docdata", data.get("docdata", data))
    if not isinstance(block, dict):
        raise ValueError("GSTR-2B docdata must be an object")
    supported = {"b2b", "b2ba", "cdnr", "cdna", "isd", "isda", "impg", "impgsez"}
    if not supported.intersection(block):
        raise ValueError("GSTR-2B has no recognised document sections; use explicit empty arrays for a nil statement")
    for section, rows in block.items():
        if section not in supported:
            if isinstance(rows, (dict, list)) and rows:
                raise ValueError(f"Unsupported GSTR-2B section {section!r}; review/import it explicitly rather than dropping it")
            continue
        if not isinstance(rows, list):
            raise ValueError(f"GSTR-2B {section} must be an array")
        aliases = (("inv", "invoices") if section in ("b2b", "b2ba") else
                   ("nt", "notes") if section in ("cdnr", "cdna") else
                   ("doclist", "docs") if section in ("isd", "isda") else ("boe", "boes"))
        for row in rows:
            if section in ("impg", "impgsez") and row.get("boenum"):
                continue
            if not any(key in row and isinstance(row[key], list) for key in aliases):
                raise ValueError(f"GSTR-2B {section} record requires a {aliases[0]} array")
    for field, expected in (("gstin", gstin), ("fp", period)):
        actual = data.get(field) or nested.get(field) or block.get(field)
        if expected and actual != expected:
            raise ValueError(f"GSTR-2B {field} {actual!r} does not match return {expected!r}")


def atomic_output(function):
    """Publish a complete run by directory rename; never overwrite an earlier run."""
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        target = Path(bound.arguments["output_dir"]).resolve()
        if target.exists():
            raise ValueError(f"Output directory already exists: {target}. Choose a fresh run directory.")
        target.parent.mkdir(parents=True, exist_ok=True)
        input_hashes = {
            key: hashlib.sha256(Path(bound.arguments[key]).read_bytes()).hexdigest()
            for key in ("sales", "purchases", "gstr2b", "context") if bound.arguments.get(key)
        }
        with tempfile.TemporaryDirectory(prefix=".gstr-stage-", dir=target.parent) as temporary:
            staging = Path(temporary) / "run"
            rules_path = Path(__file__).resolve().parents[1] / "config/rules_manifest.json"
            rules_snapshot = rules_path.read_bytes()
            from scripts.constants import reload_manifest
            reload_manifest()
            bound.arguments["output_dir"] = str(staging)
            result = function(*bound.args, **bound.kwargs)
            for key, digest in input_hashes.items():
                if hashlib.sha256(Path(bound.arguments[key]).read_bytes()).hexdigest() != digest:
                    raise ValueError(f"Source {key} changed during computation; rerun with stable input files")
            if rules_path.read_bytes() != rules_snapshot:
                raise ValueError("Rules changed during computation; rerun with a stable rule snapshot")
            with (staging / "rules_snapshot.json").open("wb") as stream:
                stream.write(rules_snapshot)
            manifest_path = staging / "review_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs"] = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(staging.iterdir()) if path.is_file() and path != manifest_path
            }
            with manifest_path.open("w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2, allow_nan=False)
            os.rename(staging, target)
        print(f"Published complete draft run: {target}")
        return result
    return wrapped


def write_review_manifest(output_dir: str, sources: dict[str, str], reconciliation: dict, warnings: list[str]) -> None:
    """One consolidated, source-linked exception report plus reproducibility hashes."""
    folder = Path(output_dir)
    issues: list[dict[str, Any]] = [{"reason": reason} for reason in warnings]
    details = reconciliation.get("details", {})
    for category in ("review_required", "value_mismatches", "in_books_only", "blocked_17_5", "rule_37_reversals", "ineligible_2b"):
        issues.extend({"category": category, **record} for record in details.get(category, []))
    for index, issue in enumerate(issues, 1):
        issue["id"] = f"R{index:04d}"
    manifest = {
        "status": "DRAFT_REQUIRES_CA_REVIEW",
        "schema_version": "1.0",
        "sources": {key: {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()} for key, path in sources.items()},
        "evaluation_cutoff": reconciliation.get("evaluation_cutoff"),
        "issues": issues,
    }
    with (folder / "review_manifest.json").open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
    lines = ["# Consolidated CA review", "", "Status: DRAFT — requires professional review.", ""]
    for index, issue in enumerate(issues, 1):
        book = issue.get("books_invoice", issue.get("gstr2b_invoice", issue))
        lines.append(f"{index}. [{issue['id']}] {issue.get('category', 'context')}: {book.get('ctin', '')} / {book.get('inum', '')} — {issue.get('reason', 'Review source values in review_manifest.json')}")
    if not issues:
        lines.append("No recorded exceptions. Review return totals, ledgers and completeness before filing.")
    with (folder / "ca_review.md").open("w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def approve_run(directory: str, reviewer: str, decisions: dict[str, str]) -> None:
    """Record a local review of unchanged outputs; never file or recalculate tax."""
    folder = Path(directory)
    manifest_path = folder / "review_manifest.json"
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    expected = {issue["id"] for issue in manifest["issues"]}
    if not reviewer.strip() or not isinstance(decisions, dict) or set(decisions) != expected:
        raise ValueError("Supply reviewer name and one decision note for every review issue ID")
    if any(not isinstance(note, str) or not note.strip() for note in decisions.values()):
        raise ValueError("Every review decision needs a nonempty explanation")
    if not manifest.get("outputs"):
        raise ValueError("Run has no output fingerprints; regenerate with the current pipeline")
    for name, digest in manifest["outputs"].items():
        if Path(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Output changed since preparation: {name}; regenerate and review again")
    approval = {"reviewer": reviewer, "reviewed_at": datetime.now(UTC).isoformat(),
                "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
                "decisions": decisions, "status": "REVIEWED_DRAFT_NOT_FILED"}
    # Exclusive creation preserves the original review record.
    with (folder / "review_approval.json").open("x", encoding="utf-8") as stream:
        json.dump(approval, stream, indent=2)


def verify_run(directory: str) -> str:
    """Detect changed artifacts or an approval that no longer matches its manifest."""
    folder = Path(directory)
    raw = (folder / "review_manifest.json").read_bytes()
    manifest = json.loads(raw)
    if not manifest.get("outputs"):
        raise ValueError("Missing output fingerprints")
    for name, digest in manifest["outputs"].items():
        if Path(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Output changed since preparation: {name}")
    approval_path = folder / "review_approval.json"
    if not approval_path.exists():
        return "DRAFT_REQUIRES_CA_REVIEW"
    approval = json.loads(approval_path.read_text())
    if approval.get("manifest_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Review manifest changed after approval; review is no longer valid")
    return "REVIEWED_DRAFT_NOT_FILED"
