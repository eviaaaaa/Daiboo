# NexusSurf

智能浏览器自动化代理系统，基于大语言模型（LLM）的自动化操作。

## 快速浏览

NexusSurf 是一个基于 LLM 的浏览器自动化 Agent。它能模拟人类用户行为，通过 OODA（观察-调整-决策-行动）循环，在 Web 环境中自主执行复杂的自然语言指令（如自动查阅资料、操作页面等）。

## 核心组件与特长

- **自动化引擎**: 基于 Playwright 异步模式，支持稳定高效的页面操作。
- **智能大脑**: LangChain Agent 框架进行核心逻辑编排，提供自主推理能力。
- **长效记忆库**: 基于 PostgreSQL + PGVector 扩展实现 RAG 架构的记忆增强，支持混合搜索。
- **多模型支持**: 内置对接 Qwen Embeddings、Tongyi Qwen (如 `qwen3-vl-plus`)，并支持 Gemini/GPT-4V 的视觉识别增强。

## 启动指南

### 1. 运行环境
- Python 3.10 或更高版本
- PostgreSQL 14+，并安装 PGVector 扩展

### 2. 初始化配置
首先复制环境变量示例文件：
```bash
cp .env.example .env
```
在 `.env` 中填写正确的 API KEY 及数据库连接信息等。

### 3. 开始使用
启动 API 接口服务：
```bash
python run_server.py
```
或直接进入本地终端对话模式：
```bash
python main.py
```
