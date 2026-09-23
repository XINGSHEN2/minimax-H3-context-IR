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
        self.assertIn("# H3 共用提示词协议", system)
        self.assertIn("# 全参考模式改写输出格式指南", system)
        self.assertNotIn("# 视频提示词编写指南（T2VA / I2VA / FL2VA / L2VA）", system)
        self.assertIn("## 7. Complete Example", system)
        self.assertIn("第一个镜头不写时间戳", system)
        self.assertNotIn("H3 镜头时间、连续性与转场执行", system)
        self.assertIn("## 3. `summary`", system)
        self.assertIn("## 4. `retention_analysis`", system)
        self.assertNotIn("前三个板块的信息边界与去重", system)
        self.assertIn("the environment identity anchors defined above remain consistent", system)
        self.assertNotIn("the coffee shop with its exposed brick wall", system)

    def test_base_loads_shared_and_base_only(self):
        system = self.injected_system("base")
        self.assertIn("# H3 共用提示词协议", system)
        self.assertIn("# 视频提示词编写指南（T2VA / I2VA / FL2VA / L2VA）", system)
        self.assertNotIn("# Full-Reference Mode Rewrite Output Format Guide", system)


if __name__ == "__main__":
    unittest.main()
