---
name: naxussurf-dev
description: "NaxusSurf project development: architecture, testing, and workflows."
version: 1.0.0
tags: [naxussurf, development, testing]
---

# NaxusSurf Development Guide

## Project Architecture

NaxusSurf is a FastAPI + LangGraph browser automation agent with these layers:

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api.py` | FastAPI endpoints: /chat, /tools, /upload, /rag/*, /skills |
| Agent | `utils/agent_factory.py` | LangGraph agent assembly, tool set, middleware chain |
| Tools | `tools/` | Custom tools: vision, hCaptcha, terminal, RAG, skills |
| Browser | `utils/my_browser.py` | Chromium CDP lifecycle management |
| MCP | `utils/mcp_client.py` | Persistent @playwright/mcp session manager |
| Prompt | `prompt/system_prompt.py` | Agent system instructions |
| RAG | `rag/` | PGVector document retrieval and experience search |
| Context | `context/context_manager.py` | Message compression middleware |
| Frontend | `frontend/index.html` | Vue.js SPA, same-origin API |

## Running Tests

```bash
# Activate environment (conda or .venv)
source .venv/bin/activate   # or: conda activate langchainenv

# Key tests (fast, no external deps)
.venv/bin/python -m pytest test/test_rag_schema_init.py test/test_frontend_ui.py -q --tb=short

# Full test suite
.venv/bin/python -m pytest -q --tb=short
```

## Starting the Service

```bash
python run_server.py
# API at http://127.0.0.1:8801
# CDP at ws://127.0.0.1:9222
```

## Common Pitfalls

1. **conda not found**: The project supports `.venv` as fallback - use `./.venv/bin/python` instead.
2. **PostgreSQL required for RAG**: pgvector must be running on localhost:5432.
3. **DashScope key for embeddings**: RAG search/upload needs `DASHSCOPE_API_KEY` or OpenAI-compatible embeddings.
4. **Never modify network config**: Clash/Mihomo/Tailscale/SSH/DNS/firewall config must NOT be touched.
5. **AGENTS.md is authoritative**: Read it before making code changes.
6. **TDD preferred**: Write/update tests before changing production code.
7. **Small convergent changes**: No large refactors without explicit user request.

## Skills System

Skills are in `skills/<name>/SKILL.md`. Each has YAML frontmatter (name, description, version) and Markdown body.
- `utils/skills.py`: scanning, parsing, caching
- `tools/skill_tools.py`: list_skills and view_skill tools
- Configurable via `NAXUSSURF_SKILLS_DIR` env var
