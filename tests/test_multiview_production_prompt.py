"""Formal compiler instruction regression, not a model-quality verdict."""
from backend.agent import build_prompt


def test_formal_compiler_retains_multiview_appearance_in_ir():
    source = {
        'user_request': 'Use the people and clothes from the supplied views.',
        'task': {'type': 'ref2va', 'duration_seconds': 15, 'aspect_ratio': '16:9', 'generate_audio': False},
        'assets': [],
    }
    prompt = build_prompt(source)
    for rule in ('combine complementary front, side, back',
                 'garment neckline/fit/length',
                 "Subject's IR", 'Keep different subjects separate',
                 'uncertain rather than being force-merged'):
        assert rule in prompt
