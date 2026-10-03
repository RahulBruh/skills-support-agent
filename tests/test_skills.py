from pathlib import Path

import pytest

from support_agent.paths import resolve_skills_dir
from support_agent.skills import SkillError, load_skills, validate_skills

VALID = """---
name: {name}
description: Handles questions about in-game tournaments and their rewards.
persona: Upbeat esports coordinator.
required_fields: [tournament_id]
intake_questions:
  tournament_id: Which tournament?
allowed_tools: [{tool}]
escalation_rules: [Missing rewards -> escalate.]
priority_rules: {{P1: a, P2: b, P3: c, P4: d}}
---
Body rules here.
"""


def write_skill(root: Path, folder: str, text: str) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("name", ["skills", "skills_v1"])
def test_shipped_skill_sets_are_valid(name):
    skills = load_skills(resolve_skills_dir(name))
    assert {"billing", "account-recovery", "bug-report"} <= set(skills)


def test_new_skill_is_picked_up_without_code(tmp_path):
    write_skill(tmp_path, "tournaments", VALID.format(name="tournaments", tool="search_kb"))
    skills = load_skills(tmp_path)
    s = skills["tournaments"]
    assert s.required_fields == ["tournament_id"]
    assert s.body == "Body rules here."
    assert s.router_card().startswith("- tournaments: Handles questions")


def test_unknown_tool_is_rejected(tmp_path):
    write_skill(tmp_path, "tournaments", VALID.format(name="tournaments", tool="issue_refund"))
    _, errors = validate_skills(tmp_path)
    assert any("unknown tool 'issue_refund'" in e for e in errors)


def test_required_field_needs_question(tmp_path):
    text = VALID.format(name="t", tool="search_kb").replace(
        "required_fields: [tournament_id]", "required_fields: [tournament_id, region]"
    )
    write_skill(tmp_path, "t", text)
    _, errors = validate_skills(tmp_path)
    assert any("'region' has no entry in intake_questions" in e for e in errors)


def test_name_must_match_folder(tmp_path):
    write_skill(tmp_path, "other", VALID.format(name="tournaments", tool="search_kb"))
    _, errors = validate_skills(tmp_path)
    assert any("must match folder name" in e for e in errors)


def test_general_is_reserved(tmp_path):
    write_skill(tmp_path, "general", VALID.format(name="general", tool="search_kb"))
    with pytest.raises(SkillError, match="reserved"):
        load_skills(tmp_path)


def test_missing_frontmatter(tmp_path):
    write_skill(tmp_path, "x", "just markdown")
    _, errors = validate_skills(tmp_path)
    assert any("frontmatter" in e for e in errors)
