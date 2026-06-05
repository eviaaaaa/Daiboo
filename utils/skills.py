"""NaxusSurf Skills 加载与管理模块。

每个 skill 是一个目录，包含一个 SKILL.md 文件（YAML frontmatter + Markdown body）。
目录扫描、解析与缓存集中在此模块，供 Agent 工具与 API 复用。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Skills 目录：可通过环境变量覆盖，默认从仓库根目录解析
_ENV_SKILLS_DIR = "NAXUSSURF_SKILLS_DIR"
_SKILL_ENTRY = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_DEFAULT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def _skills_dir() -> Path:
    env = os.environ.get(_ENV_SKILLS_DIR, "").strip()
    if env:
        return Path(env)
    return _DEFAULT_ROOT / "skills"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class SkillMeta:
    name: str
    description: str
    version: str = "0.0.0"
    path: str = ""          # 磁盘目录路径
    tags: list[str] | None = None


@dataclass
class SkillInfo(SkillMeta):
    content: str = ""       # 完整 Markdown 正文（跳过 frontmatter）


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------

def _parse_skill(skill_dir: str, md_text: str) -> SkillInfo | None:
    """解析 SKILL.md 文本，返回 SkillInfo 或 None（无效时）。"""
    m = _FRONTMATTER_RE.match(md_text)
    if not m:
        return None

    frontmatter = m.group(1)
    body = md_text[m.end():]

    # 简单逐行解析 frontmatter（不引入 PyYAML 依赖）
    meta: dict[str, str] = {}
    for line in frontmatter.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip().lower()] = val.strip().strip("'\"")

    name = meta.get("name", Path(skill_dir).name)
    description = meta.get("description", "(no description)")
    version = meta.get("version", "0.0.0")
    tags_str = meta.get("tags", "")

    tags = None
    if tags_str:
        # 简单 [...] 分割
        inner = tags_str.strip("[]")
        tags = [t.strip().strip("\"'") for t in inner.split(",") if t.strip()]

    return SkillInfo(
        name=name,
        description=description,
        version=version,
        path=skill_dir,
        tags=tags,
        content=body.strip(),
    )


# ---------------------------------------------------------------------------
# 扫描与缓存
# ---------------------------------------------------------------------------

_skills_cache: list[SkillInfo] | None = None


def _scan_skills() -> list[SkillInfo]:
    """扫描 skills 目录，返回所有有效 SkillInfo 列表。"""
    sd = _skills_dir()
    if not sd.is_dir():
        return []

    result: list[SkillInfo] = []
    for entry in sorted(sd.iterdir()):
        if not entry.is_dir():
            continue
        md_path = entry / _SKILL_ENTRY
        if not md_path.is_file():
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            continue
        info = _parse_skill(str(entry.resolve()), text)
        if info is not None:
            result.append(info)

    return result


def load_skills() -> list[SkillInfo]:
    """加载所有 skills（内置缓存，每次调用返回相同列表）。"""
    global _skills_cache
    if _skills_cache is None:
        _skills_cache = _scan_skills()
    return _skills_cache


def get_skill_by_name(name: str) -> SkillInfo | None:
    """按名称查找单个 skill。"""
    for s in load_skills():
        if s.name == name:
            return s
    return None


def reload_skills() -> list[SkillInfo]:
    """强制刷新缓存。"""
    global _skills_cache
    _skills_cache = None
    return load_skills()


# ---------------------------------------------------------------------------
# 对外便捷接口（供 prompt / API / tools 直接使用）
# ---------------------------------------------------------------------------

def skills_summary() -> str:
    """返回一个适合注入系统提示词的人类可读技能列表。"""
    skills = load_skills()
    if not skills:
        return "(none)"

    lines: list[str] = []
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def skill_names() -> list[str]:
    return [s.name for s in load_skills()]
