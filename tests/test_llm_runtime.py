import json
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.llm_runtime import DirectChatRuntime


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class DirectChatRuntimeTests(unittest.TestCase):
    def test_truncation_never_enters_syntax_only_repair(self):
        response = {"choices": [{"finish_reason": "length",
                                  "message": {"content": '{"partial":'}}]}
        with patch.dict(os.environ, {"TEST_LLM_KEY": "secret"}), patch(
            "urllib.request.urlopen", return_value=_Response(response)
        ) as request:
            with self.assertRaisesRegex(ValueError, "truncated"):
                DirectChatRuntime("http://llm.local/v1", "model-x", "TEST_LLM_KEY").invoke_json("test")
        self.assertEqual(request.call_count, 1)

    def test_explicit_v4_effort_is_sent_without_temperature(self):
        captured = {}
        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _Response({"choices": [{"message": {"content": '{"ok":true}'}}]})
        with patch.dict(os.environ, {"TEST_LLM_KEY": "secret",
                                    "CONTEXT_IR_DEEPSEEK_REASONING_EFFORT": "low"}), patch(
            "urllib.request.urlopen", fake_urlopen
        ):
            DirectChatRuntime("http://llm.local/v1", "deepseek-v4-flash", "TEST_LLM_KEY").invoke_json("test")
        self.assertEqual(captured["reasoning_effort"], "low")
        self.assertEqual(captured["thinking"], {"type": "enabled"})
        self.assertNotIn("temperature", captured)

    def test_invalid_v4_effort_fails_before_network(self):
        with patch.dict(os.environ, {"TEST_LLM_KEY": "secret",
                                    "CONTEXT_IR_DEEPSEEK_REASONING_EFFORT": "typo"}), patch(
            "urllib.request.urlopen"
        ) as request:
            with self.assertRaises(ValueError):
                DirectChatRuntime("http://llm.local/v1", "deepseek-v4-flash", "TEST_LLM_KEY").invoke_json("test")
        request.assert_not_called()

    def test_log_distinguishes_requested_and_returned_model(self):
        response = {
            "model": "resolved-model",
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
        }
        runtime = DirectChatRuntime("http://llm.local/v1", "alias", "TEST_LLM_KEY")
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ, {"TEST_LLM_KEY": "never-log-this-key"}
        ), patch("urllib.request.urlopen", return_value=_Response(response)):
            log_path = Path(folder) / "response.log"
            runtime.invoke_json("compile", log_path=log_path)
            text = log_path.read_text(encoding="utf-8")
            metadata = json.loads(text.splitlines()[0])
        self.assertEqual(metadata["model"], "alias")
        self.assertEqual(metadata["response_model"], "resolved-model")
        self.assertEqual(metadata["finish_reason"], "stop")
        self.assertEqual(metadata["usage"]["completion_tokens"], 4)
        self.assertFalse(metadata["json_repaired"])
        self.assertNotIn("never-log-this-key", text)

    def test_json_call_has_no_tools_and_loads_system_context(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response({"choices": [{"message": {"content": '{"ok":true}'}}]})

        runtime = DirectChatRuntime("http://llm.local/v1", "model-x", "TEST_LLM_KEY", 12)
        with patch.dict(os.environ, {"TEST_LLM_KEY": "secret"}, clear=False), patch(
            "urllib.request.urlopen", fake_urlopen
        ):
            result = runtime.invoke_json("compile", system_parts=["base rules", "skill rules"])
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["url"], "http://llm.local/v1/chat/completions")
        self.assertNotIn("tools", captured["payload"])
        self.assertIn("skill rules", captured["payload"]["messages"][0]["content"])
        self.assertEqual(captured["timeout"], 12)


if __name__ == "__main__":
    unittest.main()
