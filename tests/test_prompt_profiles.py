import copy
import unittest
from unittest.mock import Mock, patch

from backend.agent import invoke_reasoning_json, prompt_profile_for_source
from backend.contracts import normalize_source_request, validate_source_request


class PromptProfileTests(unittest.TestCase):
    def source(self, task_type="ref2va", profile="auto"):
        return {
            "user_request": "test",
            "task": {
                "type": task_type,
                "prompt_profile": profile,
                "duration_seconds": 5,
                "aspect_ratio": "16:9",
            },
            "assets": [],
        }

    def test_auto_profile_follows_task_type(self):
        self.assertEqual(prompt_profile_for_source(self.source("ref2va")), "ref2va")
        self.assertEqual(prompt_profile_for_source(self.source("t2va")), "base")

    def test_normalization_defaults_to_auto(self):
        source = self.source()
        del source["task"]["prompt_profile"]
        normalized = normalize_source_request(source)
        self.assertEqual(normalized["task"]["prompt_profile"], "auto")

    def test_profile_task_mismatch_is_rejected(self):
        self.assertFalse(validate_source_request(self.source("ref2va", "base")).passed)
        self.assertFalse(validate_source_request(self.source("t2va", "ref2va")).passed)

    def injected_system(self, profile):
        runtime = Mock()
        runtime.invoke_json.return_value = {}
        with patch("backend.llm_runtime.direct_runtime_from_config", return_value=runtime):
            invoke_reasoning_json(
                "prompt", {"selection":"test"}, Mock(),
                ["h3-prompt-writing"], prompt_profile=profile,
            )
        return "\n".join(runtime.invoke_json.call_args.kwargs["system_parts"])

    def test_ref2va_loads_shared_and_ref_only(self):
        system = self.injected_system("ref2va")
        self.assertIn("# Shared H3 Prompt Protocol", system)
        self.assertIn("# Full-Reference Mode Rewrite Output Format Guide", system)
        self.assertNotIn("# Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)", system)
        self.assertNotIn("## 7. Complete Example", system)

    def test_base_loads_shared_and_base_only(self):
        system = self.injected_system("base")
        self.assertIn("# Shared H3 Prompt Protocol", system)
        self.assertIn("# Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)", system)
        self.assertNotIn("# Full-Reference Mode Rewrite Output Format Guide", system)


if __name__ == "__main__":
    unittest.main()
