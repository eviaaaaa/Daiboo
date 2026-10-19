# Daiboo（代步）

面向复杂网页任务的智能浏览器代理框架，基于 LLM + Playwright MCP 执行浏览器操作，并结合上下文压缩、人工审批、文档检索与任务经验复用能力。

## 项目简介

Daiboo（代步）通过 **@playwright/mcp** + LangChain/LangGraph 组合，实现可交互的 Web Agent。它不是只执行固定脚本的浏览器自动化工具，而是把浏览器操作、视觉分析、终端读写、文档检索和经验检索放入统一的 Agent 工具链中，由模型按任务目标动态编排。浏览器操作通过 MCP (Model Context Protocol) 以 snapshot-ref 模式驱动，并使用持久会话保持跨工具调用的页面状态。

- 支持自然语言驱动浏览器与辅助工具协同执行，MCP 已启用 vision 能力，可使用坐标类鼠标工具处理拖拽等场景。
- 支持文档上传索引、文档检索和任务经验复用。
- 支持 hCaptcha 专用求解工具（基于 hcaptcha-challenger），用于合法测试页或授权场景下的验证能力联调。
- 前端内置 RAG 工作台，可直接查看命中的相关 chunk，并对比大块、小块、层级聚合三种检索效果。
- 支持 CLI 模式和 FastAPI + 前端模式。
- Web 前端支持聊天历史持久化、回溯加载与删除会话；历史默认保存在 `data/chat_history.json`。

## 核心能力

- 浏览器自动化：通过 @playwright/mcp 连接 CDP 端点，提供页面导航、元素快照交互、信息提取等能力。
- 模型推理编排：统一调度浏览器工具、视觉分析、终端工具与检索工具，支持多轮会话和可中断审批（HITL 中间件）。
- 上下文管理：长上下文压缩（旧消息摘要 + 字符硬阈值双触发）、归档和重放辅助。
- 浏览器动作追踪：对会改页面状态的 MCP 工具自动补充 DOM diff 与瞬时文本，减少额外 snapshot 验证轮次。
- 可选 Jev 快速判断：独立 TypeSafe System One API 提供只读 noul/choice/score，以及受限候选动作循环；主聊天模型不变，默认关闭。
- 检索与记忆：基于 PostgreSQL + PGVector 的文档检索与任务经验沉淀。

## 运行前准备

### 1. 环境要求

- Python 3.11–3.13（推荐 3.11；当前锁中的 spaCy 尚无 Python 3.14 wheel）
- Node.js 18+（建议 20+，用于运行 @playwright/mcp）
- PostgreSQL 14+
- 已启用 `vector` 扩展（PGVector）
- Redis 7+（可选；未配置时自动回退，不影响核心功能）

### 2. 安装依赖

推荐使用 uv（快，锁定版本）：

```bash
uv sync --locked --group dev --python 3.11
uv run playwright install chromium
```

或使用传统 pip：

```powershell
conda create -n langchainenv python=3.11 -y
conda activate langchainenv
pip install -r requirements.txt
playwright install
```

Playwright MCP 由 `npx` 按已验证版本启动，无需全局安装。可先验证 Node/npm 链路：

```bash
npx --yes @playwright/mcp@0.0.83 --version
```

### 3. 配置环境变量

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

请至少填写 `.env` 中以下配置：

- 主聊天模型二选一：
  - OpenAI 兼容接口：`OPENAI_API_KEY` **及显式的 `OPENAI_MODEL`**，可选 `OPENAI_BASE_URL`。`OPENAI_API_MODE=responses|chat_completions` 明确选择协议，`OPENAI_STREAMING=true` 开启原生 SSE。新模型工具调用是否需要 Responses，以官方与实际接口为准，不按名字猜测。
  - DashScope 兼容路径：`DASHSCOPE_API_KEY`（当 `OPENAI_API_KEY` 留空时自动回退）
- hCaptcha 求解二选一：
  - GLM 路径：`LLM_PROVIDER=glm`、`GLM_API_KEY`，可选 `GLM_BASE_URL`、`GLM_MODEL`
  - Gemini 路径：`GEMINI_API_KEY`
- RAG/文档上传功能需要 PostgreSQL + PGVector：`DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`
- 浏览器控制：`BROWSER_PATH`、`USER_DATA_DIR`、`DEBUGGING_PORT`、`BROWSER_HEADLESS=auto|true|false`。Linux 的 `auto` 会先正常启动，CDP 未就绪时自动用 `--headless=new` 重试一次。
- MCP：`PLAYWRIGHT_MCP_VERSION`（默认固定为已验证的 `0.0.83`）、`NPX_COMMAND`（可选自定义 npx 路径）；`PLAYWRIGHT_MCP_CAPS=vision` 可改为 `vision,pdf,devtools` 或 `none`。`DAIBOO_BROWSER_SNAPSHOT_MODE=none` 默认只在显式观察时返回快照，可设 `full` 恢复自动快照。
- OpenAI 参数：可选 `OPENAI_REASONING_EFFORT`、`OPENAI_REASONING_SUMMARY`（仅 Responses）、`OPENAI_VERBOSITY`、`OPENAI_SERVICE_TIER`、`OPENAI_MAX_OUTPUT_TOKENS`、`OPENAI_TEMPERATURE`。未设置温度时不强制发送；不替供应商伪造参数兼容性。`OPENAI_USE_RESPONSES_API` 为旧布尔别名，不能与协议配置冲突。Responses 保留推理/函数调用原生内容块，`normalize_content` 只用于显示，不用于历史回放。经验总结复用已配置的主模型供应商。
- 浏览器节奏：默认使用 Playwright auto-wait，不再每个动作固定等 500ms；老站可用 `BROWSER_ACTION_DELAY_MS=0..10000` 显式增加等待。
- Web 服务可选项：`HOST`（默认 `127.0.0.1`）、`PORT`（默认 `8801`，范围 `1..65535`）、`UPLOAD_DIR`（默认 `temp_uploads/`）、`UPLOAD_MAX_MB`（默认 20）。上传只接受 `.pdf/.doc/.docx/.md/.txt`，临时文件在索引结束或失败后都会删除。

可选增强（不配置不影响运行）：

- Jev：显式设置 `DAIBOO_JEV_ENABLED=true` 和服务端 `TYPESAFE_API_KEY`；`TYPESAFE_BASE_URL` 默认 `https://api.typesafe.ai/v1`，`TYPESAFE_MODEL` 默认 `jev-latest`，`TYPESAFE_TIMEOUT_SECONDS` 默认 10 秒、上限 60 秒。启用且会话具备安全 backend 时注册 `browser_jev_decide` / `browser_jev_run`，客户端随 MCP 会话关闭；未启用不会读取该密钥。`browser_runtime_info` 可确认实际注册及完整 schema，但 `configured=true` 不等于探测过端点。页面文本会发送给独立 TypeSafe 服务，使用其独立额度，不走 `OPENAI_*` / NewAPI / CPA 的订阅路径；不要上传秘密或把启发式脱敏当 DLP。完整用法与边界见 [浏览器运行时](docs/browser-runtime.md#可选-typesafe-jev)。
- API 安全：`DAIBOO_API_KEY`（设置即启用 X-API-Key 认证）、`RATE_LIMIT`（默认 60 req/60s，设 0 关闭）。Web 前端可从“安全”面板输入 Key，只写入当前标签页的 `sessionStorage`。
- Redis 缓存：`REDIS_URL`；可按需调整 `REDIS_RAG_SEARCH_TTL`（默认 300 秒）、`REDIS_RAG_SUMMARY_TTL`（默认 60 秒）、`REDIS_EMBEDDING_TTL`（默认 86400 秒）。Redis 故障会自动按 cache miss 回退，不会阻断请求。
- 跨域：默认关闭 CORS；确需跨域时用 `CORS_ALLOW_ORIGINS=https://a.example,https://b.example` 显式配置来源。
- 终端工具：`TERMINAL_TIMEOUT_SECONDS`（默认 30）、`TERMINAL_MAX_OUTPUT_CHARS`（默认 20000）。Windows 优先 `pwsh`/`powershell`，Linux/macOS 优先 `bash`/`sh`，结果包含退出码。
- 日志：`LOG_LEVEL`（debug/info/warning/error，默认 info）、`LOG_FORMAT`（pretty/json）
- Skills 目录：`DAIBOO_SKILLS_DIR`（默认 `skills/`）
- 会话持久化：`DAIBOO_CHECKPOINT_DIR`（SQLite checkpoint，默认 `data/`）
- 聊天历史文件：`DAIBOO_CHAT_HISTORY_FILE`（默认 `DAIBOO_CHECKPOINT_DIR/chat_history.json`）
- 演示模式：`DAIBOO_DEMO_MODE=1` 时 `/chat` 返回固定演示事件，不实际调用 Agent

运行时数据默认不入 Git：`.env`、`.public-auth`、`data/`、`storage/`、`screen/`、`temp_uploads/` 等均已被 `.gitignore` 忽略；不要把本地认证文件、checkpoint 数据库或聊天历史提交到 Git。上下文与最终日志旁的同名 JSON sidecar 用于原生消息回放，包含 typed blocks、调用关联及元数据，按 `0600` 权限保存；它与仅供显示的文本日志用途不同，仍应视作敏感运行时数据。

详见 `.env.example` 中注释。

### 4. 启用 Redis 缓存（可选）

项目提供只绑定回环地址的缓存容器：

```bash
docker compose -f compose.redis.yml up -d
```

随后在 `.env` 中设置：

```dotenv
REDIS_URL=redis://127.0.0.1:6380/0
```

当前缓存边界刻意保持保守：缓存 Agent 文档检索、RAG 调试检索、RAG 语料概览和查询 Embedding；浏览器操作、流式聊天和上传写入不会缓存。文档成功写入后通过 Redis namespace generation 立即失效所有 RAG 结果，不使用全库 `SCAN`。`GET /health` 的 `cache_configured` / `cache_available` 可用于观察实际状态。

服务启动时会幂等确保实际生产查询需要的索引：`rag_documents.embedding` 上与 `chunk_level='child'` 查询条件一致的部分 HNSW 索引。已有 GIN 全文索引和父子块 B-tree 索引继续保留；当前数据量很小的 AgentTrace、Experience 以及仅用于调试的 parent 检索不额外堆索引。

## 启动方式

### 1. Web 服务模式（推荐）

```bash
# 直接启动
python run_server.py

# 或用 uv run（自动激活 venv + 安装缺失依赖）
uv run daiboo-serve
```

启动后：

- API 默认监听 `http://127.0.0.1:8801`（可用 `.env` 里的 `HOST` / `PORT` 覆盖）
- `run_server.py` 会自动打开 `frontend/index.html`

### 2. CLI 模式

```bash
python main.py

# 或
uv run daiboo
```

支持命令：

- `new` / `reset`：新建会话
- `exit` / `quit`：退出

## 工具集

完整执行工具集分为以下两类；模型请求初始只披露六个核心浏览器工具（导航、快照、标签页、批次、能力查询、页面观察）及既有非浏览器工具。调用 `browser_runtime_info(tool_names=[...])` 成功后，才按需追加对应的原生 schema；`GET /tools` 返回的是完整公开工具集，不是每轮模型请求的工具列表。

**MCP 浏览器原子工具**（由 `@playwright/mcp` 动态加载）：`browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type` / `browser_fill_form` / `browser_press_key` / `browser_select_option` / `browser_tabs` / `browser_evaluate` / `browser_file_upload` / `browser_take_screenshot` / `browser_wait_for` 等。MCP 启动参数包含 `--caps=vision`，运行时还会暴露 `browser_mouse_*_xy` 等坐标类工具。详细列表运行时通过 `GET /tools` 查询。

**本仓库自定义工具**（在 `tools/` 下）：

- `list_skills` / `view_skill`：名称与描述目录在创建 Agent 时固定提供，正文按需用 `view_skill(name)` 加载；只有缺少目录或需要刷新时才调用 `list_skills`，普通问答不额外查询。
- `browser_batch`：最多 12 个已观察目标上的顺序填表、点击、等待、限额读取与文本断言，一次持久 MCP 调用；部分失败返回已完成步数，不自动重试或回滚。`verified` 只代表显式文本断言，重要外部操作仍需独立复核。
- `browser_runtime_info`：披露当前会话的实际能力、工具名及指定工具的 schema，不按模型名假定支持。
- 同一 MCP 会话的批次、原子操作与 diff 临界区共用执行门，不并发穿插浏览器动作。批次在导航、同 URL 重载、文档替换或新窗口后停止；错误仅返回固定分类，不附可能带出敏感 DOM 值的原始 Playwright call log。
- `web_observe`：基于 simphtml 的 LLM-friendly 页面观察。可内联**同源 iframe 与开放 Shadow DOM**，文本/HTML 均有硬字符预算（默认 35000）；密码值不写入简化 DOM。与 `browser_snapshot` 共存，不绕过同源策略。
  - `text_only=True`：纯文本输出，最省 token，适合"快速看页面写了啥"
  - `text_only=False`（默认）：简化 HTML 输出，保留结构便于后续 `browser_snapshot` 拿 ref 操作
- `capture_element_context`：截取目标元素及周围上下文的截图，返回本地路径。
- `vl_analysis_tool`：视觉模型分析图片（验证码、图表等）。
- `solve_hcaptcha`：基于 hcaptcha-challenger 在当前 CDP 浏览器页上处理 hCaptcha。调用前不要先点 hCaptcha checkbox，默认让工具以 `click_checkbox=True` 负责 checkbox 与 challenge 监听时序；工具成功返回后仍需用 `web_observe` 或 `browser_snapshot` 复核页面状态。
- `terminal_read` / `terminal_write`：跨平台终端读写操作（带 HITL 审批、执行超时、输出上限和退出码）。
- `search_documents` / `search_task_experience`：RAG 检索（文档 / 历史经验）。

**自动加在工具结果末尾的 diff 与 transients**：所有"会改页面状态"的 MCP 浏览器工具（click/type/navigate/...）调用结束后，工具返回末尾会自动追加：
- `[diff] DOM 变化量: N` / `[diff] 页面无明显变化`
- `[diff] 最显著变化: <html>...</html>`
- `[transients] [...]`：动作期间出现的瞬时文本（toast / 错误提示 / loading）

由 `loggers/diff_middleware.py` 实现，属于 best-effort 变化线索，不是业务成功证据；批次直接返回精准读取/断言，避免整页 diff 的额外往返。

原生 `browser_run_code` / `browser_run_code_unsafe` 默认不向模型暴露；只有明确理解风险时才设 `DAIBOO_BROWSER_ALLOW_UNSAFE_CODE=true`。固定代码批次不是授权或安全沙箱，页面、网页工具及结果均不可信。密码、OTP、银行卡及未经授权的发信/付款/发布/删除不可通过批次绕过批准。框架保留终端 HITL；提示词规则不是完整的浏览器权限系统。

最新技术取舍、Jev 的准确定位、实测方法与边界见 [浏览器运行时设计与验收](docs/browser-runtime.md)。

## API 快速说明

- `POST /chat`：发送消息并流式返回执行结果，同时按 `thread_id` 写入聊天历史
- `GET /chat/sessions`：列出已保存的聊天会话概要，用于前端历史栏
- `GET /chat/sessions/{thread_id}`：读取指定会话的完整消息，前端可切回旧 `thread_id` 继续回溯上下文
- `DELETE /chat/sessions/{thread_id}`：删除指定聊天历史记录（不清理 LangGraph checkpoint）
- `GET /tools`：列出可用工具
- `GET /skills`：列出所有可用 Skills（名称、描述、版本、标签）
- `GET /skills/{name}`：加载指定 Skill 完整内容
- `POST /upload`：上传 PDF、DOC、DOCX、Markdown、TXT 文档并写入向量库；受 `UPLOAD_MAX_MB` 限制，无法生成 chunk 时返回 422，响应不会暴露服务端临时绝对路径
- `POST /rag/search`：调试 RAG 检索，返回大块、小块和层级聚合结果，以及相关 chunk 明细
- `GET /rag/summary`：获取当前 RAG 语料概览，包括文档数、父子块数量和旧数据数量

## 测试

```bash
# 使用 uv（自动激活 venv）
uv run python -m pytest

# 或直接
pytest
```

示例：

```powershell
uv run python -m pytest test/test_context_compression.py -v -s
uv run python -m pytest test/test_hcaptcha_solver_classification.py -v
```

手工联调脚本放在 `test/manual/`，不会被默认 `pytest` 收集。常用命令：

```powershell
uv run python test/manual/epic_login_manual.py
uv run python test/manual/hcaptcha_demo_manual.py --prompt v4 --recursion 120
uv run python test/manual/browser_runtime_smoke.py
# 以下产生真实模型请求，先配置授权的 OPENAI_*；不自动切换供应商。
uv run python test/manual/openai_browser_smoke.py --graph --report browser-acceptance.json
```

其中 hCaptcha demo 只面向官方演示站和授权测试场景；`--prompt v4` 会调用 `solve_hcaptcha`，需要已配置 GLM 或 Gemini 相关环境变量。

## 常见问题

- `ModuleNotFoundError`：检查是否激活虚拟环境并已安装依赖。
- 数据库报错 `extension "vector" does not exist`：在目标数据库执行 `CREATE EXTENSION IF NOT EXISTS vector;`。
- MCP 连接失败 / `npx` 找不到：确认 Node.js 已安装且 `npx --yes @playwright/mcp@0.0.83 --version` 可运行；如需切换已验证版本或命令路径，设置 `PLAYWRIGHT_MCP_VERSION` / `NPX_COMMAND`。
- 浏览器未启动 / CDP 连接被拒绝：检查 `.env` 中 `BROWSER_PATH`、`DEBUGGING_PORT` 和 `BROWSER_HEADLESS`。启动器会访问 `/json/version` 验证真实 CDP；Linux `auto` 模式在首次失败后自动用 `--headless=new` 重试。
- `PORT must be an integer between 1 and 65535`：检查 `.env` 中 `PORT` 是否为空、非数字或超出端口范围。
- `solve_hcaptcha` 返回 `missing_*_api_key`：检查 `.env` 是否配置 `LLM_PROVIDER=glm + GLM_API_KEY`，或配置可直连的 `GEMINI_API_KEY`。

## 技能系统 (Skills)

Skills 是预置的专项知识模块，Agent 按需加载。每个 Skill 是一个 `skills/<name>/SKILL.md` 文件，包含 YAML frontmatter 和 Markdown 正文。

### 添加新 Skill

在 `skills/` 下创建子目录，放入 `SKILL.md`：

```markdown
---
name: my-skill
description: "技能描述"
version: 1.0.0
tags: [tag1, tag2]
---

# 技能内容

详细步骤、命令、陷阱等...
```

Skills 目录可通过环境变量 `DAIBOO_SKILLS_DIR` 覆盖（默认 `skills/`）。

服务启动后自动扫描；前端 Skills 页面可查看列表和详情；Agent 在对话中通过 `list_skills` → `view_skill(name)` 加载。

## 文档分工

- `README.md`：面向人类开发者与使用者，负责上手与运行说明。
- `AGENTS.md`：面向 AI coding agent，负责修改约束、边界和维护规则。

## 许可证

本项目采用 [MIT License](LICENSE)。
