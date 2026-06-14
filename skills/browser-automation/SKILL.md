---
name: browser-automation
description: "Browser interaction patterns: snapshot-ref model, tool selection, diff/transients reading, cross-origin iframes."
version: 1.0.0
tags: [browser, mcp, playwright, automation]
---

# Browser Automation Patterns

## Core Model

Daiboo uses `@playwright/mcp` in **snapshot-ref** mode:
- `browser_snapshot` returns a text tree with ref IDs like `@e5`, `@e12`
- refs are temporary — page change invalidates all old refs
- Always use the freshest snapshot before any click/type/fill

## Tool Selection Guide

| Scenario | Tool |
|----------|------|
| First visit / overall structure / page text | `web_observe` |
| Iframes or Shadow DOM | `web_observe` (snapshot can't see them) |
| Lists / feeds | `web_observe(text_only=True)` saves tokens |
| Need exact refs for click/type/fill_form | `browser_snapshot` |

`web_observe` strips floating ads, inlines cross-origin iframes, and keeps ~35k char budget — 50%+ fewer tokens than snapshot. Don't run both.

## Reading [diff] and [transients]

All state-changing tools (click, type, fill_form, navigate, press_key, select_option, hover, drag, handle_dialog, file_upload, evaluate, run_code) automatically append:

- `[diff] DOM变化量: N` or `[diff] 页面无明显变化`
- `[diff] 最显著变化: <html>...</html>`
- `[transients] [...]` — toast / error / loading text during the action

**How to read:**
- "页面无明显变化" + no transients → action probably didn't work
- transients contain error keywords (错误/失败/网络/重试) → action failed
- DOM变化量 > 5 → page changed, re-snapshot before next interaction

Always read [diff]/[transients] before deciding to re-snapshot.

## Cross-Origin Iframes

Elements inside cross-origin iframes are invisible to `browser_snapshot` and refs don't work.

**Workflow:**
1. Try `web_observe` first (same-origin iframes get inlined)
2. If invisible (cross-origin) → `browser_evaluate` to enter frame
3. If still stuck → declare "MCP path insufficient", don't retry outer refs

## Stubborn React/Vue Inputs

When `browser_type` fills the field but the form submits empty (state didn't update):

1. Don't repeat `browser_type` — it won't help
2. Use `browser_evaluate` to dispatch `input` + `change` events
3. Still failing → escalate to fallback level

## Tab Switching

Before switching tabs, always `browser_tabs` first. When multiple tabs have similar URLs/titles, select by exact tab ID, not keyword guessing.

## Escalation Ladder

1. Standard: `browser_snapshot` + click/type/fill_form, or `web_observe` + advanced MCP tools
2. Anti-bot sites: use trusted input tools (`browser_press_key`/`browser_type`), don't use `browser_evaluate` to fake click/keypress events
3. Cross-origin iframe/Shadow DOM: declare "MCP path insufficient"
4. Unsolvable captcha / OS-level native dialogs / anti-bot: stop immediately

**Rule:** same action fails 3 times → jump to next level immediately.
