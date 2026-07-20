#!/usr/bin/env python3
"""Build a minimal, read-only project context manifest and signed receipt."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from module_common import ModuleError, atomic_write_json, build_receipt, digest_json


MODULE = "project-context"
VERSION = 1
EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "coverage", "__pycache__"}
CONFIG_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "tsconfig.json",
    "pytest.ini",
}
DOC_NAMES = {"readme.md", "agents.md", "contributing.md", "architecture.md"}
TEST_PARTS = {"test", "tests", "spec", "specs", "__tests__"}


def _iter_files(root: Path, max_files: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for current, dirs, names in os.walk(root):
        dirs[:] = [item for item in dirs if item.casefold() not in EXCLUDED_DIRS]
        for name in names:
            files.append(Path(current) / name)
            if len(files) >= max_files:
                truncated = True
                return files, truncated
    return files, truncated


def build_manifest(root_value: str | Path, max_files: int = 20000) -> dict[str, Any]:
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise ModuleError(f"project root is not a directory: {root}")
    if max_files < 1:
        raise ModuleError("max_files must be positive")
    files, truncated = _iter_files(root, max_files)
    relative = [item.relative_to(root).as_posix() for item in files]
    extensions = Counter((item.suffix.casefold() or "[no-extension]") for item in files)
    configs = [item for item in relative if Path(item).name.casefold() in CONFIG_NAMES]
    docs = [item for item in relative if Path(item).name.casefold() in DOC_NAMES or "adr" in {part.casefold() for part in Path(item).parts}]
    tests = [item for item in relative if TEST_PARTS & {part.casefold() for part in Path(item).parts}]
    top_level = sorted({Path(item).parts[0] for item in relative if Path(item).parts})
    manifest = {
        "schema": 1,
        "root": str(root),
        "file_count": len(files),
        "truncated": truncated,
        "top_level": top_level[:200],
        "extensions": dict(extensions.most_common(50)),
        "config_files": configs[:200],
        "documentation_files": docs[:200],
        "test_files": tests[:500],
        "sample_files": relative[:500],
    }
    manifest["manifest_hash"] = digest_json(manifest, "manifest_hash")
    return manifest


def run_build(
    root: str | Path,
    manifest_path: str | Path,
    receipt_path: str | Path,
    max_files: int,
) -> dict[str, Any]:
    manifest = build_manifest(root, max_files)
    atomic_write_json(manifest_path, manifest)
    issues: list[dict[str, Any]] = []
    if manifest["truncated"]:
        issues.append({"code": "scan_truncated", "message": "increase max_files or narrow root"})
    if not manifest["config_files"]:
        issues.append({"code": "no_config", "message": "no recognized project config found"})
    receipt = build_receipt(
        MODULE,
        VERSION,
        "pass" if not issues else "fail",
        {"root": manifest["root"], "max_files": max_files},
        {
            "file_count": manifest["file_count"],
            "config_files": len(manifest["config_files"]),
            "documentation_files": len(manifest["documentation_files"]),
            "test_files": len(manifest["test_files"]),
            "manifest_hash": manifest["manifest_hash"],
        },
        issues,
        [str(Path(manifest_path).resolve())],
    )
    atomic_write_json(receipt_path, receipt)
    return receipt


def run_skip(reason: str, receipt_path: str | Path) -> dict[str, Any]:
    if not reason.strip():
        raise ModuleError("skip reason is required")
    receipt = build_receipt(
        MODULE,
        VERSION,
        "skip",
        {"reason": reason},
        {"reason": reason},
        [],
    )
    atomic_write_json(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build")
    cmd.add_argument("--root", required=True)
    cmd.add_argument("--manifest", required=True)
    cmd.add_argument("--receipt", required=True)
    cmd.add_argument("--max-files", type=int, default=20000)
    cmd = sub.add_parser("skip")
    cmd.add_argument("--reason", required=True)
    cmd.add_argument("--receipt", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "build":
            result = run_build(args.root, args.manifest, args.receipt, args.max_files)
        else:
            result = run_skip(args.reason, args.receipt)
    except (ModuleError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"pass", "skip"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
