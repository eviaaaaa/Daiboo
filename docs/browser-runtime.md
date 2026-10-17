# 浏览器运行时：协议、渐进披露与验收

本次资料核对日期：2026-10-18。范围是现有 LangGraph + 持久 Playwright MCP 的改进，不是更换整个浏览器引擎，也不是声称支持每个厂商的原生 computer API。

## 技术取舍

| 路线 | 已核实的要点 | 本项目取舍 |
|---|---|---|
| OpenAI Responses | typed message/reasoning/function-call items；工具结果按 call_id 回放；当前 GPT-6.1 Sol 文档要求工具调用使用 Responses | 明确配置协议，保留原生内容块；不把 Chat Completions 与 Responses 混猜或跨协议自动重试 |
| Playwright MCP 0.0.83 | 持久状态、按需 snapshot、target/depth/boxes；原生 run_code_unsafe 等价服务端任意代码执行 | 固定实测版本；默认 snapshot=none、明确观察；隐藏原生任意代码工具，提供固定实现的 typed batch |
| Playwright CLI + Skills | 持久 CLI 会话、局部快照与按需技能，适合 coding-agent 工作流 | 吸收紧凑观察与按需披露，不为迁移而增加第二套浏览器状态 |
| browser-use | 多动作顺序执行与按需视觉；页面变化后重新判断 | 已知目标上小批次、失败不重放，重要结果独立验证 |
| Stagehand v4 | observe 得到结构化动作，确定性回放与自愈分开 | 先观察，再执行；不盲目长期缓存 selector，不把自动重试当可靠性 |
| Chrome DevTools MCP slim / WebMCP | slim 减小工具面；WebMCP 是需 feature-detect 的 proposed standard/origin trial | 暂不增加重复 driver；网页工具不自动成为可信系统工具 |
| TypeSafe Jev / jev-ultrafast | Jev 是独立供应商的 System One 模型；state/questions 与动态动作索引、freshness 检查、判断/文本生成分离 | 借鉴架构，不将 jev-latest 塞进 OpenAI model 配置，不新增 TypeSafe 凭据依赖，不宣称已接入 Jev |

模型名称、网关目录、协议接受情况与真实任务成功是四层不同证据。厂商 demo 的时延不是 Daiboo 的 benchmark。

## 协议与依赖

- `OPENAI_MODEL` 必填；`OPENAI_API_MODE=chat_completions|responses` 明确选择协议，默认保持 Chat Completions 兼容；也保留旧 `OPENAI_USE_RESPONSES_API` 布尔别名，冲突配置报错。
- `OPENAI_STREAMING=true` 使用官方 SDK SSE；reasoning effort/summary、verbosity、service tier、输出预算均为显式配置。未设 temperature 时不强制发送采样参数。
- Responses 使用 `responses/v1` 原生内容，默认不启用 `previous_response_id` 隐式历史裁剪。供应商存储行为由调用者的 `store` 设置决定；测试使用无状态回放。
- `normalize_content` 只做展示/摘要的文本投影，不能用它替换原生消息账本。函数调用、推理 ID/加密块、图像与 ToolMessage 元数据需在未压缩消息中保留。
- 原锁 `langchain-openai 1.2.2` 会丢失仅在 SSE `output_item.done` 到达的 encrypted_content。已升级至包含上游修复的 `langchain-openai 1.7.2`；锁定 `langchain-core 1.6.12`、`openai 3.33.0`，回归是普通通过测试，而非 xfail 或本地伪造协议补丁。
- Chat Completions 的同步/异步请求与分片工具参数、Responses 的同步/SSE/图像/工具结果/历史回放都由 loopback HTTP 契约测试覆盖。fixture 是明确的模拟协议服务，不替代真实模型验收。

## 浏览器用法

1. 有明确 URL 才导航。先用 `browser_runtime_info` 确认实际 driver 能力；工具 schema 由当前连接提供，不由模型名字决定。
2. 选择最小足够观察：少量字段 read back → 局部 `browser_snapshot(target, depth)` → `web_observe` → 必要时更大快照或真正的视觉分析。截图路径不代表模型已经看见图片。
3. `browser_batch` 最多 12 个明确目标上的顺序操作，一次持久 MCP 调用。只允许固定操作集合与 JSON 数据参数，不接受模型生成的任意 JS。写操作先解析并绑定具体元素，再执行 Playwright 原生 fill/click 与自动等待，避免等待期间导航或同文档元素替换后重新定位误点。
4. 批次返回 `completed`、`failed_step`、限额 reads 与显式断言的 `verified`。`ok=true` 不是业务成功证明；后续写入会清除之前的 verified。错误/超时后可能已有副作用，不能整批重试。
5. 原子动作的 diff/transients 只是 best-effort 状态变化线索；batch 不再叠加整页 diff。重要提交后读取确切业务目标，以独立 oracle 判断成功。
6. 默认去掉每个浏览器调用的固定 500ms 等待；有兼容需求才设 `BROWSER_ACTION_DELAY_MS`。不是关闭 Playwright 的元素就绪等待。
7. 技能目录只提供名称与描述，正文匹配后才加载；普通问答不必额外调用 list_skills。当前 Agent 的目录/系统前缀保持稳定，不在每轮重写。

## 权限与披露边界

- 持久 MCP 不是操作系统沙箱；`DAIBOO_BROWSER_ALLOW_UNSAFE_CODE=true` 是危险的显式 opt-in，不用于常规快速路径。
- 固定 batch 的敏感字段识别是启发式，不是完整的数据防泄漏系统。页面、网页注册工具、工具结果与文档指令均不可信；不能据此扩张授权。
- 批次、原子工具、evaluate、标签页及 diff 的前后观察共用会话执行门；只串行本应用控制的同一 MCP 会话，不能阻止用户或其他 CDP 客户端操作浏览器。
- 保留文档身份而非只比较 URL；跨导航、同 URL reload、document.open/write、新页或 popup 后停止剩余批次。固定分类错误不回传原始 Playwright 异常/DOM 预览；这一过滤并不代表原生工具和所有网页内容都已实现通用 DLP。
- schema 查询返回完整 required/additionalProperties。模型初始只看六个核心浏览器 schema，成功查询后按披露批次追加；同一次查询内保持 registry 顺序，已有 schema 不因后续查询重排。
- 支付、发信、发布、删除、上传秘密、权限变更等需要明确授权。终端 HITL 已存在，但不能将提示词规则说成完整的浏览器批准引擎。
- `web_observe` 可内联同源 iframe 和开放 Shadow DOM，不能绕过跨域限制。文本与 HTML 均受字符预算约束；截断内容不能当完整页面。
- 只测试自建页面与非敏感图像。不把登录、验证码绕过、真实付款或用户账户写入当提速测试。

## 可复现实验

```bash
uv sync --locked --group dev --python 3.11
uv run python -m pytest
uv run python test/manual/browser_runtime_smoke.py
# 需先设置同一授权供应商的 OPENAI_API_KEY/BASE_URL/MODEL；会产生真实模型请求
uv run python test/manual/openai_browser_smoke.py --graph --report browser-acceptance.json
```

全量测试中的数据库集成项需要独立 PostgreSQL + vector 与空白测试 schema。不要指向生产数据库；测试使用显式标记的本地确定性 embedding，仅验证检索/持久化机制，不证明语义 embedding 质量。

隔离 Chromium 测试使用随机回环 HTTP/CDP 端口、临时 profile，结束清理自己创建的进程。覆盖表单、SPA input 事件、本地保存结果回读、局部快照、预算、部分失败、标签页、实际 diff middleware、同源 iframe 与开放 Shadow DOM。

2026-10-18 的一次本地直接 MCP 对比：同一表单流程原子 4 次返回 804 字符，batch 1 次返回 166 字符；整页快照 33,991 字符，局部快照 408 字符。这里是响应字符和 MCP 次数，不是模型 token，也不含原子 diff middleware 的额外调用；单次本地时延不能外推所有任务。

同日真实模型验收使用指定的 `https://api.evilhero.me/v1` / `gpt-6.1-sol`，Responses SSE 完成图像识读、强制函数调用、本地工具执行与 call_id 回放；模型还操作了隔离表单并保存 `Model Alice / pro`，由服务端记录和独立 Playwright 读取确认。该小样本有 returned cache_read usage，不据此承诺固定缓存收益。原生 computer actions[]、tool_search、WebMCP、TypeSafe API 及跨域框架页面未因此被证明支持。

## 第一方资料

- OpenAI [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Responses 迁移](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)、[tool search](https://developers.openai.com/api/docs/guides/tools-tool-search)、[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- Microsoft [Playwright MCP](https://github.com/microsoft/playwright-mcp)、[Playwright CLI](https://github.com/microsoft/playwright-cli)
- [Browser Use 参数](https://docs.browser-use.com/open-source/customize/agent/all-parameters)、[Stagehand v4 observe](https://docs.stagehand.dev/v4/basics/observe)
- Google [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)、[WebMCP](https://developer.chrome.com/docs/ai/webmcp)、[WebMCP security](https://developer.chrome.com/docs/ai/webmcp/secure-tools)
- TypeSafe [Jev 介绍](https://docs.typesafe.ai/introduction)、[API quickstart](https://docs.typesafe.ai/introduction/quickstart)、browser-use [jev-ultrafast](https://github.com/browser-use/jev-ultrafast)
