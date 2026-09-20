from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR


def test_prompt_writing_is_the_only_active_core_skill():
    assert CORE_SKILLS == ("h3-prompt-writing",)
    assert (Path(SKILLS_DIR) / CORE_SKILLS[0] / "SKILL.md").is_file()


def test_shot_planning_remains_available_but_inactive():
    assert (Path(SKILLS_DIR) / "h3-shot-planning" / "SKILL.md").is_file()
    assert "h3-shot-planning" not in CORE_SKILLS
