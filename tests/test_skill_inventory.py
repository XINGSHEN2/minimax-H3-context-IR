from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR


def test_only_active_and_optional_skills_are_packaged():
    packaged = {
        path.name
        for path in Path(SKILLS_DIR).iterdir()
        if path.is_dir() and (path / 'SKILL.md').is_file()
    }
    # Production packages only the two skills loaded by the compiler.
    assert packaged == set(CORE_SKILLS)


def test_shot_planning_skill_is_always_loaded():
    assert CORE_SKILLS == ('h3-prompt-writing', 'h3-shot-planning')
    assert (Path(SKILLS_DIR) / CORE_SKILLS[1] / 'SKILL.md').is_file()
