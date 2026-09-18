import json
import time
from unittest.mock import patch

from backend.compiler import compile_prompt


VALID_H3 = '''subject_definitions:
<Picture 1> is the reference.
summary:
A concise target video.
retention_analysis:
<Picture 1> is preserved.
detailed_description:
[Shot 1] A continuous view.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A'''


def run(tmp_path, invalid=False):
    source = {'task': {'type': 'ref2va', 'duration_seconds': 5, 'aspect_ratio': '16:9'},
              'assets': [{'asset_id': 'image_1', 'media_type': 'image', 'uri': '/tmp/image.png'}]}
    answer = {'content_plan': {'bindings': [{'asset_id': 'image_1'}],
              'shots': [{'start_seconds': 0, 'end_seconds': 6 if invalid else 5}]},
              'h3_prompt': VALID_H3}
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


def test_long_prompt_is_preserved_without_assumed_endpoint_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTEXT_IR_H3_TEXT_MAX_CHARS", raising=False)
    from backend.compiler import transport_issues
    source = {'task': {'type': 'ref2va', 'duration_seconds': 5, 'aspect_ratio': '16:9'}, 'assets': []}
    plan = {'bindings': [], 'shots': [{'start_seconds': 0, 'end_seconds': 5}]}
    prompt = VALID_H3 + 'x' * (7000 - len(VALID_H3))
    answer = {'content_plan': plan, 'h3_prompt': prompt}
    assert len(prompt) == 7000
    assert not any('endpoint limit' in w for w in transport_issues(answer, source)[1])
    answer['h3_prompt'] += ' '
    errors, warnings = transport_issues(answer, source)
    assert not errors
    assert not any('text limit' in w or 'endpoint limit' in w for w in warnings)
    with patch('backend.evidence.build_writer_evidence', return_value=source), patch('backend.agent.invoke_reasoning_json', return_value=answer) as invoke:
        compile_prompt(source, tmp_path, {}, {'stages_seconds': {}}, time.perf_counter())
    assert invoke.call_count == 1
    assert (tmp_path / 'h3_prompt.txt').read_text() == answer['h3_prompt']
    audit = json.loads((tmp_path / 'h3_prompt_audit.json').read_text())
    assert audit['passed']
    assert audit['h3_prompt_chars'] == 7001
    assert audit['h3_v2_endpoint_max_chars'] is None


def test_explicit_deployment_limit_warns_without_rejecting_or_truncating(monkeypatch):
    from backend.compiler import transport_issues
    monkeypatch.setenv('CONTEXT_IR_H3_TEXT_MAX_CHARS', '7000')
    source = {'task': {'duration_seconds': 5}, 'assets': []}
    answer = {'content_plan': {'bindings': [], 'shots': [{'start_seconds': 0, 'end_seconds': 5}]}, 'h3_prompt': VALID_H3 + 'x' * (7001 - len(VALID_H3))}
    errors, warnings = transport_issues(answer, source)
    assert not errors
    assert any('configured H3 text limit is 7000' in w for w in warnings)
    assert len(answer['h3_prompt']) == 7001
