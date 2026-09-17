import io
import json
from unittest.mock import patch

import pytest

from backend.llm_runtime import DirectChatRuntime


def response(content, reasoning=None, finish="stop"):
    message = {"content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return io.BytesIO(json.dumps({"choices": [{"message": message, "finish_reason": finish}],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 12}}}).encode())


@pytest.mark.parametrize("mode", ["normal", "missing", "truncated", "repair", "repair_failed"])
def test_reasoning_saved_before_parsing(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("TEST_REASONING_KEY", "secret-test-key")
    first = response('{"ok": true}' if mode in ("normal", "missing") else 'bad json',
                     None if mode == "missing" else "检查约束\n规划镜头", "length" if mode == "truncated" else "stop")
    responses = [first]
    if mode.startswith("repair"):
        responses.append(response('{"ok": true}' if mode == "repair" else 'still invalid', "修复语法"))
    log = tmp_path / "writer_1.log"
    with patch("urllib.request.urlopen", side_effect=responses) as call:
        runtime = DirectChatRuntime("http://test.local", "test", "TEST_REASONING_KEY")
        if mode in ("truncated", "repair_failed"):
            with pytest.raises(ValueError):
                runtime.invoke_json("test", log_path=log)
        else:
            assert runtime.invoke_json("test", log_path=log) == {"ok": True}
        assert call.call_count == len(responses)
    text = log.with_suffix(".reasoning.json").read_text()
    records = json.loads(text)["responses"]
    assert records[0]["reasoning_tokens"] == 12
    assert records[0]["reasoning_content"] == (None if mode == "missing" else "检查约束\n规划镜头")
    assert records[0]["reasoning_content_returned"] == (mode != "missing")
    assert "secret-test-key" not in text
    if mode.startswith("repair"):
        assert records[1]["stage"] == "json_repair"
        assert records[1]["reasoning_content"] == "修复语法"
