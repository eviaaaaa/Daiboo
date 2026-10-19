# Manual Test Scripts

这个目录放不会参与默认 `pytest` 收集的手工联调脚本。

约定：

- 需要真实浏览器、真实账号、数据库、副作用或人工观察的脚本放这里。
- 目录已被 `pytest.ini` 的 `norecursedirs` 排除，执行 `pytest` 时不会自动跑。
- 运行仓库脚本使用 `uv run python ...`，环境以仓库 `uv.lock` 为准。

示例：

```bash
uv run python test/manual/epic_login_manual.py
```

## 脚本清单

- `browser_runtime_smoke.py`：不调用模型的真实隔离 Chromium/CDP + 持久 Playwright MCP 测试；覆盖表单、SPA 事件、快照范围、预算、失败进度与业务结果回读。随机回环端口、临时 profile，结束清理自己创建的进程。
- `openai_browser_smoke.py`：显式 opt-in 的真实 OpenAI Responses SSE / 原生图像 / 工具调用与隔离表单验收。需要 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`，不会发现私有凭据或自动更换供应商。`--graph` 使用产品 factory/middleware；不加时测受限工具循环。`--browser-only` 避免重复图像/协议请求；`--report PATH` 写不含凭据/推理正文的 JSON。

  ```bash
  uv run python test/manual/browser_runtime_smoke.py
  # 会产生真实供应商请求；仅使用已获授权的 endpoint/model。
  uv run python test/manual/openai_browser_smoke.py --graph --report browser-acceptance.json
  ```

真实模型通过不代表付款、登录、验证码或跨域框架页面已测试；本地确定性 embedding 也不证明语义检索质量。完整边界见 `docs/browser-runtime.md`。

- `jev_browser_smoke.py`：显式 `--live` 才调用独立 TypeSafe 服务。需 `DAIBOO_JEV_ENABLED=true`、`TYPESAFE_API_KEY`；默认验证原生 noul/choice/score 与隔离表单。`--graph` 使用实际主模型 factory/middleware（额外需要 OpenAI 环境配置，包含 handoff 后只完成剩余步骤）；`--public --skip-local --trials 3` 单独测试公开 TodoMVC React，由独立 Playwright DOM 核对结果。该 demo 数据只在页面内存，不能用刷新验证持久化。当前按有效分布最高项选择，不再设概率/confidence 门槛；最高项若为 handoff/observe_again 仍交回。未达到独立成功条件时脚本返回非零，保留所有失败。耗时是工具循环端到端时间，没有整 agent 提速基线；文档中的旧阈值 0/3 是历史结果，不代表当前策略。

  ```bash
  # 需先在服务端配置授权凭据；会产生真实 TypeSafe / 主模型请求。
  uv run python test/manual/jev_browser_smoke.py --live --graph --report jev-acceptance.json
  uv run python test/manual/jev_browser_smoke.py --live --public --skip-local --trials 3 --report jev-public.json
  # 以下只用假推理 + 真实隔离 Chromium/MCP，不消费模型额度。
  DAIBOO_TEST_JEV_BROWSER_LIVE=1 uv run python -m pytest test/test_jev_browser.py test/test_jev_dispatch_safety.py
  ```

- `epic_login_manual.py`：Epic Games 登录联调，验证基础登录链路。
- `hcaptcha_demo_manual.py`：在 hCaptcha 官方演示站
  <https://accounts.hcaptcha.com/demo> 上测 agent 的「先 ref、后观察 challenge、
  最后正确声明边界」能力。脚本内置四档 prompt（v1 最少引导 / v2 两阶段提示 /
  v3 详细策略 / v4 调用 solve_hcaptcha 工具），避免模型乱用虚构工具名或误走 terminal 工具。

  ```bash
  uv run python test/manual/hcaptcha_demo_manual.py --prompt v3 --recursion 120
  uv run python test/manual/hcaptcha_demo_manual.py --prompt v1 --show-prompt-only
  ```

## 依赖与环境变量

`hcaptcha_demo_manual.py --prompt v4` 依赖 `solve_hcaptcha` 工具，需要先安装：

```bash
uv sync --locked --group dev
```

> `loguru` 是 `extensions/llm_adapter.py` 的运行时依赖；`google.genai` 会随
> `hcaptcha-challenger` 一起装上。

LLM provider 二选一在 `.env` 配置：

**A. 走 GLM / Z.ai 兼容接口（推荐）**

```
LLM_PROVIDER=glm
GLM_API_KEY=...
GLM_BASE_URL=https://api.z.ai/api/paas/v4
GLM_MODEL=glm-4.6v
```

`solve_hcaptcha` 内部会先 `apply_llm_patch()`，monkey-patch `google.genai.Client`
到 `extensions/llm_adapter.py::GLMCompatibleGenAIClient`，所有请求改走 GLM endpoint。
hcaptcha-challenger 内部仍会校验 `GEMINI_API_KEY` 字段非空——工具会自动拿 GLM key 占位，
真实流量已被 patch 接管。

**B. 走 Gemini（境外环境直连）**

```
GEMINI_API_KEY=...
```

无任何 key 时 `solve_hcaptcha` 立即返回 `status=error / code=missing_*_api_key`，
不要重试；此时退回 v1/v2/v3 prompt，观察 agent 是否能正确声明边界。
