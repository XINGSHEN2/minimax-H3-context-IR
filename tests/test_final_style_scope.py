from backend.agent import build_final_optimization_prompt


def test_global_compression_does_not_expand_style_authority():
    prompt = build_final_optimization_prompt(
        {'user_request': 'Preserve the supplied final card exactly.', 'assets': []},
        {'subjects': [], 'timeline': []}, 'draft',
    )
    assert 'only across the' in prompt
    assert 'frame-anchor instruction takes precedence' in prompt
    assert 'independently' in prompt
    assert 'preserved card, insert or reference frame' in prompt
    assert 'Do not add, remove, merge, split, reorder, or retime shots' in prompt
