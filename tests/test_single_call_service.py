import json
import time
from unittest.mock import patch

from backend.single_call_service import finish_single_call


def run(tmp_path, invalid=False):
    source = {'task': {'type': 'ref2va', 'duration_seconds': 5, 'aspect_ratio': '16:9'},
              'assets': [{'asset_id': 'image_1', 'media_type': 'image', 'uri': '/tmp/image.png'}]}
    answer = {'content_plan': {'bindings': [{'asset_id': 'image_1'}],
              'shots': [{'start_seconds': 0, 'end_seconds': 6 if invalid else 5}]},
              'h3_prompt': '<Picture 1> A continuous product view.'}
    with patch('backend.agent._compact_final_editor_source', return_value=source), \
         patch('backend.agent.invoke_reasoning_json', return_value=answer) as invoke:
        try:
            finish_single_call(source, tmp_path, {}, {'stages_seconds': {}}, time.perf_counter())
        except ValueError:
            assert invalid
        assert invoke.call_count == 1
    return tmp_path


def test_single_call_and_request(tmp_path):
    run(tmp_path)
    request = json.loads((tmp_path / 'h3_request.json').read_text())
    assert request['target']['duration_seconds'] == 5
    assert request['conditions'][0]['uri'] == '/tmp/image.png'
    assert json.loads((tmp_path / 'context_ir.json').read_text())['schema_version'] == 'h3_compilation.light.v1'
    assert json.loads((tmp_path / 'llm_optimization.json').read_text())['enabled'] is False


def test_no_hidden_retry_or_request_on_error(tmp_path):
    run(tmp_path, invalid=True)
    assert not (tmp_path / 'h3_request.json').exists()
    assert json.loads((tmp_path / 'result_status.json').read_text())['status'] == 'needs_review'
