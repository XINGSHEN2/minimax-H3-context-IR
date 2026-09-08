from pathlib import Path

from backend.agent import CORE_SKILLS, SKILLS_DIR, build_prompt


def test_only_active_skills_are_packaged():
    packaged = {
        path.name
        for path in Path(SKILLS_DIR).iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }
    assert packaged == set(CORE_SKILLS)


def test_shot_planning_skill_is_always_loaded():
    assert CORE_SKILLS == ("h3-prompt-writing", "h3-shot-planning")
    prompt = build_prompt({"task": {"duration_seconds": 8}})
    assert "h3-shot-planning" in prompt
