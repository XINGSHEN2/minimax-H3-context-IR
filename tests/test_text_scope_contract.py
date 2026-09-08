from backend.agent import build_prompt


def test_text_accuracy_does_not_grant_source_authority():
    prompt = build_prompt({'user_request': 'Use image 1 only for atmosphere.', 'assets': []})
    assert 'source authority before checking spelling' in prompt
    assert 'Evidence that text exists is not permission to use it' in prompt
    assert 'even as optional overlays' in prompt
    assert 'already authorized by text_policy' in prompt


def test_required_text_visuals_are_not_erased_by_uncertain_ocr():
    prompt = build_prompt({'user_request': 'Keep the source signs and reflection.', 'assets': []})
    assert 'exact frame, or edit-base preservation' in prompt
    assert 'not a reason to omit a required sign, label, or reflection' in prompt
    assert 'without guessing' in prompt
