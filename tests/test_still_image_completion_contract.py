from backend.agent import build_prompt


def test_missing_motion_evidence_is_not_a_target_prohibition():
    prompt = build_prompt({'assets': [], 'user_request': 'Opening shot only; continue it.'})
    assert 'Absence of observed motion does not authorize a stillness lock' in prompt
    assert 'same subjects' in prompt
    assert 'as completion, never as evidence' in prompt
    assert "static nature disable authorized performance" in prompt


def test_explicit_stillness_and_reference_authority_still_apply():
    prompt = build_prompt({'assets': [], 'user_request': 'Keep the person still in shot 1.'})
    assert 'preserve specified\n  stillness within its actual shot scope' in prompt
    assert 'but never motion authority' in prompt
    assert 'when continuation is authorized' in prompt
