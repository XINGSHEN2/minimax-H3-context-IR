import copy
import json
from pathlib import Path

from backend.context_ir import compile_context_ir, render_h3_prompt, audit_h3_prompt_contract
from tests.test_input_contract import SourceContractTests


def fixture():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / 'examples/resolved_request.case6.json').read_text())
    ir = compile_context_ir(SourceContractTests._minimal_ir(source), source)
    second = copy.deepcopy(ir['subjects'][0])
    second.update(subject_id='subject_2', primary=False)
    ir['subjects'].append(second)
    ir['timeline'][0]['subject_refs'].append('subject_2')
    return ir


def test_renderer_respects_declared_joint_priority():
    ir = fixture()
    ir['semantic_plan'] = {'subject_priority': {
        'mode': 'co_equal', 'subject_ids': ['subject_1', 'subject_2']}}
    prompt = render_h3_prompt(ir)
    summary = prompt.split('summary:', 1)[1].split('retention_analysis:', 1)[0]
    assert '<Subject 1>, <Subject 2> share the creative focus' in summary
    assert 'is the primary creative focus' not in summary
    assert 'PROMPT_COEQUAL_PRIORITY_CONTRADICTION' not in {
        issue.code for issue in audit_h3_prompt_contract(ir, prompt).issues}


def test_single_priority_is_not_turned_into_joint_focus():
    ir = fixture()
    prompt = render_h3_prompt(ir)
    summary = prompt.split('summary:', 1)[1].split('retention_analysis:', 1)[0]
    assert '<Subject 1> is the primary creative focus' in summary
    assert 'share the creative focus' not in summary
