from pathlib import Path
from unittest.mock import Mock, patch

from backend.agent import invoke_reasoning_json, SKILLS_DIR


def test_direct_runtime_receives_selected_bilingual_guides():
    runtime = Mock()
    runtime.invoke_json.return_value = {"ok": True}
    with patch.dict("os.environ", {"CONTEXT_IR_LLM_RUNTIME": "direct"}), patch(
        "backend.llm_runtime.direct_runtime_from_config", return_value=runtime
    ):
        invoke_reasoning_json(
            "test", {}, Path("unused.log"), ["h3-prompt-writing"],
            prompt_profile="ref2va",
        )
    parts = runtime.invoke_json.call_args.kwargs["system_parts"]
    for name in ("shared-zh-en.txt", "ref2va-zh-en.txt"):
        expected = (SKILLS_DIR / "h3-prompt-writing" / "references" / name).read_text(encoding="utf-8")
        assert parts.count(expected) == 1
    base_guide = (SKILLS_DIR / "h3-prompt-writing" / "references" / "base-zh-en.txt").read_text(encoding="utf-8")
    assert base_guide not in parts


def test_intent_only_call_does_not_load_h3_guides():
    runtime = Mock()
    with patch.dict("os.environ", {"CONTEXT_IR_LLM_RUNTIME": "direct"}), patch(
        "backend.llm_runtime.direct_runtime_from_config", return_value=runtime
    ):
        invoke_reasoning_json("test", {}, Path("unused.log"))
    assert len(runtime.invoke_json.call_args.kwargs["system_parts"]) == 1
