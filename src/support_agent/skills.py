"""Load and validate declarative SKILL.md files.

A skill is a folder containing ``SKILL.md``: YAML frontmatter (structured config) followed by a
markdown body (business rules). Adding a folder adds a support domain; no code changes needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .tools_impl import TOOL_NAMES

Priority = Literal["P1", "P2", "P3", "P4"]
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
_FIELD = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    description: str = Field(min_length=20, max_length=1000)
    persona: str = Field(min_length=10)
    required_fields: list[str] = Field(default_factory=list)
    intake_questions: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)
    priority_rules: dict[Priority, str]
    # Not part of the frontmatter; filled in by the loader.
    body: str = ""
    source: str = Field(default="", exclude=True)

    @model_validator(mode="after")
    def _check(self) -> Skill:
        problems = []
        for f in self.required_fields:
            if not _FIELD.match(f):
                problems.append(f"required field '{f}' must be snake_case")
            if f not in self.intake_questions:
                problems.append(f"required field '{f}' has no entry in intake_questions")
        for q in self.intake_questions:
            if q not in self.required_fields:
                problems.append(f"intake question '{q}' is not a required field")
        for t in self.allowed_tools:
            if t not in TOOL_NAMES:
                problems.append(f"unknown tool '{t}' (known: {', '.join(sorted(TOOL_NAMES))})")
        missing = {"P1", "P2", "P3", "P4"} - set(self.priority_rules)
        if missing:
            problems.append(f"priority_rules missing {sorted(missing)}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # -- prompt rendering ---------------------------------------------------------------------
    def router_card(self) -> str:
        return f"- {self.name}: {self.description}"

    def rules_block(self) -> str:
        esc = "\n".join(f"- {r}" for r in self.escalation_rules) or "- Escalate if unsure."
        pri = "\n".join(f"- {k}: {v}" for k, v in sorted(self.priority_rules.items()))
        return (
            f"# Active skill: {self.name}\n"
            f"Persona: {self.persona}\n\n"
            f"## Escalate when\n{esc}\n\n## Priority\n{pri}\n\n{self.body}".strip()
        )


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("missing YAML frontmatter delimited by '---'")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    skill = Skill(**meta, body=m.group(2).strip(), source=text)
    if skill.name != path.parent.name:
        raise ValueError(f"name '{skill.name}' must match folder name '{path.parent.name}'")
    return skill


def validate_skills(skills_dir: Path) -> tuple[dict[str, Skill], list[str]]:
    skills: dict[str, Skill] = {}
    errors: list[str] = []
    files = sorted(Path(skills_dir).glob("*/SKILL.md"))
    if not files:
        errors.append(f"{skills_dir}: no */SKILL.md files found")
    for path in files:
        try:
            skill = parse_skill(path)
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "frontmatter"
                errors.append(f"{path}: {loc}: {err['msg']}")
            continue
        except (ValueError, yaml.YAMLError) as e:
            errors.append(f"{path}: {e}")
            continue
        if skill.name == GENERAL.name:
            errors.append(f"{path}: '{GENERAL.name}' is reserved for the built-in fallback")
            continue
        skills[skill.name] = skill
    return skills, errors


def load_skills(skills_dir: Path) -> dict[str, Skill]:
    skills, errors = validate_skills(skills_dir)
    if errors:
        raise SkillError(errors)
    return skills


# Built-in fallback for messages no skill claims. It always escalates to a human.
GENERAL = Skill(
    name="general",
    description="Anything that does not clearly match another skill.",
    persona="Helpful generalist. Acknowledge the request and route it to a human.",
    allowed_tools=["search_kb"],
    escalation_rules=["Always escalate: no specialised skill matched this request."],
    priority_rules={
        "P1": "Safety threat or legal issue.",
        "P2": "Player cannot play at all.",
        "P3": "Default.",
        "P4": "Feedback or general question.",
    },
    body="Do not try to resolve the request yourself. Set escalate=true.",
)
