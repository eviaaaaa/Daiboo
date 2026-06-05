"""Tests for the NaxusSurf skills system."""

from __future__ import annotations

import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# utils.skills module tests
# ---------------------------------------------------------------------------

def test_skills_dir_defaults_to_project_root():
    from utils.skills import _skills_dir as skills_dir

    expected = Path(__file__).resolve().parents[1] / "skills"
    assert skills_dir() == expected


def test_skills_dir_respects_env(monkeypatch):
    monkeypatch.setenv("NAXUSSURF_SKILLS_DIR", "/custom/skills")
    if "utils.skills" in sys.modules:
        del sys.modules["utils.skills"]
    from utils.skills import _skills_dir as skills_dir

    assert skills_dir() == Path("/custom/skills")


def test_parse_valid_skill():
    from utils.skills import _parse_skill

    md = """---
name: test-skill
description: A test skill
version: 1.0.0
tags: [python, testing]
---

# Hello

This is the content.
"""
    info = _parse_skill("/fake/skills/test-skill", md)
    assert info is not None
    assert info.name == "test-skill"
    assert info.description == "A test skill"
    assert info.version == "1.0.0"
    assert info.tags == ["python", "testing"]
    assert info.path == "/fake/skills/test-skill"
    assert "Hello" in info.content
    assert "This is the content" in info.content


def test_parse_skill_no_frontmatter_returns_none():
    from utils.skills import _parse_skill

    assert _parse_skill("/fake", "# Just markdown") is None
    assert _parse_skill("/fake", "") is None


def test_parse_skill_minimal_frontmatter():
    from utils.skills import _parse_skill

    md = """---
name: minimal
---

Content here.
"""
    info = _parse_skill("/fake/skills/minimal", md)
    assert info is not None
    assert info.name == "minimal"
    assert info.description == "(no description)"
    assert info.version == "0.0.0"
    assert info.content == "Content here."


def test_load_skills_finds_example_skill():
    from utils.skills import load_skills, reload_skills

    reload_skills()
    skills = load_skills()
    names = [s.name for s in skills]
    assert "naxussurf-dev" in names, f"Expected naxussurf-dev in {names}"


def test_get_skill_by_name():
    from utils.skills import get_skill_by_name

    skill = get_skill_by_name("naxussurf-dev")
    assert skill is not None
    assert skill.name == "naxussurf-dev"
    assert "NaxusSurf" in skill.description
    assert len(skill.content) > 100


def test_get_skill_by_name_missing():
    from utils.skills import get_skill_by_name

    assert get_skill_by_name("nonexistent-skill") is None


def test_skills_summary_format():
    from utils.skills import skills_summary

    summary = skills_summary()
    assert "naxussurf-dev" in summary


def test_load_skills_empty_dir(monkeypatch, tmp_path):
    # Clear cache first, then set env for this test only
    monkeypatch.setenv("NAXUSSURF_SKILLS_DIR", str(tmp_path))
    if "utils.skills" in sys.modules:
        del sys.modules["utils.skills"]
    from utils.skills import load_skills, reload_skills

    reload_skills()
    assert load_skills() == []


# ---------------------------------------------------------------------------
# Tools tests (unit, no MCP needed)
# ---------------------------------------------------------------------------

def test_list_skills_tool_returns_available_skills():
    # Ensure cache is fresh with real skills dir
    from utils.skills import reload_skills
    reload_skills()

    from tools.skill_tools import list_skills

    result = list_skills.invoke({})
    assert "naxussurf-dev" in result
    assert "Available skills" in result


def test_view_skill_tool_returns_content():
    from utils.skills import reload_skills
    reload_skills()

    from tools.skill_tools import view_skill

    result = view_skill.invoke({"name": "naxussurf-dev"})
    assert "NaxusSurf Development Guide" in result
    assert "Project Architecture" in result


def test_view_skill_tool_not_found():
    from tools.skill_tools import view_skill

    result = view_skill.invoke({"name": "does-not-exist"})
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Lazy export test
# ---------------------------------------------------------------------------

def test_skill_tools_exported_from_package():
    from tools import list_skills, view_skill

    # LangChain @tool decorators produce StructuredTool objects
    assert hasattr(list_skills, "invoke")
    assert hasattr(view_skill, "invoke")
    assert list_skills.name == "list_skills"
    assert view_skill.name == "view_skill"
