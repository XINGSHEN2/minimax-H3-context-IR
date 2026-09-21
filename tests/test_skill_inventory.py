from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR


def test_outline_shot_sound_and_writing_are_active_core_skills():
    assert CORE_SKILLS == (
        "h3-outline-planning", "h3-shot-planning",
        "h3-sound-planning", "h3-prompt-writing",
    )
    for skill_name in CORE_SKILLS:
        assert (Path(SKILLS_DIR) / skill_name / "SKILL.md").is_file()
