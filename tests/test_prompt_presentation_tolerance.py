import json
from pathlib import Path

import pytest

from backend.context_ir import audit_h3_prompt_contract, compile_context_ir, render_h3_prompt
from tests.test_input_contract import SourceContractTests


@pytest.fixture
def compiled_prompt():
    source = json.loads((Path(__file__).resolve().parents[1] /
                         "examples/resolved_request.case6.json").read_text())
    ir = compile_context_ir(SourceContractTests._minimal_ir(source), source)
    return ir, render_h3_prompt(ir)


def test_inline_shot_reference_does_not_force_model_retry(compiled_prompt):
    ir, prompt = compiled_prompt
    prompt = prompt.replace("detailed_description:\n",
                            "detailed_description:\nThe opening composition is used in [Shot 1].\n", 1)
    report = audit_h3_prompt_contract(ir, prompt)
    assert report.passed, report.to_dict()
    assert any(i.code == "PROMPT_SHOT_LABEL_NOT_LINE_START" and i.severity == "warning"
               for i in report.issues)


def test_sound_section_order_is_advisory_when_both_are_present(compiled_prompt):
    ir, prompt = compiled_prompt
    body, sound = prompt.split("overall_soundscape:\n", 1)
    ambience, music = sound.split("non_diegetic_music:\n", 1)
    reordered = body + "non_diegetic_music:\n" + music + "\n\noverall_soundscape:\n" + ambience
    report = audit_h3_prompt_contract(ir, reordered)
    assert report.passed, report.to_dict()
    assert any(i.code == "PROMPT_SECTION_ORDER" and i.severity == "warning"
               for i in report.issues)


def test_unavailable_reference_still_blocks(compiled_prompt):
    ir, prompt = compiled_prompt
    report = audit_h3_prompt_contract(ir, prompt.replace("<Picture 1>", "<Picture 99>"))
    assert not report.passed
    assert any(i.code == "REFERENCE_TAG_UNEXPECTED" and i.severity == "error"
               for i in report.issues)


def test_missing_visual_body_still_blocks(compiled_prompt):
    ir, prompt = compiled_prompt
    before, rest = prompt.split("detailed_description:\n", 1)
    _, sound = rest.split("overall_soundscape:\n", 1)
    report = audit_h3_prompt_contract(ir, before + "overall_soundscape:\n" + sound)
    assert not report.passed
    assert any(i.code == "PROMPT_SECTION_MISSING" and i.severity == "error"
               for i in report.issues)
