import copy
import json
import unittest
from pathlib import Path

from backend.agent import compile_render_with_semantic_repair
from backend.context_ir import ContextIRError
from tests.test_input_contract import SourceContractTests


ROOT = Path(__file__).resolve().parents[1]


class SemanticRepairTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        self.valid = SourceContractTests._minimal_ir(self.source)

    def test_invalid_candidate_is_returned_to_reasoning_model_once(self):
        invalid = copy.deepcopy(self.valid)
        invalid["protocol"]["rewrite_language"] = "French"
        prompts = []

        def repair(prompt):
            prompts.append(prompt)
            return copy.deepcopy(self.valid)

        ir, prompt, audit = compile_render_with_semantic_repair(
            invalid, self.source, repair, max_repairs=1
        )

        self.assertTrue(prompt)
        self.assertEqual(ir["intent"]["user_request"], self.source["user_request"])
        self.assertTrue(audit["passed"])
        self.assertTrue(audit["repair"]["attempted"])
        self.assertEqual(audit["repair"]["attempts"], 1)
        self.assertEqual(len(prompts), 1)
        self.assertIn("REWRITE_LANGUAGE_INVALID", prompts[0])
        self.assertIn("Treat locked_source as immutable", prompts[0])

    def test_failed_repair_stops_after_configured_bound(self):
        invalid = copy.deepcopy(self.valid)
        invalid["protocol"]["rewrite_language"] = "French"
        calls = []

        def ineffective_repair(prompt):
            calls.append(prompt)
            return copy.deepcopy(invalid)

        with self.assertRaisesRegex(ContextIRError, "SEMANTIC_REPAIR_EXHAUSTED"):
            compile_render_with_semantic_repair(
                invalid, self.source, ineffective_repair, max_repairs=1
            )
        self.assertEqual(len(calls), 1)

    def test_valid_candidate_never_calls_repair_model(self):
        def unexpected(_prompt):
            self.fail("repair callback must not run for a valid candidate")

        _, _, audit = compile_render_with_semantic_repair(
            copy.deepcopy(self.valid), self.source, unexpected, max_repairs=1
        )
        self.assertTrue(audit["passed"])
        self.assertFalse(audit["repair"]["attempted"])


if __name__ == "__main__":
    unittest.main()
