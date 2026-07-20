#!/usr/bin/env python3
"""Shared hashing and receipt helpers for workflow modules."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = 1


class ModuleError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_json(value: Any, excluded_key: str | None = None) -> str:
    if isinstance(value, dict) and excluded_key:
        payload = dict(value)
        payload.pop(excluded_key, None)
    else:
        payload = value
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.{secrets.token_hex(4)}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, output)


def build_receipt(
    module: str,
    version: int,
    status: str,
    input_value: Any,
    summary: dict[str, Any],
    issues: list[dict[str, Any]],
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    if status not in {"pass", "fail", "skip"}:
        raise ModuleError(f"invalid receipt status: {status}")
    receipt = {
        "receipt_schema": RECEIPT_SCHEMA,
        "module": module,
        "module_version": version,
        "status": status,
        "input_hash": digest_json(input_value),
        "summary": summary,
        "issues": issues,
        "artifacts": artifacts or [],
        "created_at": utc_now(),
    }
    receipt["receipt_hash"] = digest_json(receipt, "receipt_hash")
    return receipt


def verify_receipt(
    path: str | Path,
    expected_module: str | None = None,
    allowed_statuses: set[str] | None = None,
) -> dict[str, Any]:
    receipt_path = Path(path)
    if not receipt_path.is_file():
        raise ModuleError(f"receipt does not exist: {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleError(f"receipt is not valid JSON: {exc}") from exc
    if receipt.get("receipt_schema") != RECEIPT_SCHEMA:
        raise ModuleError("unsupported receipt schema")
    recorded_hash = receipt.get("receipt_hash")
    if not isinstance(recorded_hash, str) or not secrets.compare_digest(
        recorded_hash, digest_json(receipt, "receipt_hash")
    ):
        raise ModuleError("receipt integrity check failed")
    if expected_module and receipt.get("module") != expected_module:
        raise ModuleError(
            f"receipt module mismatch: expected {expected_module}, got {receipt.get('module')}"
        )
    allowed = allowed_statuses or {"pass"}
    if receipt.get("status") not in allowed:
        raise ModuleError(
            f"receipt status is not allowed: {receipt.get('status')}"
        )
    return receipt
