from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR


def test_only_active_skills_are_packaged():
    packaged = {
        path.name
        for path in Path(SKILLS_DIR).iterdir()
        if path.is_dir() and (path / 'SKILL.md').is_file()
    }
    assert packaged == set(CORE_SKILLS)


def test_all_four_planning_and_writing_skills_are_loaded():
    assert CORE_SKILLS == (
        'h3-outline-planning',
        'h3-shot-planning',
        'h3-sound-planning',
        'h3-prompt-writing',
    )
    for skill_name in CORE_SKILLS:
        assert (Path(SKILLS_DIR) / skill_name / 'SKILL.md').is_file()
