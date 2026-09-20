from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR


def test_writing_shot_and_sound_planning_are_active_core_skills():
    assert CORE_SKILLS == ("h3-prompt-writing", "h3-shot-planning", "h3-sound-planning")
    for skill_name in CORE_SKILLS:
        assert (Path(SKILLS_DIR) / skill_name / "SKILL.md").is_file()
