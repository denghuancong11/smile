#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import workflow_guard as guard
import evidence_protocol
import evaluation_harness
import project_context
import story_audit
from module_common import atomic_write_json, build_receipt
from test_modules import evidence_manifest, evaluation_inputs, story_manifest


def sample_record():
    return {
        "task_signature": "large workflow refactor with state loss",
        "surface_request": "make the Agent workflow stable",
        "underlying_goal": "resume work without repeating completed changes",
        "decision": {
            "target": "state recovery",
            "solution": "external checkpoint gate",
            "risk_boundary": "no destructive writes",
        },
        "outcome": "the minimal interruption test passed in the tested repository",
        "error_classes": {
            "alignment": "no alignment error observed",
            "assumption": "state persistence hypothesis supported",
            "execution": "one encoding issue corrected",
            "data": "fixture covered one repository",
        },
        "lessons": ["external state must be read before resuming"],
        "applicability_boundary": "large local repositories with file-based state",
        "retrieval_keys": ["workflow", "state", "interruption"],
        "evidence_refs": ["tests/test_resume.py"],
        "regression_checks": ["resume-state-test"],
    }


def sample_value(stage: int, field: str):
    special = {
        (1, "alignment_confirmation"): "user_explicit",
        (1, "environment"): {
            "runtime": "Windows with Codex",
            "task_context": "large local repository refactor",
        },
        (1, "authorization_boundary"): {
            "allowed": ["read and test"],
            "requires_confirmation": ["external writes"],
            "forbidden": ["destructive operations"],
        },
        (5, "decision_source"): "user_explicit",
        (5, "decision_status"): "proceed",
        (6, "criteria_locked"): True,
        (7, "error_classification"): {
            "alignment": "checked against accepted goal",
            "assumption": "core hypothesis compared with result",
            "execution": "tool output and diff inspected",
            "data": "fixture coverage inspected",
        },
        (9, "check_passed"): True,
        (10, "final_status"): "validated",
    }
    if (stage, field) in special:
        return special[(stage, field)]
    spec = guard.STAGES[stage]
    type_name = spec.get("types", {}).get(field)
    count = spec.get("min_items", {}).get(field, 1)
    if type_name == "list":
        return [f"{field}-{index}" for index in range(1, count + 1)]
    if type_name == "dict":
        return {f"{field}-evidence": "verified"}
    choices = spec.get("enums", {}).get(field)
    if choices:
        return choices[0]
    if field in spec.get("booleans_true", []):
        return True
    return f"verified evidence for stage {stage} field {field}"


class WorkflowGuardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_path = self.root / "state.json"
        self.memory_path = self.root / "memory.jsonl"
        guard.init_state(
            self.state_path,
            "make an Agent workflow recoverable",
            memory_store=self.memory_path,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def open(self):
        return guard.open_turn(self.state_path)

    def attach_stage_receipt(self, token: str, stage: int):
        mapping = {
            1: ("context", "project-context", "skip"),
            4: ("evidence", "evidence-protocol", "pass"),
            7: ("story", "story-audit", "pass"),
            9: ("evaluation", "evaluation-harness", "pass"),
        }
        if stage not in mapping:
            return
        kind, module, status = mapping[stage]
        receipt_path = self.root / f"{kind}-receipt.json"
        receipt = build_receipt(
            module,
            1,
            status,
            {"stage": stage},
            {"verified": True},
            [],
        )
        atomic_write_json(receipt_path, receipt)
        guard.attach_receipt(self.state_path, token, kind, receipt_path)

    def fill_current(self, token: str):
        state = guard.load_state(self.state_path)
        stage = state["current_stage"]
        spec = guard.STAGES[stage]
        self.attach_stage_receipt(token, stage)
        if stage == 2:
            guard.memory_search(self.state_path, token, ["workflow", "state"])
        elif stage == 8:
            guard.deposit_experience(self.state_path, token, sample_record())
            return
        elif stage == 10:
            guard.memory_search(self.state_path, token, ["workflow", "state"])
        for field in spec["required"]:
            if field in set(spec.get("system_fields", [])):
                continue
            value = sample_value(stage, field)
            guard.put_value(
                self.state_path, token, stage, field, json.dumps(value, ensure_ascii=False)
            )

    def advance_one_stage(self):
        token = self.open()
        self.fill_current(token)
        result = guard.advance(self.state_path, token)
        guard.close_turn(self.state_path, token)
        return result

    def reach_stage(self, stage: int):
        while guard.load_state(self.state_path)["current_stage"] < stage:
            self.advance_one_stage()

    def test_initializes_schema_three_at_stage_one(self):
        state = guard.load_state(self.state_path)
        self.assertEqual(state["schema_version"], 3)
        self.assertEqual(state["current_stage"], 1)
        self.assertEqual(len(guard.STAGES), 10)

    def test_real_module_receipts_unlock_bound_stages(self):
        runners = {
            1: (
                "context",
                lambda path: project_context.run_skip(
                    "conceptual workflow test without a target repository", path
                ),
            ),
            4: (
                "evidence",
                lambda path: evidence_protocol.run(evidence_manifest(), path),
            ),
            7: (
                "story",
                lambda path: story_audit.run(story_manifest(), path),
            ),
            9: (
                "evaluation",
                lambda path: evaluation_harness.run(*evaluation_inputs(True), path),
            ),
        }
        for target_stage in [1, 4, 7, 9]:
            self.reach_stage(target_stage)
            token = self.open()
            kind, runner = runners[target_stage]
            receipt_path = self.root / f"real-{kind}-receipt.json"
            receipt = runner(receipt_path)
            self.assertIn(receipt["status"], {"pass", "skip"})
            attached = guard.attach_receipt(
                self.state_path, token, kind, receipt_path
            )
            self.assertEqual(attached["receipt_hash"], receipt["receipt_hash"])
            for field in guard.STAGES[target_stage]["required"]:
                if field in set(guard.STAGES[target_stage].get("system_fields", [])):
                    continue
                guard.put_value(
                    self.state_path,
                    token,
                    target_stage,
                    field,
                    json.dumps(sample_value(target_stage, field), ensure_ascii=False),
                )
            guard.advance(self.state_path, token)
            guard.close_turn(self.state_path, token)

    def test_old_schema_is_rejected(self):
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["schema_version"] = 2
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "start a new workflow"):
            guard.load_state(self.state_path)

    def test_memory_store_is_required(self):
        with self.assertRaisesRegex(guard.GuardError, "memory_store is required"):
            guard.init_state(self.root / "missing-memory.json", "objective")

    def test_cli_rejects_incomplete_advance(self):
        cli_state = Path(self.tempdir.name) / "cli-state.json"
        script = Path(guard.__file__)
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        subprocess.run(
            [
                sys.executable,
                str(script),
                "init",
                "--state",
                str(cli_state),
                "--memory",
                str(self.memory_path),
                "--objective",
                "verify the ten-stage command-line gate",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
        )
        opened = subprocess.run(
            [sys.executable, str(script), "open-turn", "--state", str(cli_state)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
        )
        token = json.loads(opened.stdout)["result"]["token"]
        rejected = subprocess.run(
            [
                sys.executable,
                str(script),
                "advance",
                "--state",
                str(cli_state),
                "--token",
                token,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stage gate failed", json.loads(rejected.stderr)["error"])

    def test_rejects_future_stage_write(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "current stage is 1"):
            guard.put_value(self.state_path, token, 2, "applicability_assessment", '"x"')

    def test_rejects_past_stage_write(self):
        self.advance_one_stage()
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "current stage is 2"):
            guard.put_value(self.state_path, token, 1, "surface_request", '"x"')

    def test_rejects_unknown_field(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "not allowed"):
            guard.put_value(self.state_path, token, 1, "future_solution", '"plugin"')

    def test_rejects_placeholder(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "placeholder"):
            guard.put_value(self.state_path, token, 1, "surface_request", '"待定"')

    def test_alignment_rejects_nested_unresolved_information(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "unresolved information"):
            guard.put_value(
                self.state_path,
                token,
                1,
                "environment",
                '{"runtime":"Windows","task_context":"用户尚未提供"}',
            )

    def test_alignment_requires_explicit_user_confirmation(self):
        token = self.open()
        self.fill_current(token)
        guard.put_value(
            self.state_path, token, 1, "alignment_confirmation", '"AI-inferred"'
        )
        errors = guard.check_current(self.state_path, token)["errors"]
        self.assertTrue(any(item.startswith("invalid_enum:alignment_confirmation") for item in errors))

    def test_alignment_rejects_solution_language(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "solution language"):
            guard.put_value(
                self.state_path,
                token,
                1,
                "acceptance_criteria",
                '["使用持久记录恢复状态","使用机器检查防止越界"]',
            )

    def test_detects_manual_tampering(self):
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["current_stage"] = 5
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "integrity check failed"):
            guard.load_state(self.state_path)

    def test_incomplete_stage_cannot_advance(self):
        token = self.open()
        guard.put_value(self.state_path, token, 1, "surface_request", '"stability"')
        with self.assertRaisesRegex(guard.GuardError, "stage gate failed"):
            guard.advance(self.state_path, token)

    def test_complete_stage_advances_exactly_one(self):
        result = self.advance_one_stage()
        self.assertEqual(result["current_stage"], 2)

    def test_no_new_stage_work_after_advance_in_same_turn(self):
        token = self.open()
        self.fill_current(token)
        guard.advance(self.state_path, token)
        with self.assertRaisesRegex(guard.GuardError, "already advanced"):
            guard.put_value(
                self.state_path, token, 2, "applicability_assessment", '"relevant"'
            )

    def test_cannot_advance_twice_in_same_turn(self):
        token = self.open()
        self.fill_current(token)
        guard.advance(self.state_path, token)
        with self.assertRaisesRegex(guard.GuardError, "only one stage transition"):
            guard.advance(self.state_path, token)

    def test_cannot_open_two_turns(self):
        self.open()
        with self.assertRaisesRegex(guard.GuardError, "already open"):
            self.open()

    def test_stage_two_recall_fields_cannot_be_faked(self):
        self.reach_stage(2)
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "guarded command"):
            guard.put_value(self.state_path, token, 2, "recall_result", '"matched"')

    def test_module_receipt_fields_cannot_be_faked(self):
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "guarded command"):
            guard.put_value(self.state_path, token, 1, "context_receipt", '"fake"')

    def test_receipt_cannot_attach_to_wrong_stage(self):
        token = self.open()
        receipt_path = self.root / "evidence.json"
        atomic_write_json(
            receipt_path,
            build_receipt("evidence-protocol", 1, "pass", {}, {}, []),
        )
        with self.assertRaisesRegex(guard.GuardError, "only allowed in stage 4"):
            guard.attach_receipt(self.state_path, token, "evidence", receipt_path)

    def test_failed_receipt_is_rejected(self):
        self.reach_stage(4)
        token = self.open()
        receipt_path = self.root / "evidence-failed.json"
        atomic_write_json(
            receipt_path,
            build_receipt("evidence-protocol", 1, "fail", {}, {}, [{"code": "x"}]),
        )
        with self.assertRaisesRegex(guard.GuardError, "status is not allowed"):
            guard.attach_receipt(self.state_path, token, "evidence", receipt_path)

    def test_tampered_receipt_is_rejected(self):
        token = self.open()
        receipt_path = self.root / "context-tampered.json"
        atomic_write_json(
            receipt_path,
            build_receipt("project-context", 1, "skip", {}, {}, []),
        )
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
        value["summary"] = {"tampered": True}
        receipt_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "integrity"):
            guard.attach_receipt(self.state_path, token, "context", receipt_path)

    def test_stage_two_verified_no_match_can_pass(self):
        self.reach_stage(2)
        token = self.open()
        result = guard.memory_search(self.state_path, token, ["never-seen-task"])
        self.assertEqual(result["matches"], [])
        guard.put_value(
            self.state_path,
            token,
            2,
            "applicability_assessment",
            '"no applicable historical record was found"',
        )
        self.assertTrue(guard.check_current(self.state_path, token)["passed"])

    def test_exploration_requires_three_operators_and_candidates(self):
        self.reach_stage(3)
        token = self.open()
        self.fill_current(token)
        guard.put_value(
            self.state_path, token, 3, "discovery_operators", '["only-one"]'
        )
        errors = guard.check_current(self.state_path, token)["errors"]
        self.assertIn("min_items:discovery_operators (required: 3)", errors)

    def test_challenge_requires_negative_evidence(self):
        self.reach_stage(4)
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "empty evidence"):
            guard.put_value(self.state_path, token, 4, "negative_evidence", "[]")

    def test_ai_cannot_supply_human_decision(self):
        self.reach_stage(5)
        token = self.open()
        self.fill_current(token)
        guard.put_value(self.state_path, token, 5, "decision_source", '"AI-decides"')
        errors = guard.check_current(self.state_path, token)["errors"]
        self.assertTrue(any(item.startswith("invalid_enum:decision_source") for item in errors))

    def test_validation_criteria_must_be_boolean_true(self):
        self.reach_stage(6)
        token = self.open()
        self.fill_current(token)
        guard.put_value(self.state_path, token, 6, "criteria_locked", '"true"')
        self.assertIn("must_be_true:criteria_locked", guard.check_current(self.state_path, token)["errors"])

    def test_retrospective_requires_four_error_classes(self):
        self.reach_stage(7)
        token = self.open()
        self.fill_current(token)
        guard.put_value(
            self.state_path,
            token,
            7,
            "error_classification",
            '{"alignment":"checked"}',
        )
        errors = guard.check_current(self.state_path, token)["errors"]
        self.assertTrue(any(item.startswith("missing_keys:error_classification") for item in errors))

    def test_deposit_is_guarded_and_persistent(self):
        self.reach_stage(8)
        token = self.open()
        record_id = guard.deposit_experience(self.state_path, token, sample_record())
        self.assertTrue(record_id.startswith("awr-"))
        self.assertTrue(self.memory_path.is_file())
        self.assertTrue(guard.check_current(self.state_path, token)["passed"])

    def test_deposit_rejects_incomplete_record(self):
        self.reach_stage(8)
        token = self.open()
        with self.assertRaisesRegex(guard.GuardError, "record missing"):
            guard.deposit_experience(self.state_path, token, {"task_signature": "x"})

    def test_regression_check_must_pass(self):
        self.reach_stage(9)
        token = self.open()
        self.fill_current(token)
        guard.put_value(self.state_path, token, 9, "check_passed", "false")
        self.assertIn("must_be_true:check_passed", guard.check_current(self.state_path, token)["errors"])

    def test_loop_requires_actual_memory_match(self):
        self.reach_stage(10)
        token = self.open()
        guard.memory_search(self.state_path, token, ["definitely-unmatched-key"])
        for field in ["influence_on_next_alignment", "loop_entry_rule", "final_status"]:
            guard.put_value(
                self.state_path,
                token,
                10,
                field,
                json.dumps(sample_value(10, field)),
            )
        errors = guard.check_current(self.state_path, token)["errors"]
        self.assertTrue(any(item.startswith("invalid_enum:retrieval_result") for item in errors))
        self.assertTrue(any(item.startswith("min_items:retrieved_record_ids") for item in errors))

    def test_rollback_clears_later_state_but_keeps_memory(self):
        self.reach_stage(9)
        self.assertTrue(self.memory_path.exists())
        token = self.open()
        guard.rollback(self.state_path, token, 4)
        state = guard.load_state(self.state_path)
        self.assertEqual(state["current_stage"], 4)
        self.assertEqual(state["stage_data"]["8"], {})
        self.assertTrue(self.memory_path.exists())

    def test_workflow_only_completes_after_stage_ten(self):
        for _ in range(9):
            result = self.advance_one_stage()
            self.assertEqual(result["status"], "active")
        final = self.advance_one_stage()
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["current_stage"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
