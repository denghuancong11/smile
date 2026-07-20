#!/usr/bin/env python3
"""Versioned, append-only workflow experience store with structured search."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from module_common import ModuleError, digest_json, utc_now


STORE_SCHEMA = 2
REQUIRED_FIELDS = [
    "task_signature",
    "surface_request",
    "underlying_goal",
    "decision",
    "outcome",
    "error_classes",
    "lessons",
    "applicability_boundary",
    "retrieval_keys",
    "evidence_refs",
    "regression_checks",
]
ERROR_KEYS = ["alignment", "assumption", "execution", "data"]


def validate_record_input(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ModuleError("experience record must be a JSON object")
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ModuleError("experience record missing: " + ", ".join(missing))
    if not isinstance(record["decision"], dict):
        raise ModuleError("decision must be an object")
    errors = record["error_classes"]
    if not isinstance(errors, dict) or any(key not in errors for key in ERROR_KEYS):
        raise ModuleError("error_classes must contain alignment, assumption, execution, data")
    for field in ["lessons", "retrieval_keys", "evidence_refs", "regression_checks"]:
        if not isinstance(record[field], list) or not record[field]:
            raise ModuleError(f"{field} must be a non-empty list")


def _record_fingerprint(record: dict[str, Any]) -> str:
    stable = {
        "task_signature": record["task_signature"],
        "underlying_goal": record["underlying_goal"],
        "decision": record["decision"],
        "outcome": record["outcome"],
        "applicability_boundary": record["applicability_boundary"],
        "retrieval_keys": sorted(map(str, record["retrieval_keys"])),
    }
    return digest_json(stable)


def load_records(path: str | Path) -> list[dict[str, Any]]:
    store = Path(path)
    if not store.exists():
        return []
    try:
        lines = store.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ModuleError(f"cannot read memory store: {exc}") from exc
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModuleError(f"memory store has invalid JSON on line {index}: {exc}") from exc
        if record.get("store_schema") != STORE_SCHEMA:
            raise ModuleError(f"unsupported memory schema on line {index}")
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or record_id in seen_ids:
            raise ModuleError(f"invalid or duplicate record_id on line {index}")
        seen_ids.add(record_id)
        recorded_hash = record.get("record_hash")
        if not isinstance(recorded_hash, str) or not secrets.compare_digest(
            recorded_hash, digest_json(record, "record_hash")
        ):
            raise ModuleError(f"memory record integrity failed on line {index}")
        records.append(record)
    return records


def _atomic_write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temp.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def append_record(
    path: str | Path,
    record: dict[str, Any],
    relation: str = "original",
    supersedes: str | None = None,
) -> tuple[dict[str, Any], int]:
    validate_record_input(record)
    if relation not in {"original", "correction", "extension"}:
        raise ModuleError("relation must be original, correction, or extension")
    records = load_records(path)
    ids = {item["record_id"] for item in records}
    if relation != "original" and (not supersedes or supersedes not in ids):
        raise ModuleError("correction or extension must reference an existing record")
    fingerprint = _record_fingerprint(record)
    if any(
        item.get("fingerprint") == fingerprint
        and item.get("status") == "active"
        and item.get("relation") == relation
        for item in records
    ):
        raise ModuleError("duplicate active experience record rejected")
    stored = dict(record)
    stored.update(
        {
            "store_schema": STORE_SCHEMA,
            "record_id": f"awr-{utc_now().replace(':', '').replace('-', '').replace('.', '')}-{secrets.token_hex(4)}",
            "record_version": 1,
            "status": "active",
            "relation": relation,
            "supersedes": supersedes,
            "fingerprint": fingerprint,
            "created_at": utc_now(),
        }
    )
    stored["record_hash"] = digest_json(stored, "record_hash")
    _atomic_write_records(Path(path), [*records, stored])
    verified = load_records(path)
    if not verified or verified[-1]["record_id"] != stored["record_id"]:
        raise ModuleError("memory write verification failed")
    return stored, len(verified)


def effective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {
        item["supersedes"]
        for item in records
        if item.get("relation") in {"correction", "extension"} and item.get("supersedes")
    }
    return [
        item
        for item in records
        if item.get("status") == "active" and item["record_id"] not in superseded
    ]


def search_records(
    records: list[dict[str, Any]],
    queries: list[str],
    task_type: str | None = None,
    error_class: str | None = None,
    environment: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    normalized = [str(item).strip().casefold() for item in queries if str(item).strip()]
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for record in effective_records(records):
        if task_type and str(record.get("task_type", "")).casefold() != task_type.casefold():
            continue
        if environment and environment.casefold() not in str(record.get("environment", "")).casefold():
            continue
        if error_class:
            value = record.get("error_classes", {}).get(error_class)
            if value is None:
                continue
        searchable = " ".join(
            [
                str(record.get("task_signature", "")),
                str(record.get("surface_request", "")),
                str(record.get("underlying_goal", "")),
                str(record.get("task_type", "")),
                str(record.get("environment", "")),
                " ".join(map(str, record.get("retrieval_keys", []))),
                " ".join(map(str, record.get("lessons", []))),
            ]
        ).casefold()
        score = sum(3 if query in map(str.casefold, map(str, record.get("retrieval_keys", []))) else 1 for query in normalized if query in searchable)
        if score:
            scored.append((score, record.get("created_at", ""), record))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record for _, _, record in scored[:limit]]


def verify_store(path: str | Path) -> dict[str, Any]:
    records = load_records(path)
    return {
        "store": str(Path(path).resolve()),
        "records": len(records),
        "effective_records": len(effective_records(records)),
        "schema": STORE_SCHEMA,
        "verified": True,
    }


def _read_json_arg(raw: str) -> Any:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("append")
    cmd.add_argument("--store", required=True)
    cmd.add_argument("--record", required=True)
    cmd.add_argument("--relation", default="original")
    cmd.add_argument("--supersedes")
    cmd = sub.add_parser("search")
    cmd.add_argument("--store", required=True)
    cmd.add_argument("--queries", required=True)
    cmd.add_argument("--task-type")
    cmd.add_argument("--error-class")
    cmd.add_argument("--environment")
    cmd.add_argument("--limit", type=int, default=10)
    cmd = sub.add_parser("verify")
    cmd.add_argument("--store", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "append":
            stored, count = append_record(
                args.store,
                _read_json_arg(args.record),
                args.relation,
                args.supersedes,
            )
            result: Any = {"record_id": stored["record_id"], "records": count}
        elif args.command == "search":
            result = search_records(
                load_records(args.store),
                _read_json_arg(args.queries),
                args.task_type,
                args.error_class,
                args.environment,
                args.limit,
            )
        else:
            result = verify_store(args.store)
    except (ModuleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
