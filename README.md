# NexusSurf

面向复杂网页任务的智能浏览器代理框架，基于 LLM + Playwright MCP 执行浏览器操作，并结合上下文压缩、人工审批、文档检索与任务经验复用能力。

## 项目简介

NexusSurf 通过 **@playwright/mcp** + LangChain/LangGraph 组合，实现可交互的 Web Agent。它不是只执行固定脚本的浏览器自动化工具，而是把浏览器操作、视觉分析、终端读写、文档检索和经验检索放入统一的 Agent 工具链中，由模型按任务目标动态编排。浏览器操作通过 MCP (Model Context Protocol) 以 snapshot-ref 模式驱动，并使用持久会话保持跨工具调用的页面状态。

- 支持自然语言驱动浏览器与辅助工具协同执行。
- 支持文档上传索引、文档检索和任务经验复用。
- 前端内置 RAG 工作台，可直接查看命中的相关 chunk，并对比大块、小块、层级聚合三种检索效果。
- 支持 CLI 模式和 FastAPI + 前端模式。

## 核心能力

- 浏览器自动化：通过 @playwright/mcp 连接 CDP 端点，提供页面导航、元素快照交互、信息提取等能力。
- 模型推理编排：统一调度浏览器工具、视觉分析、终端工具与检索工具，支持多轮会话和可中断审批（HITL 中间件）。
- 上下文管理：长上下文压缩（旧消息摘要 + 字符硬阈值双触发）、归档和重放辅助。
- 检索与记忆：基于 PostgreSQL + PGVector 的文档检索与任务经验沉淀。

## 运行前准备

### 1. 环境要求

- Python 3.10+
- Node.js 16+（用于运行 @playwright/mcp）
- PostgreSQL 14+
- 已启用 `vector` 扩展（PGVector）

### 2. 安装依赖

推荐安装方式：

```powershell
conda create -n langchainenv python=3.11 -y
conda activate langchainenv
pip install -r requirements.txt
playwright install
```

还需安装 Node.js 依赖（Playwright MCP 服务通过 npx 启动）：

```powershell
npm install -g @playwright/mcp
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

- `DASHSCOPE_API_KEY`
- `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`
- `BROWSER_PATH`、`USER_DATA_DIR`、`DEBUGGING_PORT`

## 启动方式

### 1. Web 服务模式（推荐）

```powershell
python run_server.py
```

启动后：

- API 默认监听 `http://localhost:8801`
- 会自动打开 `frontend/index.html`

### 2. CLI 模式

```powershell
python main.py
```

支持命令：

- `new` / `reset`：新建会话
- `exit` / `quit`：退出

## 工具集

Agent 在每次对话中可见的工具分两类：

**MCP 浏览器原子工具**（由 `@playwright/mcp` 动态加载）：`browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type` / `browser_fill_form` / `browser_press_key` / `browser_select_option` / `browser_tabs` / `browser_evaluate` / `browser_file_upload` / `browser_take_screenshot` / `browser_wait_for` 等。详细列表运行时通过 `GET /tools` 查询。

**本仓库自定义工具**（在 `tools/` 下）：

- `web_observe`：基于 simphtml 的 LLM-friendly 页面观察。**跨 iframe 与 Shadow DOM 内容内联**、自动剔除浮窗广告、字符预算可控（默认 35000）、表单当前值落入属性。与 `browser_snapshot` 共存，不替换。
  - `text_only=True`：纯文本输出，最省 token，适合"快速看页面写了啥"
  - `text_only=False`（默认）：简化 HTML 输出，保留结构便于后续 `browser_snapshot` 拿 ref 操作
- `capture_element_context`：截取目标元素及周围上下文的截图，返回本地路径。
- `vl_analysis_tool`：视觉模型分析图片（验证码、图表等）。
- `terminal_read` / `terminal_write`：终端读写操作（带 HITL 审批）。
- `search_documents` / `search_task_experience`：RAG 检索（文档 / 历史经验）。

**自动加在工具结果末尾的 diff 与 transients**：所有"会改页面状态"的 MCP 浏览器工具（click/type/navigate/...）调用结束后，工具返回末尾会自动追加：
- `[diff] DOM 变化量: N` / `[diff] 页面无明显变化`
- `[diff] 最显著变化: <html>...</html>`
- `[transients] [...]`：动作期间出现的瞬时文本（toast / 错误提示 / loading）

由 `loggers/diff_middleware.py` 实现，省下 LLM "做动作 → 再 snapshot 验证" 的下一轮。

## API 快速说明

- `POST /chat`：发送消息并流式返回执行结果
- `GET /tools`：列出可用工具
- `POST /upload`：上传 PDF、DOC、DOCX、Markdown、TXT 等文档并写入向量库，响应里包含本次生成的 `total_parents` 和 `total_children`
- `POST /rag/search`：调试 RAG 检索，返回大块、小块和层级聚合结果，以及相关 chunk 明细

## 测试

```powershell
pytest
```

示例：

```powershell
pytest test/test_context_compression.py -v -s
```

## 常见问题

- `ModuleNotFoundError`：检查是否激活虚拟环境并已安装依赖。
- 数据库报错 `extension "vector" does not exist`：在目标数据库执行 `CREATE EXTENSION IF NOT EXISTS vector;`。
- MCP 连接失败 / `npx` 找不到：确认 Node.js 已安装且 `npx @playwright/mcp@latest` 可正常运行。
- 浏览器未启动 / CDP 连接被拒绝：检查 `.env` 中 `BROWSER_PATH` 和 `DEBUGGING_PORT` 配置，确保浏览器以 `--remote-debugging-port` 启动。

## 文档分工

- `README.md`：面向人类开发者与使用者，负责上手与运行说明。
- `AGENT.md`：面向 AI coding agent，负责修改约束、边界和维护规则。
