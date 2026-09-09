from backend.agent import build_prompt


def test_view_uncertainty_does_not_erase_observed_components():
    prompt = build_prompt({'assets': [], 'user_request': 'Use the reference product.'})
    assert "uncertain\n  view orientation does not invalidate a clearly observed component's shape" in prompt
    assert 'not proof of its absence' in prompt


def test_material_qualifier_is_consistent_through_compilation():
    prompt = build_prompt({'assets': [], 'user_request': 'Preserve its appearance.'})
    assert 'leather-like or metallic-looking does not' in prompt
    assert 'Subject,\n  binding and preservation constraint' in prompt
