#!/usr/bin/env python3
"""Adversarial audit for problem-mechanism-evidence-boundary story closure."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from module_common import ModuleError, atomic_write_json, build_receipt


MODULE = "story-audit"
VERSION = 1
INFLATION_PATTERNS = [
    r"\bguarantee(?:d|s)?\b",
    r"\bnever\b",
    r"\bbest\b",
    r"\bfirst\b",
    r"\bparadigm\b",
    r"保证永不",
    r"绝对",
    r"首次",
    r"最佳",
    r"范式",
]


def audit(story: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    for field in ["problem", "counterintuitive_entry", "mechanism", "solution_boundary"]:
        if not story.get(field):
            issues.append({"code": "story_field_missing", "field": field})
    importance = story.get("importance_evidence")
    if not isinstance(importance, list) or not importance:
        issues.append({"code": "importance_evidence_missing"})
    claims = story.get("claims")
    if not isinstance(claims, list) or not claims:
        issues.append({"code": "claims_missing"})
        claims = []
    claim_ids: set[str] = set()
    inflated: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            issues.append({"code": "claim_type"})
            continue
        missing = [
            field
            for field in ["id", "text", "method", "evidence", "negative_evidence", "boundary"]
            if not claim.get(field)
        ]
        if missing:
            issues.append({"code": "claim_fields", "id": claim.get("id"), "missing": missing})
            continue
        if claim["id"] in claim_ids:
            issues.append({"code": "duplicate_claim_id", "id": claim["id"]})
        claim_ids.add(claim["id"])
        if not isinstance(claim["evidence"], list) or not claim["evidence"]:
            issues.append({"code": "claim_evidence_missing", "id": claim["id"]})
        if not isinstance(claim["negative_evidence"], list) or not claim["negative_evidence"]:
            issues.append({"code": "claim_negative_missing", "id": claim["id"]})
        if any(re.search(pattern, claim["text"], flags=re.IGNORECASE) for pattern in INFLATION_PATTERNS):
            inflated.append(claim["id"])
            if not claim.get("inflation_evidence"):
                issues.append({"code": "unsupported_inflation", "id": claim["id"]})
    mapping = story.get("problem_claim_mapping")
    if not isinstance(mapping, list) or not mapping:
        issues.append({"code": "problem_claim_mapping_missing"})
    else:
        unknown = [item for item in mapping if item not in claim_ids]
        if unknown:
            issues.append({"code": "mapping_unknown_claims", "ids": unknown})
    summary = {
        "claims": len(claims),
        "mapped_claims": len(mapping) if isinstance(mapping, list) else 0,
        "inflated_claims": inflated,
        "closure_complete": not issues,
    }
    return summary, issues


def run(story: dict[str, Any], receipt_path: str | Path) -> dict[str, Any]:
    summary, issues = audit(story)
    receipt = build_receipt(
        MODULE,
        VERSION,
        "pass" if not issues else "fail",
        story,
        summary,
        issues,
    )
    atomic_write_json(receipt_path, receipt)
    return receipt


def _read_json(raw: str) -> dict[str, Any]:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ModuleError("story must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", required=True)
    parser.add_argument("--receipt", required=True)
    try:
        args = parser.parse_args(argv)
        result = run(_read_json(args.story), args.receipt)
    except (ModuleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
