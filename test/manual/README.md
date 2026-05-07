# Manual Test Scripts

这个目录放不会参与默认 `pytest` 收集的手工联调脚本。

约定：

- 需要真实浏览器、真实账号、数据库、副作用或人工观察的脚本放这里。
- 目录已被 `pytest.ini` 的 `norecursedirs` 排除，执行 `pytest` 时不会自动跑。
- 运行仓库脚本前先切到 `conda activate langchainenv`。

示例：

```powershell
conda run -n langchainenv python test/manual/epic_login_manual.py
```

## 脚本清单

- `epic_login_manual.py`：Epic Games 登录联调，验证基础登录链路。
- `hcaptcha_demo_manual.py`：在 hCaptcha 官方演示站
  <https://accounts.hcaptcha.com/demo> 上测 agent 的「先 ref、后观察 challenge、
  最后正确声明边界」能力。脚本内置四档 prompt（v1 最少引导 / v2 两阶段提示 /
  v3 详细策略 / v4 调用 solve_hcaptcha 工具），避免模型乱用虚构工具名或误走 terminal 工具。

  ```powershell
  conda run -n langchainenv python test/manual/hcaptcha_demo_manual.py --prompt v3 --recursion 120
  conda run -n langchainenv python test/manual/hcaptcha_demo_manual.py --prompt v1 --show-prompt-only
  ```

## 依赖与环境变量

`hcaptcha_demo_manual.py --prompt v4` 依赖 `solve_hcaptcha` 工具，需要先安装：

```powershell
conda activate langchainenv
pip install hcaptcha-challenger loguru
```

> `loguru` 是 `extensions/llm_adapter.py` 的运行时依赖；`google.genai` 会随
> `hcaptcha-challenger` 一起装上。

LLM provider 二选一在 `.env` 配置：

**A. 走 GLM（推荐，BigModel 免费额度够用）**

```
LLM_PROVIDER=glm
GLM_API_KEY=...
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
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
