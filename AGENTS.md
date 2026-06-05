# AGENTS.md

本文件只面向 AI coding agent，描述“如何安全、准确地改这个仓库”。
用户上手、安装、运行、接口说明请看 `README.md`。

## 1. 适用范围

- 适用于本仓库内所有代码与文档修改。
- 目标是降低错误修改、路径幻觉、过时说明复用。

## 2. 真实入口（修改前先核对）

- `main.py`: CLI 会话入口。
- `api.py`: FastAPI 服务入口（`/chat`、`/tools`、`/skills`、`/upload`）。
- `run_server.py`: 启动 API 并打开前端页面。

如需求影响入口行为，必须同步核对并更新相关说明。

## 3. 运行环境前置

- 在本仓库执行 Python、pytest、uvicorn、脚本前，先激活 conda 环境：`conda activate langchainenv`。
- 若当前终端不在 conda shell，先执行 conda 初始化后的 PowerShell 会话，再激活 `langchainenv`。
- 不要默认使用系统 Python 或 `base` 环境，除非用户明确要求。

## 4. 核心代码边界

- `utils/agent_factory.py`: agent 组装与中间件链。
- `utils/mcp_client.py`: MCP 持久会话管理（`create_persistent_mcp_session`），解决每次工具调用创建新 subprocess 的问题。
- `utils/my_browser.py`: 浏览器进程管理（启动、CDP 端口检测、清理），启动流程全异步。
- `context/context_manager.py`: 上下文压缩、归档、消息重写。
- `tools/`: 工具定义。当前包含：`capture_element_context_tool`、`vision_analysis_tool`、`delay_tool_call`、`terminal_tools`、`rag_tools`、`web_observe_tool`。浏览器原子操作工具由 MCP 会话动态加载，不在此目录。
- `tools/_simphtml/`: web_observe 工具与 diff middleware 的共享内部模块（`opthtml.js`、`find_main_list.js`、`observer.py`、`post_process.py`、`diff.py`），算法源自 GenericAgent (MIT)，详见 `docx/genericagent_investigation.md`。
- `rag/`: 检索与向量相关逻辑。
- `loggers/`: 记录、经验总结、diff 中间件（`diff_middleware.py` 给 MCP 写动作自动附 DOM diff + 瞬时文本）。
- `skills/`: Skills 技能目录。每个子目录包含一个 `SKILL.md`（YAML frontmatter + Markdown body）。加载逻辑在 `utils/skills.py`，Agent 工具在 `tools/skill_tools.py`。
- `utils/skills.py`: Skills 加载模块（扫描、YAML 解析、缓存、便捷格式化）。
- `tools/skill_tools.py`: Skills Agent 工具（`list_skills`、`view_skill`）。
- `frontend/index.html`: 单文件 Vue.js SPA，含 Chat / RAG / Tools / Skills 四个标签页。

仅在边界明确时修改，跨模块改动需检查调用链是否一致。

## 5. 强约束

- 先读代码再改文档，文档必须映射真实实现。
- 不把规划文档中的设计当作已实现能力。
- 不引入仓库中不存在的路径、模块或类名。
- 改动后不得破坏现有入口可运行性。
- 涉及消息重写时，必须保证 Human/AI 角色严格交替。

## 6. 变更同步规则

- 改接口行为：同步更新 `README.md` 的用法或接口说明。
- 改目录结构：同步更新本文件“真实入口/核心边界”。
- 改运行前置条件：同步更新 `README.md` 环境与排障章节。

## 7. 当前仓库已知事实（2026-03-11）

- 浏览器操作已迁移至 `@playwright/mcp` (snapshot-ref 模式)，通过 `utils/mcp_client.py` 管理持久 MCP 会话。
- 已废弃并删除的工具：`fill_text_tool`、`get_all_element_tool`、`get_page_img_tool`、`playwright_mcp_tool`。
- `context/context_manager.py` 存在且为生效中间件，支持旧消息压缩和字符硬阈值双触发。
- `context/state_manager.py`、`context/assembly_engine.py`、`context/dynamic_id/` 当前不存在。
- `docx/` 下内容主要是设计和过程文档，不等于运行时代码。
- `loggers/screen_logger.py` 仅保留文字日志，不再持有 ScreenshotHelper / CDP 连接。
- `ToolNode` 已全局修补 `_handle_tool_errors = True`，MCP 工具异常不会导致 Agent 直接崩溃。
- `README.md` 当前约定的 conda 环境名是 `langchainenv`。

## 7.1 当前仓库已知事实（2026-05-03 更新）

- 新增 `tools/web_observe_tool.py`（基于 GenericAgent simphtml 算法的 LLM-friendly 页面观察工具），与 `@playwright/mcp` 的 `browser_snapshot` 共存。
- 新增 `tools/_simphtml/` 内部模块（opthtml.js / find_main_list.js / observer.py / post_process.py / diff.py），不对外暴露。
- 新增 `loggers/diff_middleware.py`，给所有"会改页面状态"的 MCP 浏览器工具自动附 `[diff]` 与 `[transients]` 字段。挂在 `agent_factory` 的 middleware 链中、`delay_tool_call` 之前。
- `prompt/system_prompt.py` 已加入 4.5（web_observe 选择规则）、5.1-5.4（标签页/受控组件/跨域 iframe/diff 结果阅读）、9.1（工具降级阶梯）。
- 调研依据：`docx/genericagent_investigation.md`；落地计划：`docx/genericagent_improvement_plan.md`。

## 7.2 当前仓库已知事实（2026-05-07 更新）

- 新增 `tools/hcaptcha_solver_tool.py`，通过 hcaptcha-challenger 的 AgentV 封装 `solve_hcaptcha` 工具；`utils/agent_factory.py` 已把该工具加入 agent 工具集。
- hCaptcha 标准调用约束写入 `prompt/system_prompt.py`：调用 `solve_hcaptcha` 前不要先 `browser_click`，默认让工具以 `click_checkbox=True` 处理 checkbox 与 challenge 监听时序。
- 新增 `extensions/llm_adapter.py`，用于 GLM 响应归一化，覆盖多路径拖拽题的箭头串和 `draggable` 数组等返回形态。
- `utils/mcp_client.py` 启动 `@playwright/mcp` 时启用 `--caps=vision`，因此 `browser_mouse_*_xy` 等坐标类 MCP 工具可用。
- 新增 `utils/log_path.py` 统一生成带时间戳和 session 片段的归档文件名；`context/context_manager.py` 与 `loggers/screen_logger.py` 已改用 `thread_id` 作为 `session_id` 参与归档路径生成。
- 手动测试已归入 `test/manual/`；`test/manual/README.md` 记录 MCP smoke、VL 分析、middleware logging、Epic 登录和 hCaptcha demo 的手动用法。
- `test/manual/hcaptcha_demo_manual.py` 是 hCaptcha demo 联调脚本；`test/test_hcaptcha_solver_classification.py` 覆盖 hCaptcha 题型/响应归一化相关回归。
- `tmp/` 已加入 `.gitignore`，用于临时产物，不应作为稳定运行目录写入文档承诺。

## 7.3 当前仓库已知事实（2026-06 更新）

- 新增 Skills 技能系统：`skills/` 目录存放 `SKILL.md` 文件，`utils/skills.py` 扫描/解析/缓存，`tools/skill_tools.py` 提供 `list_skills` 和 `view_skill` 工具。
- Agent 系统提示词已加入第 9 节 Skills 使用规则；Agent 每次任务前应先 `list_skills`，有匹配时用 `view_skill(name)` 加载完整内容再执行。
- API 新增 `GET /skills`（列表）和 `GET /skills/{name}`（详情）端点。
- 前端新增 Skills 标签页：可查看技能列表、标签、版本，点击展开加载完整 Markdown 内容。
- Skills 目录可通过 `NAXUSSURF_SKILLS_DIR` 环境变量覆盖，默认 `skills/`。
- 当前已有一个示例技能：`naxussurf-dev`（NaxusSurf 项目架构与开发指南）。

## 7.4 当前仓库已知事实（2026-06-05 更新 — 结构化日志）

- 新增 `utils/logging.py`：基于 loguru 的统一日志配置。入口（`api.py`、`main.py`）在 `load_dotenv()` 后调用 `setup_logging()` 初始化。
- 两种输出模式，通过 `LOG_FORMAT` 环境变量切换：
  - `pretty`（默认）：开发用，带颜色，含时间/级别/模块:函数:行号/消息。
  - `json`：生产用，`serialize=True`，每行一个 JSON 对象（含 `record.message`、`record.extra`、`record.level` 等）。
- 级别控制：`LOG_LEVEL`（debug/info/warning/error，默认 info）。
- 文件输出：`LOG_FILE`（可选日志文件路径）。
- **规则**：生产模块（`api.py`、`loggers/`、`utils/my_browser.py` 等）统一使用 `from loguru import logger`，不再使用裸 `print()`。CLI 入口 `main.py` 的用户界面消息保留 `print()`，内部错误用 `logger.error()`。
- `api.py` 已加入 HTTP 请求日志中间件（`method`/`path`/`status_code` 绑定到 `extra`）。
- 测试参见 `test/test_logging.py`。

## 8. 执行偏好

- 小步修改，优先最小可验证变更。
- 每次修改后至少做一次本地一致性检查（路径、导入、文档引用）。
- 避免在不相关文件做顺手重构。
