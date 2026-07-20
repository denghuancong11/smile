#!/usr/bin/env python3
"""Compare baseline and candidate Agent workflow results against user-defined gates."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from module_common import ModuleError, atomic_write_json, build_receipt


MODULE = "evaluation-harness"
VERSION = 1
REQUIRED_CATEGORIES = {"normal", "known_failure", "holdout", "perturbation"}
METRICS = [
    "success",
    "constraint_violations",
    "first_pass",
    "repair_rounds",
    "duplicate_work",
    "context_hit",
    "context_noise",
    "recovery_success",
    "tokens",
    "duration_seconds",
]


def _validate_suite(suite: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tasks = suite.get("tasks")
    thresholds = suite.get("thresholds")
    if not isinstance(tasks, list) or not tasks:
        raise ModuleError("suite.tasks must be non-empty")
    if not isinstance(thresholds, dict):
        raise ModuleError("suite.thresholds must be an object")
    ids: set[str] = set()
    categories: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or not task.get("id") or not task.get("category"):
            raise ModuleError("each task requires id and category")
        if task["id"] in ids:
            raise ModuleError(f"duplicate task id: {task['id']}")
        ids.add(task["id"])
        categories.add(task["category"])
    missing_categories = REQUIRED_CATEGORIES - categories
    if missing_categories:
        raise ModuleError("suite missing categories: " + ", ".join(sorted(missing_categories)))
    required_thresholds = [
        "min_success_rate",
        "max_constraint_violations",
        "min_recovery_rate",
        "max_task_regressions",
        "max_token_increase_ratio",
    ]
    missing = [item for item in required_thresholds if item not in thresholds]
    if missing:
        raise ModuleError("thresholds missing: " + ", ".join(missing))
    return tasks, thresholds


def _validate_results(name: str, tasks: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = result.get("tasks")
    if not isinstance(entries, dict):
        raise ModuleError(f"{name}.tasks must be an object keyed by task id")
    expected = {item["id"] for item in tasks}
    if set(entries) != expected:
        raise ModuleError(f"{name} task ids do not match suite")
    for task_id, values in entries.items():
        if not isinstance(values, dict):
            raise ModuleError(f"{name}.{task_id} must be an object")
        missing = [metric for metric in METRICS if metric not in values]
        if missing:
            raise ModuleError(f"{name}.{task_id} missing metrics: {', '.join(missing)}")
        for metric in ["success", "first_pass", "context_hit", "recovery_success"]:
            if not isinstance(values[metric], bool):
                raise ModuleError(f"{name}.{task_id}.{metric} must be boolean")
        for metric in set(METRICS) - {"success", "first_pass", "context_hit", "recovery_success"}:
            if not isinstance(values[metric], (int, float)) or values[metric] < 0:
                raise ModuleError(f"{name}.{task_id}.{metric} must be non-negative number")
    return entries


def _aggregate(entries: dict[str, dict[str, Any]]) -> dict[str, float]:
    values = list(entries.values())
    count = len(values)
    return {
        "success_rate": sum(item["success"] for item in values) / count,
        "constraint_violations": sum(item["constraint_violations"] for item in values),
        "first_pass_rate": sum(item["first_pass"] for item in values) / count,
        "repair_rounds_mean": statistics.fmean(item["repair_rounds"] for item in values),
        "duplicate_work_total": sum(item["duplicate_work"] for item in values),
        "context_hit_rate": sum(item["context_hit"] for item in values) / count,
        "context_noise_mean": statistics.fmean(item["context_noise"] for item in values),
        "recovery_rate": sum(item["recovery_success"] for item in values) / count,
        "tokens_total": sum(item["tokens"] for item in values),
        "duration_seconds_total": sum(item["duration_seconds"] for item in values),
    }


def compare(
    suite: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks, thresholds = _validate_suite(suite)
    base_entries = _validate_results("baseline", tasks, baseline)
    candidate_entries = _validate_results("candidate", tasks, candidate)
    base = _aggregate(base_entries)
    current = _aggregate(candidate_entries)
    regressions = [
        task["id"]
        for task in tasks
        if base_entries[task["id"]]["success"] and not candidate_entries[task["id"]]["success"]
    ]
    token_ratio = (
        current["tokens_total"] / base["tokens_total"]
        if base["tokens_total"]
        else (1.0 if current["tokens_total"] == 0 else None)
    )
    issues: list[dict[str, Any]] = []
    checks = [
        (current["success_rate"] >= thresholds["min_success_rate"], "success_rate"),
        (
            current["constraint_violations"] <= thresholds["max_constraint_violations"],
            "constraint_violations",
        ),
        (current["recovery_rate"] >= thresholds["min_recovery_rate"], "recovery_rate"),
        (len(regressions) <= thresholds["max_task_regressions"], "task_regressions"),
        (
            token_ratio is not None
            and token_ratio <= thresholds["max_token_increase_ratio"],
            "token_increase_ratio",
        ),
    ]
    for passed, metric in checks:
        if not passed:
            issues.append({"code": "threshold_failed", "metric": metric})
    summary = {
        "baseline": base,
        "candidate": current,
        "task_regressions": regressions,
        "token_increase_ratio": token_ratio,
        "thresholds": thresholds,
    }
    return summary, issues


def run(
    suite: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    receipt_path: str | Path,
) -> dict[str, Any]:
    summary, issues = compare(suite, baseline, candidate)
    receipt = build_receipt(
        MODULE,
        VERSION,
        "pass" if not issues else "fail",
        {"suite": suite, "baseline": baseline, "candidate": candidate},
        summary,
        issues,
    )
    atomic_write_json(receipt_path, receipt)
    return receipt


def _read_json(raw: str) -> dict[str, Any]:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ModuleError("input must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--receipt", required=True)
    try:
        args = parser.parse_args(argv)
        result = run(
            _read_json(args.suite),
            _read_json(args.baseline),
            _read_json(args.candidate),
            args.receipt,
        )
    except (ModuleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
