"""Prompt-contract regression only; real outputs still need content review."""
from backend.agent import build_prompt


def test_registry_anchor_does_not_force_unique_creative_priority():
    prompt = build_prompt({'user_request': 'Present both clothes and bag naturally.',
                           'assets': []})
    assert 'exactly one primary outcome subject' not in prompt
    assert 'Spend the remaining detail on how the primary subject' not in prompt
    assert 'technical registry anchor' in prompt
    assert 'relevant co-equal subjects' in prompt
    assert 'independently paraphrasing the same appearance' in prompt
    assert 'must dominate the finished video' not in prompt
    assert 'including joint goals where requested' in prompt


def test_explicit_priority_and_identity_separation_remain():
    prompt = build_prompt({'user_request': 'The bag is primary; the person supports it.',
                           'assets': []})
    assert "user's requested outcome" in prompt
    assert 'Do not collapse physical entities' in prompt
    assert 'not every non-anchor subject' in prompt
