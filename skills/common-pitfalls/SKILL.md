---
name: common-pitfalls
description: "Common agent mistakes and recovery patterns: ref reuse, stale state, tool confusion, error loops."
version: 1.0.0
tags: [pitfalls, debugging, recovery, errors]
---

# Common Pitfalls & Recovery

## 1. Stale Ref Reuse

**Symptom:** `browser_click(@e5)` returns an error about invalid ref.

**Cause:** Ref was from an old snapshot. Page changed (navigation, dynamic load, tab switch).

**Fix:** Run `browser_snapshot` to get fresh refs. Never cache or reuse refs.

## 2. Running Both web_observe AND browser_snapshot

**Symptom:** Wasted tokens, extra round trips.

**Fix:** Pick one based on the scenario (see browser-automation skill). After `web_observe`, don't immediately `browser_snapshot` unless you need exact refs for interaction.

## 3. Ignoring [diff]/[transients]

**Symptom:** Action appeared to succeed but next step fails because page didn't actually change.

**Fix:** Always read `[diff]` and `[transients]` after every state-changing action. If "页面无明显变化", the action probably had no effect.

## 4. Repeating Failed Actions

**Symptom:** Same tool call fails 4, 5, 6 times.

**Fix:** After 3 consecutive failures, escalate per the fallback ladder. Don't retry indefinitely.

## 5. Forgetting list_skills / view_skill

**Symptom:** Solving a problem from scratch when a skill already covers it.

**Fix:** Always call `list_skills` at the start of a task. If a matching skill exists, `view_skill(name)` before executing.

## 6. Blaming External APIs for Local Config Issues

**Symptom:** Attribute `search_documents` failure to "API down" when it's a local PostgreSQL/pgvector issue.

**Fix:** Check:
- Is PostgreSQL running? (`pg_isready`)
- Is the `vector` extension enabled? (`CREATE EXTENSION IF NOT EXISTS vector`)
- Are DB credentials in `.env` correct?
- For embedding failures: is `DASHSCOPE_API_KEY` set, or is `DAIBOO_LOCAL_EMBEDDINGS=1` for offline testing?

## 7. Tab Confusion

**Symptom:** Operating on the wrong tab after multiple `browser_navigate` calls.

**Fix:** Always `browser_tabs` before switching. Select by exact tab ID, not fuzzy URL matching.

## 8. Modal / Dialog Blocking Interactions

**Symptom:** Clicks/inputs have no effect because a modal is open.

**Fix:** Check `web_observe` output for modal/dialog elements. Use `browser_handle_dialog` if a native alert/confirm/prompt is blocking.

## 9. Forgetting Agent Has Terminal Tools

**Symptom:** Describing what you would check instead of actually checking.

**Fix:** The agent has `terminal_read` and `terminal_write` (with HITL approval). Use them to verify system state, check logs, run diagnostic commands.

## 10. Missing Skills Directory

**Symptom:** `list_skills` returns "No skills available" despite `skills/` directory existing.

**Fix:** Each skill needs a subdirectory with a `SKILL.md` inside. Not a single file in `skills/` root. Format: `skills/<name>/SKILL.md`.

## Quick Recovery Checklist

1. `browser_snapshot` — get fresh state
2. `web_observe` — understand page content and structure
3. `list_skills` — find relevant procedural knowledge
4. Check `[diff]` / `[transients]` of last action
5. If stuck 3+ times on same action → escalate
