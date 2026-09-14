import json
import time
from unittest.mock import patch

from backend.compiler import compile_prompt


def run(tmp_path, invalid=False):
    source = {'task': {'type': 'ref2va', 'duration_seconds': 5, 'aspect_ratio': '16:9'},
              'assets': [{'asset_id': 'image_1', 'media_type': 'image', 'uri': '/tmp/image.png'}]}
    answer = {'content_plan': {'bindings': [{'asset_id': 'image_1'}],
              'shots': [{'start_seconds': 0, 'end_seconds': 6 if invalid else 5}]},
              'h3_prompt': '<Picture 1> A continuous product view.'}
    with patch('backend.evidence.build_writer_evidence', return_value=source), \
         patch('backend.agent.invoke_reasoning_json', return_value=answer) as invoke:
        try:
            compile_prompt(source, tmp_path, {}, {'stages_seconds': {}}, time.perf_counter())
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
    assert not (tmp_path / 'llm_optimization.json').exists()


def test_no_hidden_retry_or_request_on_error(tmp_path):
    run(tmp_path, invalid=True)
    assert not (tmp_path / 'h3_request.json').exists()
    assert json.loads((tmp_path / 'result_status.json').read_text())['status'] == 'needs_review'


def test_long_prompt_is_preserved_with_endpoint_warning(tmp_path):
    from backend.compiler import transport_issues
    source = {'task': {'type': 'ref2va', 'duration_seconds': 5, 'aspect_ratio': '16:9'}, 'assets': []}
    plan = {'bindings': [], 'shots': [{'start_seconds': 0, 'end_seconds': 5}]}
    prompt = '图😀\n ' * 1750
    answer = {'content_plan': plan, 'h3_prompt': prompt}
    assert len(prompt) == 7000
    assert not any('endpoint limit' in w for w in transport_issues(answer, source)[1])
    answer['h3_prompt'] += ' '
    errors, warnings = transport_issues(answer, source)
    assert not errors
    assert any('endpoint limit is 7000' in w for w in warnings)
    with patch('backend.evidence.build_writer_evidence', return_value=source), patch('backend.agent.invoke_reasoning_json', return_value=answer) as invoke:
        compile_prompt(source, tmp_path, {}, {'stages_seconds': {}}, time.perf_counter())
    assert invoke.call_count == 1
    assert (tmp_path / 'h3_prompt.txt').read_text() == answer['h3_prompt']
    audit = json.loads((tmp_path / 'h3_prompt_audit.json').read_text())
    assert audit['passed']
    assert audit['h3_prompt_chars'] == 7001
    assert audit['h3_v2_endpoint_max_chars'] == 7000
