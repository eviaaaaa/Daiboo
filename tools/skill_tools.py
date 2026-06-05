"""Skills tools for the NexusSurf agent.

Provides two tools:
- list_skills: lists all available skills with descriptions.
- view_skill: loads the full content of a specific skill.
"""

from langchain_core.tools import tool

from utils.skills import get_skill_by_name, load_skills, reload_skills


@tool
def list_skills() -> str:
    """List all available skills with their names and descriptions.

    Use this tool BEFORE performing any task to check if a relevant skill exists.
    Skills contain specialized procedural knowledge, workflows, and pitfalls for
    specific task types. Loading the right skill can save many rounds of trial-and-error.

    Returns a formatted list of skill names and descriptions.
    """
    skills = load_skills()
    if not skills:
        return "No skills available."

    lines: list[str] = ["Available skills:"]
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


@tool
def view_skill(name: str) -> str:
    """Load and return the full content of a specific skill.

    Call this tool when a skill from the list_skills output matches your current task.
    The skill content provides detailed instructions, commands, pitfalls, and
    verification steps that the agent should follow.

    Args:
        name: The skill name (exact match from list_skills output).

    Returns the full skill content, or an error message if not found.
    """
    skill = get_skill_by_name(name.strip())
    if skill is None:
        available = ", ".join([s.name for s in load_skills()]) or "none"
        return f"Skill '{name}' not found. Available skills: {available}"

    header = f"# Skill: {skill.name}\n"
    if skill.description:
        header += f"Description: {skill.description}\n"
    if skill.version and skill.version != "0.0.0":
        header += f"Version: {skill.version}\n"
    header += "\n"

    return header + skill.content
