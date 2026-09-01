import json
import os
import unittest
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
