import copy
import json
from unittest.mock import Mock

import pytest

from backend.compact_writer import COMPACT_WRITING_INSTRUCTIONS, write_compact_prompt


def test_instructions_prioritize_content_and_evidence_over_specificity():
    assert 'even if tagged visible' in COMPACT_WRITING_INSTRUCTIONS
    assert 'supported common' in COMPACT_WRITING_INSTRUCTIONS
    assert 'entire wording inside the visible frame' in COMPACT_WRITING_INSTRUCTIONS
    assert 'explicitly requested cropped typography' in COMPACT_WRITING_INSTRUCTIONS


def test_multiview_details_include_people_not_only_products():
    assert 'combine complementary observations' in COMPACT_WRITING_INSTRUCTIONS
    assert 'garment neckline/fit/length' in COMPACT_WRITING_INSTRUCTIONS
    assert 'different people or products' in COMPACT_WRITING_INSTRUCTIONS
    assert 'actually express them' in COMPACT_WRITING_INSTRUCTIONS


def test_one_call_preserves_input_constraints_and_authored_content():
    evidence = {
        "user_request": "只替换台词：别走了，好吗？",
        "completion_policy": {"creative": False},
        "directives": [{"operation": "exclude", "scope": ["music"]}],
        "assets": [{"asset_id": "video_1", "events": [{"time_range": [0, 9]}]}],
    }
    original = copy.deepcopy(evidence)
    result = {"content_plan": {"task_mode": "edit"},
              "h3_prompt": "Exact authored text\n<d>[Chinese] 别走了，好吗？</d>",
              "uncertainties": ["unheard source soundtrack"]}
    invoke = Mock(return_value=result)
    assert write_compact_prompt(evidence, invoke) == result
    invoke.assert_called_once()
    sent = invoke.call_args.args[0]
    assert json.loads(sent[len(COMPACT_WRITING_INSTRUCTIONS):]) == original
    assert evidence == original


@pytest.mark.parametrize("result", [[], {"content_plan": {}, "h3_prompt": ""},
                                   {"h3_prompt": "text", "content_plan": []}])
def test_incomplete_transport_result_is_not_returned_as_success(result):
    with pytest.raises(ValueError):
        write_compact_prompt({}, Mock(return_value=result))
