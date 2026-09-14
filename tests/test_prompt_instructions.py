import copy
import json
from unittest.mock import Mock

import pytest

from backend.prompt_instructions import COMPACT_WRITING_INSTRUCTIONS, build_compact_writing_prompt


def test_instructions_prioritize_content_and_evidence_over_specificity():
    assert '即使标为 visible' in COMPACT_WRITING_INSTRUCTIONS
    assert '有证据支持的共同外观' in COMPACT_WRITING_INSTRUCTIONS
    assert '完整处于画面内并留边距' in COMPACT_WRITING_INSTRUCTIONS
    assert '用户明确要求裁切字形' in COMPACT_WRITING_INSTRUCTIONS


def test_multiview_details_include_people_not_only_products():
    assert '同一对象的互补视图' in COMPACT_WRITING_INSTRUCTIONS
    assert '服装领口/版型/长度' in COMPACT_WRITING_INSTRUCTIONS
    assert '不同人物或产品' in COMPACT_WRITING_INSTRUCTIONS
    assert '实际落实到 h3_prompt' in COMPACT_WRITING_INSTRUCTIONS


def test_one_call_preserves_input_constraints_and_authored_content():
    evidence = {
        "user_request": "只替换台词：别走了，好吗？",
        "completion_policy": {"creative": False},
        "directives": [{"operation": "exclude", "scope": ["music"]}],
        "assets": [{"asset_id": "video_1", "events": [{"time_range": [0, 9]}]}],
    }
    original = copy.deepcopy(evidence)
    sent = build_compact_writing_prompt(evidence)
    assert json.loads(sent[len(COMPACT_WRITING_INSTRUCTIONS):]) == original
    assert evidence == original


def test_shot_scope_policy_shared_by_both_stages():
    from backend.prompt_instructions import SHOT_SCOPE_RULES
    from backend.intent_resolver import build_intent_prompt
    for request in (
        'Shot 1 人物背对镜头。→ Hard cut。非完整Prompt，可自行补充',
        '全程一镜到底，不要增加镜头',
        '片尾硬切结束，不要后续画面',
    ):
        source = {'user_request': request, 'assets': []}
        for prompt in (build_intent_prompt(source), build_compact_writing_prompt(source)):
            assert prompt.count(SHOT_SCOPE_RULES) == 1
            assert request in prompt
            assert '未描述后续' in prompt
            assert '片尾硬切' in prompt
            assert '不能以派生指令自身作证' in prompt


def test_minimum_completion_reaches_both_stages_without_changing_request():
    from backend.prompt_instructions import COMPLETION_RULES
    from backend.intent_resolver import build_intent_prompt
    for request in ('仅提供开场，可补充细节', '大胆发挥，设计完整故事和高潮', '严格复刻，一镜到底'):
        source = {'user_request': request, 'assets': []}
        before = copy.deepcopy(source)
        for prompt in (build_intent_prompt(source), build_compact_writing_prompt(source)):
            assert prompt.count(COMPLETION_RULES) == 1
            assert request in prompt
        assert source == before
