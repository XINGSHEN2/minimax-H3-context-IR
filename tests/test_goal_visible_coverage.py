"""Instruction contract tests, not a claim about video quality."""
from backend.agent import build_prompt


def test_coverage_prioritizes_visible_goal_without_new_schema():
    prompt = build_prompt({
        'user_request': 'Show the clothes and bag naturally as the person leaves.',
        'task': {'type': 'ref2va', 'duration_seconds': 15, 'aspect_ratio': '16:9', 'generate_audio': False},
        'assets': [],
    })
    for rule in ('not equally to each verb', 'short enabling actions together',
                 'existing shot composition', 'isolated product insert'):
        assert rule in prompt


def test_coverage_does_not_shorten_user_demonstration_or_override_locked_shots():
    prompt = build_prompt({
        'user_request': 'Keep the specified four shots and show the entire operation.',
        'task': {'type': 'ref2va', 'duration_seconds': 15, 'aspect_ratio': '16:9', 'generate_audio': False},
        'assets': [],
    })
    for rule in ("itself the user's demonstration goal", 'user-locked shots, timing',
                 'universal close-up quota, shot count, or duration ratio'):
        assert rule in prompt
