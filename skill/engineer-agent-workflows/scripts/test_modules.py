#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import evidence_protocol
import evaluation_harness
import memory_store
import project_context
import story_audit
from module_common import ModuleError, atomic_write_json, build_receipt, verify_receipt


def experience_record(outcome: str = "candidate passed"):
    return {
        "task_signature": "large refactor with interruption",
        "surface_request": "avoid repeated edits",
        "underlying_goal": "resume without rework",
        "decision": {"target": "recovery", "solution": "checkpoint", "risk_boundary": "no deletion"},
        "outcome": outcome,
        "error_classes": {
            "alignment": "checked",
            "assumption": "supported",
            "execution": "checked",
            "data": "one repository",
        },
        "lessons": ["read state before resuming"],
        "applicability_boundary": "local repositories",
        "retrieval_keys": ["refactor", "interruption", "state"],
        "evidence_refs": ["test-output.json"],
        "regression_checks": ["resume-test"],
        "task_type": "code_refactor",
        "environment": "Windows pnpm",
    }


def evidence_manifest():
    return {
        "claims": [
            {
                "id": "c1",
                "text": "No equivalent mechanism was found in the searched scope",
                "claim_type": "novelty",
                "support_ids": ["e1", "e2"],
                "negative_ids": ["e3"],
                "boundary": "official docs and repositories searched on 2026-07-20",
                "search_scope": "official docs and public repositories",
            }
        ],
        "evidence": [
            {
                "id": "e1",
                "source_type": "official_doc",
                "locator": "https://example.test/docs",
                "observed_at": "2026-07-20",
                "authority": "primary",
                "summary": "documented mechanisms differ",
                "direction": "supports",
            },
            {
                "id": "e2",
                "source_type": "repository",
                "locator": "repo:example",
                "observed_at": "2026-07-20",
                "authority": "primary",
                "summary": "implementation differs",
                "direction": "supports",
            },
            {
                "id": "e3",
                "source_type": "paper",
                "locator": "doi:example",
                "observed_at": "2026-07-20",
                "authority": "primary",
                "summary": "nearest contrary work reviewed",
                "direction": "negative_search",
            },
        ],
    }


def story_manifest():
    return {
        "problem": "Agents repeat accepted work after interruption",
        "importance_evidence": ["three observed failures"],
        "counterintuitive_entry": "more prompt text does not preserve state",
        "mechanism": "accepted state is not externalized",
        "solution_boundary": "tested only on local repositories",
        "claims": [
            {
                "id": "c1",
                "text": "external state reduced repeated edits in the test suite",
                "method": "checkpoint protocol",
                "evidence": ["evaluation-receipt.json"],
                "negative_evidence": ["one holdout still failed"],
                "boundary": "tested repositories only",
            }
        ],
        "problem_claim_mapping": ["c1"],
    }


def evaluation_inputs(candidate_success: bool = True):
    tasks = [
        {"id": "normal", "category": "normal"},
        {"id": "failure", "category": "known_failure"},
        {"id": "holdout", "category": "holdout"},
        {"id": "interrupt", "category": "perturbation"},
    ]
    suite = {
        "tasks": tasks,
        "thresholds": {
            "min_success_rate": 0.75,
            "max_constraint_violations": 0,
            "min_recovery_rate": 0.75,
            "max_task_regressions": 0,
            "max_token_increase_ratio": 1.2,
        },
    }

    def result(success_override=None, tokens=100):
        values = {}
        for task in tasks:
            success = True if success_override is None else success_override
            values[task["id"]] = {
                "success": success,
                "constraint_violations": 0,
                "first_pass": success,
                "repair_rounds": 0 if success else 2,
                "duplicate_work": 0,
                "context_hit": True,
                "context_noise": 1,
                "recovery_success": success,
                "tokens": tokens,
                "duration_seconds": 10,
            }
        return {"tasks": values}

    return suite, result(), result(candidate_success)


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_receipt_integrity(self):
        path = self.root / "receipt.json"
        receipt = build_receipt("x", 1, "pass", {"a": 1}, {"ok": True}, [])
        atomic_write_json(path, receipt)
        self.assertEqual(verify_receipt(path, "x")["status"], "pass")

    def test_receipt_tampering_is_detected(self):
        path = self.root / "receipt.json"
        receipt = build_receipt("x", 1, "pass", {"a": 1}, {"ok": True}, [])
        atomic_write_json(path, receipt)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["status"] = "fail"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ModuleError, "integrity"):
            verify_receipt(path)

    def test_memory_append_search_and_verify(self):
        store = self.root / "memory.jsonl"
        stored, count = memory_store.append_record(store, experience_record())
        self.assertEqual(count, 1)
        matches = memory_store.search_records(
            memory_store.load_records(store),
            ["interruption"],
            task_type="code_refactor",
            environment="Windows",
        )
        self.assertEqual(matches[0]["record_id"], stored["record_id"])
        self.assertTrue(memory_store.verify_store(store)["verified"])

    def test_memory_duplicate_rejected(self):
        store = self.root / "memory.jsonl"
        memory_store.append_record(store, experience_record())
        with self.assertRaisesRegex(ModuleError, "duplicate"):
            memory_store.append_record(store, experience_record())

    def test_memory_correction_supersedes_old_record(self):
        store = self.root / "memory.jsonl"
        old, _ = memory_store.append_record(store, experience_record("old conclusion"))
        new, _ = memory_store.append_record(
            store,
            experience_record("corrected conclusion"),
            relation="correction",
            supersedes=old["record_id"],
        )
        effective = memory_store.effective_records(memory_store.load_records(store))
        self.assertEqual([item["record_id"] for item in effective], [new["record_id"]])

    def test_evidence_protocol_passes_closed_manifest(self):
        receipt = evidence_protocol.run(evidence_manifest(), self.root / "evidence.json")
        self.assertEqual(receipt["status"], "pass")

    def test_evidence_protocol_rejects_missing_negative_search(self):
        manifest = evidence_manifest()
        manifest["claims"][0]["negative_ids"] = []
        receipt = evidence_protocol.run(manifest, self.root / "evidence.json")
        self.assertEqual(receipt["status"], "fail")
        self.assertTrue(any(item["code"] == "negative_search_missing" for item in receipt["issues"]))

    def test_project_context_builds_manifest(self):
        project = self.root / "project"
        project.mkdir()
        (project / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "index.ts").write_text("export const x = 1", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "x.test.ts").write_text("test('x',()=>{})", encoding="utf-8")
        receipt = project_context.run_build(
            project,
            self.root / "context.json",
            self.root / "context-receipt.json",
            100,
        )
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["summary"]["test_files"], 1)

    def test_project_context_skip_receipt(self):
        receipt = project_context.run_skip("non-repository conceptual task", self.root / "skip.json")
        self.assertEqual(receipt["status"], "skip")

    def test_story_audit_passes_closed_story(self):
        receipt = story_audit.run(story_manifest(), self.root / "story.json")
        self.assertEqual(receipt["status"], "pass")

    def test_story_audit_rejects_unsupported_inflation(self):
        story = story_manifest()
        story["claims"][0]["text"] = "This is the best paradigm and never fails"
        receipt = story_audit.run(story, self.root / "story.json")
        self.assertEqual(receipt["status"], "fail")
        self.assertTrue(any(item["code"] == "unsupported_inflation" for item in receipt["issues"]))

    def test_evaluation_harness_passes_candidate(self):
        suite, baseline, candidate = evaluation_inputs(True)
        receipt = evaluation_harness.run(
            suite, baseline, candidate, self.root / "evaluation.json"
        )
        self.assertEqual(receipt["status"], "pass")

    def test_evaluation_harness_rejects_regression(self):
        suite, baseline, candidate = evaluation_inputs(False)
        receipt = evaluation_harness.run(
            suite, baseline, candidate, self.root / "evaluation.json"
        )
        self.assertEqual(receipt["status"], "fail")
        self.assertTrue(any(item["code"] == "threshold_failed" for item in receipt["issues"]))

    def test_evaluation_zero_baseline_tokens_is_strict_json(self):
        suite, baseline, candidate = evaluation_inputs(True)
        for values in baseline["tasks"].values():
            values["tokens"] = 0
        receipt = evaluation_harness.run(
            suite, baseline, candidate, self.root / "evaluation.json"
        )
        self.assertEqual(receipt["status"], "fail")
        self.assertIsNone(receipt["summary"]["token_increase_ratio"])
        serialized = json.dumps(receipt, allow_nan=False)
        self.assertNotIn("Infinity", serialized)

    def test_evaluation_requires_all_categories(self):
        suite, baseline, candidate = evaluation_inputs(True)
        suite["tasks"] = suite["tasks"][:-1]
        with self.assertRaisesRegex(ModuleError, "missing categories"):
            evaluation_harness.compare(suite, baseline, candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
