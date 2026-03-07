# NexusSurf

智能浏览器自动化代理系统，基于 LLM 执行网页操作、上下文压缩和知识检索。

## 项目简介

NexusSurf 通过 Playwright + LangChain/LangGraph 组合，实现可交互的 Web 自动化 Agent。

- 支持自然语言驱动浏览器操作。
- 支持文档上传并进入 RAG 检索链路。
- 支持 CLI 模式和 FastAPI + 前端模式。

## 核心能力

- 浏览器自动化：页面导航、元素操作、信息提取。
- 模型推理编排：工具调用、多轮会话、可中断审批。
- 上下文管理：长上下文压缩、归档和重放辅助。
- 数据存储与检索：PostgreSQL + PGVector。

## 运行前准备

### 1. 环境要求

- Python 3.10+
- PostgreSQL 14+
- 已启用 `vector` 扩展（PGVector）

### 2. 安装依赖

当前仓库未提供 `requirements.txt` / `pyproject.toml`，可先安装最小依赖集：

```powershell
pip install langchain langgraph langchain-community fastapi uvicorn pydantic playwright psycopg2-binary pgvector
python -m playwright install
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
- Playwright 相关报错：重新执行 `python -m playwright install`。

## 文档分工

- `README.md`：面向人类开发者与使用者，负责上手与运行说明。
- `AGENT.md`：面向 AI coding agent，负责修改约束、边界和维护规则。
