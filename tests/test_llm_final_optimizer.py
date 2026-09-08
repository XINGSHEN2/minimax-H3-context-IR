import copy
import json
import unittest
from pathlib import Path

from backend.agent import _compact_final_editor_source, accept_final_optimization, build_final_optimization_prompt
from tests.test_input_contract import SourceContractTests


ROOT = Path(__file__).resolve().parents[1]


class LLMFinalOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        self.draft = SourceContractTests._minimal_ir(self.source)

    def test_optimizer_always_rewrites_instead_of_scoring(self):
        prompt = build_final_optimization_prompt(
            self.source,
            self.draft,
            "draft prompt",
            semantic_warnings=[{
                "code": "SHOT_CAMERA_CONTRADICTION",
                "message": "static and moving camera wording",
                "path": "$.timeline[0].camera",
                "severity": "warning",
            }],
        )
        self.assertIn("immutable", prompt)
        self.assertIn("H3 Prompt directly", prompt)
        self.assertIn("Do not add, remove, merge, split, reorder, or retime shots", prompt)
        self.assertIn("Do not output", prompt)
        self.assertIn("passed", prompt)
        self.assertIn("h3_prompt", prompt)
        self.assertIn("warning_resolutions", prompt)
        self.assertIn("SHOT_CAMERA_CONTRADICTION", prompt)

    def test_final_optimizer_locks_the_entire_semantic_ir(self):
        original = copy.deepcopy(self.draft)
        optimized = {
            "context_ir": {
                "task": {"duration_seconds": 999},
                "assets": [],
                "timeline": [{"shot_id": "01", "event": "optimized shot"}],
            },
            "h3_prompt": "subject_definitions:\n<Subject 1> is optimized.",
            "optimization_notes": [{"type": "camera", "location": "01", "change": "simplified", "reason": "clarity"}],
            "warning_resolutions": [{
                "code": "SHOT_CAMERA_CONTRADICTION",
                "path": "$.timeline[0].camera",
                "status": "resolved",
                "action": "kept the authorized camera move",
            }],
        }
        final_ir, final_prompt, metadata = accept_final_optimization(
            optimized,
            original,
            [{
                "code": "SHOT_CAMERA_CONTRADICTION",
                "path": "$.timeline[0].camera",
                "severity": "warning",
            }],
        )
        self.assertEqual(final_ir["task"], original["task"])
        self.assertEqual(final_ir["assets"], original["assets"])
        self.assertEqual(final_ir, original)
        self.assertEqual(final_prompt, optimized["h3_prompt"])
        self.assertFalse(metadata["programmatic_content_audit"])
        self.assertTrue(metadata["semantic_ir_locked"])
        self.assertTrue(metadata["ignored_context_ir_output"])
        self.assertEqual(len(metadata["semantic_warnings_input"]), 1)
        self.assertEqual(metadata["semantic_warning_resolutions"][0]["status"], "resolved")

    def test_optimizer_limits_notes_and_receives_reference_registry(self):
        source = copy.deepcopy(self.source)
        first_asset_id = source["assets"][0]["asset_id"]
        source["asset_mentions"] = [{
            "source_text": "图1", "resolved_asset_ids": [first_asset_id],
        }]
        compact = _compact_final_editor_source(source)
        self.assertEqual(compact["reference_registry"][0]["official_label"], "<Picture 1>")
        self.assertIn("图1", compact["reference_registry"][0]["aliases"])
        optimized = {
            "h3_prompt": "subject_definitions:\n<Subject 1> is optimized.",
            "optimization_notes": [
                {"type": "change", "location": str(index), "change": "x", "reason": "y"}
                for index in range(8)
            ],
        }
        _, _, metadata = accept_final_optimization(optimized, self.draft)
        self.assertEqual(len(metadata["optimization_notes"]), 5)

    def test_warning_resolutions_must_be_an_array(self):
        with self.assertRaisesRegex(ValueError, "warning_resolutions must be an array"):
            accept_final_optimization(
                {
                    "h3_prompt": "subject_definitions:\n<Subject 1> is optimized.",
                    "optimization_notes": [],
                    "warning_resolutions": "resolved",
                },
                self.draft,
            )

    def test_empty_llm_prompt_is_rejected_as_transport_contract(self):
        with self.assertRaisesRegex(ValueError, "non-empty h3_prompt"):
            accept_final_optimization(
                {"h3_prompt": "", "optimization_notes": []},
                self.draft,
            )


if __name__ == "__main__":
    unittest.main()
