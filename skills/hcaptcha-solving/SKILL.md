---
name: hcaptcha-solving
description: "hCaptcha solving workflow: timing, solver tool usage, post-verification, and fallback."
version: 1.0.0
tags: [captcha, hcaptcha, solver, browser]
---

# hCaptcha Solving

## Tool

`solve_hcaptcha` — wraps hcaptcha-challenger AgentV. Handles cross-iframe positioning, multimodal recognition, Bezier-trajectory clicks, and multi-round challenges.

## Critical Timing (DO NOT VIOLATE)

**Never click the hCaptcha checkbox before calling `solve_hcaptcha`.**

The solver must register `/getcaptcha/` response listeners **before** the checkbox is clicked. Pre-clicking the checkbox externally makes the listener miss the challenge payload, falling back to unreliable visual-only solving.

## Standard Call

```python
solve_hcaptcha(click_checkbox=True)
```

- This is the default and correct way.
- The tool internally uses robotic_arm with Bezier trajectories to click.
- After the call completes, the tool's internal reload fallback handles edge cases — don't trigger it manually.

## Options

| Param | When |
|-------|------|
| `click_checkbox=True` | Default — always use this |
| `click_checkbox=False` | ONLY when you're certain hCaptcha hasn't issued `/getcaptcha/` yet — almost never needed |
| `target_url_hint="hcaptcha.com/demo"` | Multiple tabs, disambiguate |
| `ignore_questions=[...]` | Skip unsolvable question types (e.g. drag-to-line) |

## Post-Verification (MANDATORY)

**`status=ok` does NOT mean hCaptcha passed.**

After `solve_hcaptcha` returns, you MUST verify:
1. Green checkmark visible on the page
2. `name="h-captcha-response"` input field has non-empty value
3. Page content changed (challenge panel gone)

Use `web_observe` or `browser_snapshot` to verify. Only then submit the form.

## Error Handling

| Return | Meaning | Action |
|--------|---------|--------|
| `status=error, missing_*_api_key` | GLM_API_KEY or GEMINI_API_KEY not set | Stop immediately, don't retry |
| `status=error, CDP connection failed` | Browser/CDP issue | Stop, don't retry |
| `status=fail, unsupported question type` | Drag-to-line etc. | Try `ignore_questions` or escalate |

## Static Captcha Alternative

For same-origin static captchas (image is in the main document):
1. `capture_element_context` → local image path
2. `vl_analysis_tool` → text recognition
3. `browser_type` → fill answer
