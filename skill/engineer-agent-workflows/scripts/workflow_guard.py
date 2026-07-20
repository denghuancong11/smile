#!/usr/bin/env python3
"""Fail-closed ten-stage guard with persistent recall/deposit/loop memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_store import (
    append_record as append_memory_record,
    load_records as load_memory_records,
    search_records as search_memory_records,
)
from module_common import ModuleError, verify_receipt


SCHEMA_VERSION = 3

STAGES: dict[int, dict[str, Any]] = {
    1: {
        "name": "对齐",
        "required": [
            "surface_request",
            "underlying_goal",
            "constraints",
            "acceptance_criteria",
            "environment",
            "authorization_boundary",
            "alignment_confirmation",
            "context_receipt",
        ],
        "system_fields": ["context_receipt"],
        "types": {
            "constraints": "list",
            "acceptance_criteria": "list",
            "environment": "dict",
            "authorization_boundary": "dict",
        },
        "min_items": {"constraints": 1, "acceptance_criteria": 1},
        "required_keys": {
            "environment": ["runtime", "task_context"],
            "authorization_boundary": ["allowed", "requires_confirmation", "forbidden"],
        },
        "enums": {"alignment_confirmation": ["user_explicit"]},
        "reject_unresolved": [
            "underlying_goal",
            "constraints",
            "acceptance_criteria",
            "environment",
            "authorization_boundary",
        ],
        "solution_neutral": ["underlying_goal", "acceptance_criteria"],
    },
    2: {
        "name": "回忆",
        "required": [
            "recall_executed",
            "recall_queries",
            "recall_sources",
            "similar_failures",
            "prior_decisions",
            "recall_result",
            "recall_evidence",
            "applicability_assessment",
        ],
        "system_fields": [
            "recall_executed",
            "recall_queries",
            "recall_sources",
            "similar_failures",
            "prior_decisions",
            "recall_result",
            "recall_evidence",
        ],
        "booleans_true": ["recall_executed"],
        "enums": {"recall_result": ["matched", "no_match"]},
        "types": {
            "recall_queries": "list",
            "recall_sources": "list",
            "similar_failures": "list",
            "prior_decisions": "list",
            "recall_evidence": "dict",
        },
        "min_items": {"recall_queries": 1, "recall_sources": 1},
        "allow_empty": ["similar_failures", "prior_decisions"],
    },
    3: {
        "name": "探索",
        "required": [
            "discovery_operators",
            "operator_outputs",
            "overlooked_problem_candidates",
            "candidate_evidence_status",
        ],
        "types": {
            "discovery_operators": "list",
            "operator_outputs": "dict",
            "overlooked_problem_candidates": "list",
            "candidate_evidence_status": "dict",
        },
        "min_items": {
            "discovery_operators": 3,
            "overlooked_problem_candidates": 3,
        },
    },
    4: {
        "name": "质疑",
        "required": [
            "counterexamples",
            "conflicts",
            "negative_evidence",
            "disconfirmed_candidates",
            "surviving_candidates",
            "remaining_uncertainty",
            "evidence_receipt",
        ],
        "system_fields": ["evidence_receipt"],
        "types": {
            "counterexamples": "list",
            "conflicts": "list",
            "negative_evidence": "list",
            "disconfirmed_candidates": "list",
            "surviving_candidates": "list",
        },
        "min_items": {
            "counterexamples": 1,
            "conflicts": 1,
            "negative_evidence": 1,
            "surviving_candidates": 1,
        },
        "allow_empty": ["disconfirmed_candidates"],
    },
    5: {
        "name": "决策",
        "required": [
            "selected_target",
            "selected_solution",
            "risk_boundary",
            "rejected_options",
            "decision_reason",
            "decision_source",
            "decision_status",
        ],
        "types": {"rejected_options": "list"},
        "min_items": {"rejected_options": 1},
        "enums": {
            "decision_source": ["user_explicit"],
            "decision_status": ["proceed"],
        },
    },
    6: {
        "name": "验证",
        "required": [
            "core_hypothesis",
            "minimal_experiment_or_mvp",
            "control",
            "criteria_locked",
            "success_criterion",
            "failure_criterion",
            "stop_condition",
            "observed_result",
            "evidence_refs",
        ],
        "booleans_true": ["criteria_locked"],
        "types": {"evidence_refs": "list"},
        "min_items": {"evidence_refs": 1},
    },
    7: {
        "name": "复盘",
        "required": [
            "error_classification",
            "causal_explanation",
            "lessons",
            "next_action",
            "story_receipt",
        ],
        "system_fields": ["story_receipt"],
        "types": {"error_classification": "dict", "lessons": "list"},
        "min_items": {"lessons": 1},
        "required_keys": {
            "error_classification": ["alignment", "assumption", "execution", "data"]
        },
    },
    8: {
        "name": "沉淀",
        "required": [
            "experience_record_id",
            "experience_record",
            "decision_record",
            "applicability_boundary",
            "retrieval_keys",
            "storage_location",
            "write_verification",
        ],
        "system_fields": [
            "experience_record_id",
            "experience_record",
            "decision_record",
            "applicability_boundary",
            "retrieval_keys",
            "storage_location",
            "write_verification",
        ],
        "types": {
            "experience_record": "dict",
            "decision_record": "dict",
            "retrieval_keys": "list",
            "write_verification": "dict",
        },
        "min_items": {"retrieval_keys": 1},
    },
    9: {
        "name": "回归",
        "required": [
            "key_error",
            "automated_checks",
            "failure_fixture",
            "check_locations",
            "check_passed",
            "check_evidence",
            "coverage_boundary",
            "evaluation_receipt",
        ],
        "system_fields": ["evaluation_receipt"],
        "types": {
            "automated_checks": "list",
            "check_locations": "list",
            "check_evidence": "list",
        },
        "min_items": {
            "automated_checks": 1,
            "check_locations": 1,
            "check_evidence": 1,
        },
        "booleans_true": ["check_passed"],
    },
    10: {
        "name": "循环",
        "required": [
            "next_task_query",
            "retrieved_record_ids",
            "retrieval_result",
            "retrieval_first_verified",
            "influence_on_next_alignment",
            "loop_entry_rule",
            "final_status",
        ],
        "system_fields": [
            "next_task_query",
            "retrieved_record_ids",
            "retrieval_result",
            "retrieval_first_verified",
        ],
        "types": {"next_task_query": "list", "retrieved_record_ids": "list"},
        "min_items": {"next_task_query": 1, "retrieved_record_ids": 1},
        "booleans_true": ["retrieval_first_verified"],
        "enums": {
            "retrieval_result": ["matched"],
            "final_status": ["validated", "partially_validated", "rejected"],
        },
    },
}

PLACEHOLDERS = {
    "",
    "?",
    "todo",
    "tbd",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "unsure",
    "later",
    "待定",
    "待补充",
    "不知道",
    "未知",
    "暂无",
    "无信息",
    "以后再说",
}

UNRESOLVED_MARKERS = {
    "尚未提供",
    "未提供",
    "待确认",
    "待验证",
    "没有提供",
    "not provided",
    "unspecified",
    "to be confirmed",
    "to be verified",
}

SOLUTION_MARKERS = {
    "安装插件",
    "插件",
    "plugin",
    "状态文件",
    "state file",
    "持久记录",
    "persistent record",
    "自动检查",
    "automated check",
    "机器检查",
    "提示词",
    "prompt",
    "脚本",
    "script",
    "重构架构",
    "rewrite architecture",
}

TYPE_MAP = {"list": list, "dict": dict, "str": str, "bool": bool}


class GuardError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: dict[str, Any], excluded: str) -> str:
    payload = dict(value)
    payload.pop(excluded, None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["integrity"] = _digest(data, "integrity")
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _assert_state_shape(state: dict[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise GuardError(
            f"unsupported state schema; start a new workflow with schema {SCHEMA_VERSION}"
        )
    stage = state.get("current_stage")
    if not isinstance(stage, int) or stage not in STAGES:
        raise GuardError("current_stage is invalid")
    if state.get("status") not in {"active", "complete"}:
        raise GuardError("status is invalid")
    if not isinstance(state.get("stage_data"), dict):
        raise GuardError("stage_data is invalid")
    if not isinstance(state.get("history"), list):
        raise GuardError("history is invalid")
    if not isinstance(state.get("memory_store"), str):
        raise GuardError("memory_store is invalid")


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.is_file():
        raise GuardError(f"state file does not exist: {state_path}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError(f"cannot read valid state JSON: {exc}") from exc
    _assert_state_shape(state)
    recorded = state.get("integrity")
    if not isinstance(recorded, str) or not secrets.compare_digest(
        recorded, _digest(state, "integrity")
    ):
        raise GuardError("state integrity check failed; do not continue from edited state")
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    _assert_state_shape(state)
    state["updated_at"] = utc_now()
    _atomic_write_json(Path(path), state)


def init_state(
    path: str | Path,
    objective: str,
    mode: str = "strict",
    memory_store: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(objective, str) or objective.strip().casefold() in PLACEHOLDERS:
        raise GuardError("objective must be concrete")
    state_path = Path(path)
    if state_path.exists():
        raise GuardError("state file already exists; use status or choose another path")
    if memory_store is None:
        raise GuardError("memory_store is required; choose a stable path outside the target repository")
    store_path = Path(memory_store)
    now = utc_now()
    state = {
        "schema_version": SCHEMA_VERSION,
        "skill": "engineer-agent-workflows",
        "mode": mode,
        "objective": objective.strip(),
        "status": "active",
        "current_stage": 1,
        "stage_data": {str(i): {} for i in STAGES},
        "memory_store": str(store_path.resolve()),
        "active_turn": None,
        "history": [
            {"at": now, "event": "initialized", "stage": 1, "objective": objective.strip()}
        ],
        "created_at": now,
        "updated_at": now,
    }
    save_state(state_path, state)
    return state


def open_turn(path: str | Path) -> str:
    state = load_state(path)
    if state["status"] == "complete":
        raise GuardError("workflow is already complete")
    if state["active_turn"] is not None:
        raise GuardError("a turn is already open; close or recover it before continuing")
    token = secrets.token_urlsafe(18)
    state["active_turn"] = {
        "token": token,
        "opened_at": utc_now(),
        "stage_at_open": state["current_stage"],
        "advanced": False,
    }
    state["history"].append(
        {"at": utc_now(), "event": "turn_opened", "stage": state["current_stage"]}
    )
    save_state(path, state)
    return token


def _require_turn(state: dict[str, Any], token: str) -> dict[str, Any]:
    turn = state.get("active_turn")
    if not isinstance(turn, dict) or not secrets.compare_digest(
        str(turn.get("token", "")), token
    ):
        raise GuardError("missing or invalid turn token")
    return turn


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()


def _is_placeholder(value: Any, allow_empty: bool = False) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in PLACEHOLDERS
    if isinstance(value, (list, dict)):
        return len(value) == 0 and not allow_empty
    return False


def _contains_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        return any(marker in normalized for marker in UNRESOLVED_MARKERS)
    if isinstance(value, list):
        return any(_contains_unresolved(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_unresolved(item) for item in value.values())
    return False


def _contains_solution_marker(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        return any(marker in normalized for marker in SOLUTION_MARKERS)
    if isinstance(value, list):
        return any(_contains_solution_marker(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_solution_marker(item) for item in value.values())
    return False


def put_value(
    path: str | Path, token: str, stage: int, field: str, raw_value: str
) -> None:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("this turn already advanced; future-stage work is forbidden")
    if stage != state["current_stage"]:
        raise GuardError(
            f"write rejected: current stage is {state['current_stage']}, requested stage is {stage}"
        )
    spec = STAGES[stage]
    if field not in set(spec["required"]):
        raise GuardError(f"field is not allowed in stage {stage}: {field}")
    if field in set(spec.get("system_fields", [])):
        raise GuardError(f"field must be produced by a guarded command: {field}")
    value = _parse_value(raw_value)
    if _is_placeholder(value, field in set(spec.get("allow_empty", []))):
        raise GuardError(f"placeholder or empty evidence rejected for field: {field}")
    if field in set(spec.get("reject_unresolved", [])) and _contains_unresolved(value):
        raise GuardError(f"unresolved information rejected for field: {field}")
    if field in set(spec.get("solution_neutral", [])) and _contains_solution_marker(value):
        raise GuardError(f"solution language rejected from alignment field: {field}")
    state["stage_data"][str(stage)][field] = value
    state["history"].append(
        {"at": utc_now(), "event": "field_recorded", "stage": stage, "field": field}
    )
    save_state(path, state)


def validate_stage_data(stage: int, data: dict[str, Any]) -> list[str]:
    spec = STAGES[stage]
    errors: list[str] = []
    allow_empty = set(spec.get("allow_empty", []))
    for field in spec["required"]:
        if field not in data:
            errors.append(f"missing:{field}")
        elif _is_placeholder(data[field], field in allow_empty):
            errors.append(f"placeholder:{field}")
        elif field in set(spec.get("reject_unresolved", [])) and _contains_unresolved(data[field]):
            errors.append(f"unresolved:{field}")
        elif field in set(spec.get("solution_neutral", [])) and _contains_solution_marker(data[field]):
            errors.append(f"solution_language:{field}")
    for field, type_name in spec.get("types", {}).items():
        if field in data and not isinstance(data[field], TYPE_MAP[type_name]):
            errors.append(f"invalid_type:{field} (expected: {type_name})")
    for field, count in spec.get("min_items", {}).items():
        if field in data and isinstance(data[field], (list, dict)) and len(data[field]) < count:
            errors.append(f"min_items:{field} (required: {count})")
    for field, keys in spec.get("required_keys", {}).items():
        if field in data and isinstance(data[field], dict):
            missing = [key for key in keys if key not in data[field]]
            if missing:
                errors.append(f"missing_keys:{field} ({', '.join(missing)})")
    for field, choices in spec.get("enums", {}).items():
        if field in data and data[field] not in choices:
            errors.append(f"invalid_enum:{field} (allowed: {', '.join(choices)})")
    for field in spec.get("booleans_true", []):
        if field in data and data[field] is not True:
            errors.append(f"must_be_true:{field}")
    return errors


def _load_memory(path: Path) -> list[dict[str, Any]]:
    try:
        return load_memory_records(path)
    except ModuleError as exc:
        raise GuardError(str(exc)) from exc


def _search_records(records: list[dict[str, Any]], queries: list[str]) -> list[dict[str, Any]]:
    return search_memory_records(records, queries)


def memory_search(
    path: str | Path,
    token: str,
    queries: list[str],
    task_type: str | None = None,
    error_class: str | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("this turn already advanced")
    stage = state["current_stage"]
    if stage not in {2, 10}:
        raise GuardError("memory-search is only allowed in stage 2 or stage 10")
    if not isinstance(queries, list) or not queries or any(not str(q).strip() for q in queries):
        raise GuardError("queries must be a non-empty JSON array")
    store = Path(state["memory_store"])
    records = _load_memory(store)
    matches = search_memory_records(
        records,
        queries,
        task_type=task_type,
        error_class=error_class,
        environment=environment,
    )
    data = state["stage_data"][str(stage)]
    if stage == 2:
        data.update(
            {
                "recall_executed": True,
                "recall_queries": queries,
                "recall_sources": [str(store)],
                "similar_failures": [
                    {
                        "record_id": item["record_id"],
                        "outcome": item["outcome"],
                        "error_classes": item["error_classes"],
                    }
                    for item in matches
                ],
                "prior_decisions": [
                    {"record_id": item["record_id"], "decision": item["decision"]}
                    for item in matches
                ],
                "recall_result": "matched" if matches else "no_match",
                "recall_evidence": {
                    "store": str(store),
                    "records_scanned": len(records),
                    "matched_ids": [item["record_id"] for item in matches],
                    "filters": {
                        "task_type": task_type,
                        "error_class": error_class,
                        "environment": environment,
                    },
                },
            }
        )
    else:
        data.update(
            {
                "next_task_query": queries,
                "retrieved_record_ids": [item["record_id"] for item in matches],
                "retrieval_result": "matched" if matches else "no_match",
                "retrieval_first_verified": True,
            }
        )
    state["history"].append(
        {
            "at": utc_now(),
            "event": "memory_searched",
            "stage": stage,
            "queries": queries,
            "filters": {
                "task_type": task_type,
                "error_class": error_class,
                "environment": environment,
            },
            "matched_ids": [item["record_id"] for item in matches],
        }
    )
    save_state(path, state)
    return {"records_scanned": len(records), "matches": matches}


def deposit_experience(path: str | Path, token: str, record: dict[str, Any]) -> str:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("this turn already advanced")
    if state["current_stage"] != 8:
        raise GuardError("deposit is only allowed in stage 8")
    store = Path(state["memory_store"])
    try:
        stored, record_count = append_memory_record(store, record)
    except ModuleError as exc:
        raise GuardError(str(exc)) from exc
    state["stage_data"]["8"].update(
        {
            "experience_record_id": stored["record_id"],
            "experience_record": {
                "task_signature": stored["task_signature"],
                "outcome": stored["outcome"],
                "error_classes": stored["error_classes"],
                "lessons": stored["lessons"],
            },
            "decision_record": stored["decision"],
            "applicability_boundary": stored["applicability_boundary"],
            "retrieval_keys": stored["retrieval_keys"],
            "storage_location": str(store),
            "write_verification": {
                "record_hash": stored["record_hash"],
                "records_after_write": record_count,
                "store_schema": stored["store_schema"],
            },
        }
    )
    state["history"].append(
        {"at": utc_now(), "event": "experience_deposited", "record_id": stored["record_id"]}
    )
    save_state(path, state)
    return stored["record_id"]


RECEIPT_BINDINGS = {
    "context": {"stage": 1, "module": "project-context", "field": "context_receipt", "statuses": {"pass", "skip"}},
    "evidence": {"stage": 4, "module": "evidence-protocol", "field": "evidence_receipt", "statuses": {"pass"}},
    "story": {"stage": 7, "module": "story-audit", "field": "story_receipt", "statuses": {"pass"}},
    "evaluation": {"stage": 9, "module": "evaluation-harness", "field": "evaluation_receipt", "statuses": {"pass"}},
}


def attach_receipt(path: str | Path, token: str, kind: str, receipt_path: str | Path) -> dict[str, Any]:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("this turn already advanced")
    binding = RECEIPT_BINDINGS.get(kind)
    if binding is None:
        raise GuardError(f"unknown receipt kind: {kind}")
    if state["current_stage"] != binding["stage"]:
        raise GuardError(
            f"{kind} receipt is only allowed in stage {binding['stage']}"
        )
    try:
        receipt = verify_receipt(
            receipt_path,
            expected_module=binding["module"],
            allowed_statuses=binding["statuses"],
        )
    except ModuleError as exc:
        raise GuardError(str(exc)) from exc
    state["stage_data"][str(binding["stage"])][binding["field"]] = {
        "path": str(Path(receipt_path).resolve()),
        "module": receipt["module"],
        "module_version": receipt["module_version"],
        "status": receipt["status"],
        "input_hash": receipt["input_hash"],
        "receipt_hash": receipt["receipt_hash"],
        "summary": receipt["summary"],
    }
    state["history"].append(
        {
            "at": utc_now(),
            "event": "module_receipt_attached",
            "stage": binding["stage"],
            "kind": kind,
            "receipt_hash": receipt["receipt_hash"],
        }
    )
    save_state(path, state)
    return receipt


def check_current(path: str | Path, token: str | None = None) -> dict[str, Any]:
    state = load_state(path)
    if token is not None:
        _require_turn(state, token)
    stage = state["current_stage"]
    errors = validate_stage_data(stage, state["stage_data"][str(stage)])
    return {
        "stage": stage,
        "name": STAGES[stage]["name"],
        "passed": not errors,
        "errors": errors,
    }


def advance(path: str | Path, token: str) -> dict[str, Any]:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("only one stage transition is allowed per turn")
    stage = state["current_stage"]
    errors = validate_stage_data(stage, state["stage_data"][str(stage)])
    if errors:
        raise GuardError("stage gate failed: " + "; ".join(errors))
    turn["advanced"] = True
    if stage == max(STAGES):
        state["status"] = "complete"
        event = "workflow_completed"
    else:
        state["current_stage"] = stage + 1
        event = "stage_advanced"
    state["history"].append(
        {
            "at": utc_now(),
            "event": event,
            "from_stage": stage,
            "to_stage": state["current_stage"],
        }
    )
    save_state(path, state)
    return {"status": state["status"], "current_stage": state["current_stage"]}


def close_turn(path: str | Path, token: str) -> None:
    state = load_state(path)
    turn = _require_turn(state, token)
    state["history"].append(
        {
            "at": utc_now(),
            "event": "turn_closed",
            "stage": state["current_stage"],
            "advanced": bool(turn["advanced"]),
        }
    )
    state["active_turn"] = None
    save_state(path, state)


def rollback(path: str | Path, token: str, to_stage: int) -> None:
    state = load_state(path)
    turn = _require_turn(state, token)
    if turn["advanced"]:
        raise GuardError("this turn already transitioned")
    if to_stage not in STAGES or to_stage > state["current_stage"]:
        raise GuardError("rollback target must be an existing current or earlier stage")
    for stage in range(to_stage + 1, max(STAGES) + 1):
        state["stage_data"][str(stage)] = {}
    state["current_stage"] = to_stage
    state["status"] = "active"
    turn["advanced"] = True
    state["history"].append(
        {"at": utc_now(), "event": "rolled_back", "to_stage": to_stage}
    )
    save_state(path, state)


def status_summary(path: str | Path) -> dict[str, Any]:
    state = load_state(path)
    stage = state["current_stage"]
    check = check_current(path)
    return {
        "objective": state["objective"],
        "status": state["status"],
        "current_stage": stage,
        "stage_name": STAGES[stage]["name"],
        "gate_passed": check["passed"],
        "gate_errors": check["errors"],
        "memory_store": state["memory_store"],
        "turn_open": state["active_turn"] is not None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cmd = sub.add_parser("init")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--objective", required=True)
    cmd.add_argument("--mode", default="strict")
    cmd.add_argument("--memory")

    cmd = sub.add_parser("status")
    cmd.add_argument("--state", required=True)

    cmd = sub.add_parser("open-turn")
    cmd.add_argument("--state", required=True)

    cmd = sub.add_parser("put")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)
    cmd.add_argument("--stage", type=int, required=True)
    cmd.add_argument("--field", required=True)
    cmd.add_argument("--value", required=True)

    cmd = sub.add_parser("memory-search")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)
    cmd.add_argument("--queries", required=True, help="JSON array of retrieval keys")
    cmd.add_argument("--task-type")
    cmd.add_argument("--error-class")
    cmd.add_argument("--environment")

    cmd = sub.add_parser("deposit")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)
    cmd.add_argument("--record", required=True, help="JSON object or @path-to-json")

    cmd = sub.add_parser("attach-receipt")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)
    cmd.add_argument("--kind", choices=sorted(RECEIPT_BINDINGS), required=True)
    cmd.add_argument("--receipt", required=True)

    cmd = sub.add_parser("check")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token")

    cmd = sub.add_parser("advance")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)

    cmd = sub.add_parser("close-turn")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)

    cmd = sub.add_parser("rollback")
    cmd.add_argument("--state", required=True)
    cmd.add_argument("--token", required=True)
    cmd.add_argument("--to", type=int, required=True)
    return parser


def _parse_record_argument(raw: str) -> dict[str, Any]:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GuardError(f"record is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError("record must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_state(args.state, args.objective, args.mode, args.memory)
            output: Any = status_summary(args.state) | {"created_at": result["created_at"]}
        elif args.command == "status":
            output = status_summary(args.state)
        elif args.command == "open-turn":
            output = {"token": open_turn(args.state)}
        elif args.command == "put":
            put_value(args.state, args.token, args.stage, args.field, args.value)
            output = check_current(args.state, args.token)
        elif args.command == "memory-search":
            queries = json.loads(args.queries)
            output = memory_search(
                args.state,
                args.token,
                queries,
                args.task_type,
                args.error_class,
                args.environment,
            )
        elif args.command == "deposit":
            output = {"record_id": deposit_experience(
                args.state, args.token, _parse_record_argument(args.record)
            )}
        elif args.command == "attach-receipt":
            output = attach_receipt(args.state, args.token, args.kind, args.receipt)
        elif args.command == "check":
            output = check_current(args.state, args.token)
        elif args.command == "advance":
            output = advance(args.state, args.token)
        elif args.command == "close-turn":
            close_turn(args.state, args.token)
            output = status_summary(args.state)
        elif args.command == "rollback":
            rollback(args.state, args.token, args.to)
            output = status_summary(args.state)
        else:  # pragma: no cover
            raise GuardError("unknown command")
    except (GuardError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
