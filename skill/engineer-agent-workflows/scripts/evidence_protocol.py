#!/usr/bin/env python3
"""Audit claim evidence, contradiction search, freshness, and conclusion boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from module_common import ModuleError, atomic_write_json, build_receipt


MODULE = "evidence-protocol"
VERSION = 1
SOURCE_TYPES = {
    "official_doc",
    "paper",
    "repository",
    "product",
    "user_behavior",
    "market",
    "test_output",
    "log",
    "filing",
}
CURRENT_CLAIM_TYPES = {"novelty", "market_gap", "best_plugin", "sota", "current_capability"}


def audit(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    claims = manifest.get("claims")
    evidence = manifest.get("evidence")
    if not isinstance(claims, list) or not claims:
        issues.append({"code": "claims_missing", "message": "claims must be non-empty"})
        claims = []
    if not isinstance(evidence, list) or not evidence:
        issues.append({"code": "evidence_missing", "message": "evidence must be non-empty"})
        evidence = []
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            issues.append({"code": "evidence_type", "message": "evidence entry must be object"})
            continue
        required = ["id", "source_type", "locator", "observed_at", "authority", "summary", "direction"]
        missing = [field for field in required if not item.get(field)]
        if missing:
            issues.append({"code": "evidence_fields", "id": item.get("id"), "missing": missing})
            continue
        if item["source_type"] not in SOURCE_TYPES:
            issues.append({"code": "source_type", "id": item["id"], "value": item["source_type"]})
        if item["direction"] not in {"supports", "contradicts", "negative_search"}:
            issues.append({"code": "direction", "id": item["id"]})
        if item["id"] in evidence_by_id:
            issues.append({"code": "duplicate_evidence_id", "id": item["id"]})
        evidence_by_id[item["id"]] = item
    for claim in claims:
        if not isinstance(claim, dict):
            issues.append({"code": "claim_type", "message": "claim entry must be object"})
            continue
        required = ["id", "text", "claim_type", "support_ids", "negative_ids", "boundary"]
        missing = [
            field
            for field in required
            if field not in claim or claim[field] is None or claim[field] == ""
        ]
        if missing:
            issues.append({"code": "claim_fields", "id": claim.get("id"), "missing": missing})
            continue
        support_ids = claim["support_ids"]
        negative_ids = claim["negative_ids"]
        if not isinstance(support_ids, list) or not support_ids:
            issues.append({"code": "support_missing", "id": claim["id"]})
            support_ids = []
        if not isinstance(negative_ids, list) or not negative_ids:
            issues.append({"code": "negative_search_missing", "id": claim["id"]})
            negative_ids = []
        unknown = [item for item in [*support_ids, *negative_ids] if item not in evidence_by_id]
        if unknown:
            issues.append({"code": "unknown_evidence", "id": claim["id"], "evidence_ids": unknown})
        if any(
            evidence_by_id[item].get("direction") != "supports"
            for item in support_ids
            if item in evidence_by_id
        ):
            issues.append({"code": "support_direction", "id": claim["id"]})
        if any(
            evidence_by_id[item].get("direction") not in {"contradicts", "negative_search"}
            for item in negative_ids
            if item in evidence_by_id
        ):
            issues.append({"code": "negative_direction", "id": claim["id"]})
        if claim["claim_type"] in CURRENT_CLAIM_TYPES:
            source_types = {
                evidence_by_id[item]["source_type"]
                for item in support_ids
                if item in evidence_by_id
            }
            if len(source_types) < 2:
                issues.append(
                    {"code": "source_diversity", "id": claim["id"], "required": 2}
                )
            if not claim.get("search_scope"):
                issues.append({"code": "search_scope_missing", "id": claim["id"]})
    summary = {
        "claims": len(claims),
        "evidence_items": len(evidence),
        "source_types": sorted(
            {item.get("source_type") for item in evidence if isinstance(item, dict) and item.get("source_type")}
        ),
        "claims_with_boundaries": sum(1 for item in claims if isinstance(item, dict) and item.get("boundary")),
    }
    return summary, issues


def run(manifest: dict[str, Any], receipt_path: str | Path) -> dict[str, Any]:
    summary, issues = audit(manifest)
    receipt = build_receipt(
        MODULE,
        VERSION,
        "pass" if not issues else "fail",
        manifest,
        summary,
        issues,
    )
    atomic_write_json(receipt_path, receipt)
    return receipt


def _read_json(raw: str) -> dict[str, Any]:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ModuleError("manifest must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--receipt", required=True)
    try:
        args = parser.parse_args(argv)
        result = run(_read_json(args.manifest), args.receipt)
    except (ModuleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
