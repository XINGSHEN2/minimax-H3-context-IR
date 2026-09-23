import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch

from backend.agent import CORE_SKILLS, invoke_reasoning_json, SKILLS_DIR
from backend.prompt_instructions import COMPACT_WRITING_INSTRUCTIONS, RESPONSE_CONTRACT, build_compact_writing_prompt


def test_four_skills_loaded_in_dependency_order():
    assert CORE_SKILLS == (
        "h3-outline-planning",
        "h3-shot-planning",
        "h3-sound-planning",
        "h3-prompt-writing",
    )


def test_evidence_and_response_contract_round_trip():
    evidence = {"user_request": "保持结尾", "assets": [{"asset_id": "image_1"}]}
    before = copy.deepcopy(evidence)
    sent = build_compact_writing_prompt(evidence)
    suffix = "\n\n" + RESPONSE_CONTRACT
    assert sent.startswith(COMPACT_WRITING_INSTRUCTIONS) and sent.endswith(suffix)
    assert json.loads(sent[len(COMPACT_WRITING_INSTRUCTIONS):-len(suffix)]) == evidence
    assert evidence == before


def test_direct_runtime_receives_selected_bilingual_guides():
    runtime = Mock()
    runtime.invoke_json.return_value = {"ok": True}
    with patch.dict("os.environ", {"CONTEXT_IR_LLM_RUNTIME": "direct"}), patch(
        "backend.llm_runtime.direct_runtime_from_config", return_value=runtime
    ):
        invoke_reasoning_json(
            "test", {}, Path("unused.log"), list(CORE_SKILLS),
            prompt_profile="ref2va",
        )
    parts = runtime.invoke_json.call_args.kwargs["system_parts"]
    for name in ("shared-zh-en.txt", "ref2va-zh-en.txt"):
        expected = (SKILLS_DIR / "h3-prompt-writing" / "references" / name).read_text(encoding="utf-8")
        assert parts.count(expected) == 1
    base_guide = (SKILLS_DIR / "h3-prompt-writing" / "references" / "base-zh-en.txt").read_text(encoding="utf-8")
    assert base_guide not in parts
    for skill_name in CORE_SKILLS:
        expected = (SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert parts.count(expected) == 1


def test_intent_only_call_does_not_load_h3_guides():
    runtime = Mock()
    with patch.dict("os.environ", {"CONTEXT_IR_LLM_RUNTIME": "direct"}), patch(
        "backend.llm_runtime.direct_runtime_from_config", return_value=runtime
    ):
        invoke_reasoning_json("test", {}, Path("unused.log"))
    assert len(runtime.invoke_json.call_args.kwargs["system_parts"]) == 1
