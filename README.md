# NexusSurf

面向复杂网页任务的智能浏览器代理框架，基于 LLM + Playwright MCP 执行浏览器操作，并结合上下文压缩、人工审批、文档检索与任务经验复用能力。

## 项目简介

NexusSurf 通过 **@playwright/mcp** + LangChain/LangGraph 组合，实现可交互的 Web Agent。它不是只执行固定脚本的浏览器自动化工具，而是把浏览器操作、视觉分析、终端读写、文档检索和经验检索放入统一的 Agent 工具链中，由模型按任务目标动态编排。浏览器操作通过 MCP (Model Context Protocol) 以 snapshot-ref 模式驱动，并使用持久会话保持跨工具调用的页面状态。

- 支持自然语言驱动浏览器与辅助工具协同执行。
- 支持文档上传索引、文档检索和任务经验复用。
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

## API 快速说明

- `POST /chat`：发送消息并流式返回执行结果
- `GET /tools`：列出可用工具
- `POST /upload`：上传文档并写入向量库

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
