"""Locate the skills/ and data/ directories.

In a source checkout they live at the repo root. In an installed wheel they are bundled
under ``support_agent/_bundled`` (see ``[tool.hatch...force-include]`` in pyproject.toml).
"""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_REPO = _PKG.parents[1]


def _root() -> Path:
    if (_REPO / "skills").is_dir() and (_REPO / "data").is_dir():
        return _REPO
    return _PKG / "_bundled"


def default_skills_dir() -> Path:
    return Path(os.environ.get("SUPPORT_AGENT_SKILLS", _root() / "skills"))


def default_data_dir() -> Path:
    return Path(os.environ.get("SUPPORT_AGENT_DATA", _root() / "data"))


def resolve_skills_dir(value: str | Path | None) -> Path:
    """Accept an absolute path, a path relative to cwd, or a bare name like ``skills_v1``."""
    if value is None:
        return default_skills_dir()
    p = Path(value)
    if p.is_dir():
        return p
    candidate = _root() / p
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(f"Skills directory not found: {value}")
