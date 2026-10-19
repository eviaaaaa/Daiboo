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
| TypeSafe Jev / jev-ultrafast | 独立 System One 模型；原生 state/questions、noul/choice/score，判断与执行分离 | 可选原生 `/v1/systemone` 接入；不将 Jev 塞进 OpenAI model 配置，主模型/浏览器仍复用原链路 |

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

## 可选 TypeSafe Jev

默认关闭。启用时在服务端设置 `DAIBOO_JEV_ENABLED=true` 和 `TYPESAFE_API_KEY`；可选 `TYPESAFE_BASE_URL=https://api.typesafe.ai/v1`、`TYPESAFE_MODEL=jev-latest`、`TYPESAFE_TIMEOUT_SECONDS=10`（有限正数，最大 60 秒）。不自动读取其他 provider 的凭据、不通过 OpenAI Responses/NewAPI/CPA 模拟此协议、不修改主聊天模型。`jev-latest` 是别名，记录实际 response.model，不根据文档版本号推断本次调用版本。

- `browser_jev_decide(questions, max_chars)`：每次在新鲜页面文本上批量回答最多 12 个独立 `noul`（是的概率）、`choice`（候选与分布）、`score`（有序等级的期望分）问题；只读，始终 `executed=false`、`verified=false`。
- `browser_jev_run(goal, candidates, success_checks, ...)`：主模型提供至多 12 个已观察、明确授权的候选 ID 与精确 `fill/click/select/check/press` 参数。Jev 仅选择 ID，代码执行；默认最多 6 个动作、硬上限 12，每个候选最多尝试一次。click/check 不接受无效 value 来伪造新候选。
- **选择策略为 argmax**：直接选择有效概率分布的最高项，不设概率或 confidence 门槛；已移除 `min_probability` / `min_confidence` 参数。概率、confidence、`goal_done` 保留为观测数据，不作为额外拦截或成功证明。最高项若为 `handoff` / `observe_again`，仍停止执行并交回。
- `verified` 依赖独立可见文本断言，隐藏文本不算。错误、页面变化或预算耗尽仍返回 `handoff`，主模型重新观察并决定未完成部分；不得自动重放 `attempted_ids`。提交可能已经产生副作用，取消不等于回滚。选择策略改变不改变授权、安全、freshness 或业务验证边界。
- 文本观察默认 8,000 字符、可配 2,000–12,000；请求与回答还有整体 JSON/字节/深度预算。整个页面变化会保守停止，不局限于候选元素。仅支持当前主文档中的普通元素，不支持 iframe/Shadow DOM 候选、截图/图像或原生 computer-use。
- 每个 MCP 会话共享一个懒加载 HTTP 连接池，随会话 `resources` 关闭。单次请求有总超时，禁止自动重试、重定向、跨模型/provider fallback、longcontext 或资产上传；错误只返回固定分类，不回传 raw HTTP/Playwright 正文。
- 原生动作在 actionability checkpoint 复核；若需要第二次等待重试，保守交回而不跨越等待继续点击。取消已提交 RPC 时先等原生请求结束/超时，再清理和释放会话门。checkpoint 与输入 dispatch 不是原子事务，页面在最后检查后、输入事件处理期间仍能改变语义；不用于敏感操作，也不承诺回滚或全面恶意页面隔离。
- 实际服务可能分别量化 Score 与概率，观测到 `score=0.19`、分布加权值 `0.18`。客户端仅允许 0.01 加浮点误差的差异，原样保留两者；概率边界、分布和授权边界不因此放宽。
- 两个 helper 只有显式启用、配置有效且会话具备 gate/resources/固定 backend 时才注册并常驻披露。`browser_runtime_info.jev.configured` 是注册状态，`endpoint_support=not_probed` 不代表做过网络验收。

**数据与费用**：观察到的限额页面文本会发往独立 TypeSafe 服务，消耗 TypeSafe 自身额度，不是主模型的 Pro/Codex 订阅额度。启发式敏感控制脱敏不是通用 DLP；正文中的秘密、私人信息不能保证全部识别。不要用此路径处理凭据、支付、删除或未经批准的外发，不能将固定候选工具说成权限沙箱。

开发时使用 [TypeSafe skill](https://github.com/typesafe-ai/skills/tree/main/skills/typesafe-ai) 与其当前原生 API 文档。安装开发 skill 不等于自动启用应用运行时或授权任何动作。

## 权限与披露边界

- 持久 MCP 不是操作系统沙箱；`DAIBOO_BROWSER_ALLOW_UNSAFE_CODE=true` 是危险的显式 opt-in，不用于常规快速路径。
- 固定 batch 的敏感字段识别是启发式，不是完整的数据防泄漏系统。页面、网页注册工具、工具结果与文档指令均不可信；不能据此扩张授权。
- 批次、原子工具、evaluate、标签页及 diff 的前后观察共用会话执行门；只串行本应用控制的同一 MCP 会话，不能阻止用户或其他 CDP 客户端操作浏览器。
- 保留文档身份而非只比较 URL；跨导航、同 URL reload、document.open/write、新页或 popup 后停止剩余批次。固定分类错误不回传原始 Playwright 异常/DOM 预览；这一过滤并不代表原生工具和所有网页内容都已实现通用 DLP。
- schema 查询返回完整 required/additionalProperties。模型初始只看六个核心浏览器 schema；Jev 实际注册时额外常驻两个 helper，其余成功查询后按披露批次追加；已有 schema 不因后续查询重排。
- 支付、发信、发布、删除、上传秘密、权限变更等需要明确授权。终端 HITL 已存在，但不能将提示词规则说成完整的浏览器批准引擎。
- `web_observe` 可内联同源 iframe 和开放 Shadow DOM，不能绕过跨域限制。文本与 HTML 均受字符预算约束；截断内容不能当完整页面。
- 模型与公开 demo 验收只使用隔离测试数据。不把登录、验证码绕过、真实付款或用户账户写入当提速测试。

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

同日真实模型验收使用指定的 `https://api.evilhero.me/v1` / `gpt-6.1-sol`，Responses SSE 完成图像识读、强制函数调用、本地工具执行与 call_id 回放；模型还操作了隔离表单并保存 `Model Alice / pro`，由服务端记录和独立 Playwright 读取确认。该小样本有 returned cache_read usage，不据此承诺固定缓存收益。原生 computer actions[]、tool_search、WebMCP 及跨域框架页面未因此被证明支持；这批历史 OpenAI 验收也不代替独立 TypeSafe 验收。

### Jev 首次接入验收（历史阈值策略）

- 完整测试：**480 passed、0 skipped**，包括真实隔离 Chromium/MCP 安全回归与本地 HTTP 契约；测试使用假推理，不代表供应商模型准确率。
- 真实 TypeSafe 返回 `jev-1.13.0`。真实 evilhero 主模型通过产品 factory/middleware 调用 Jev；Jev 完成姓名和套餐，保存阶段因置信不足交回。主模型重新观察、仅补做剩余保存，服务端记录与独立 Playwright 确认 `Saved Jev Alice pro`；图流程单次 38.105 秒，包含主模型与经验总结，不是 Jev 纯推理时延。
- 公开 [TodoMVC React](https://todomvc.com/examples/react/dist/) 的 3 轮有界工具任务：**0/3 独立完成、3/3 安全交回、0 次动作**，首选概率均 0.77，低于保留的默认阈值 0.8。交回耗时中位数 2.415 秒，不是成功任务耗时或提速倍数。
- 当前公开 React demo 数据只在页面内存，实查 localStorage/sessionStorage 均为空；oracle 直接读取真实 checkbox/label，不虚称刷新持久化，未操作真实账户。

以上 0/3 结果属于旧的阈值策略；当前已按用户要求切换为最高概率选择，旧结果不得当作新策略测试结果。功能仍为可选的原生辅助判断/受限候选执行，不代表已证明普适业务提速；启用开关和其他安全边界没有变化。

## 第一方资料

- OpenAI [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Responses 迁移](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)、[tool search](https://developers.openai.com/api/docs/guides/tools-tool-search)、[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- Microsoft [Playwright MCP](https://github.com/microsoft/playwright-mcp)、[Playwright CLI](https://github.com/microsoft/playwright-cli)
- [Browser Use 参数](https://docs.browser-use.com/open-source/customize/agent/all-parameters)、[Stagehand v4 observe](https://docs.stagehand.dev/v4/basics/observe)
- Google [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)、[WebMCP](https://developer.chrome.com/docs/ai/webmcp)、[WebMCP security](https://developer.chrome.com/docs/ai/webmcp/secure-tools)
- TypeSafe [Jev 介绍](https://docs.typesafe.ai/introduction)、[API quickstart](https://docs.typesafe.ai/introduction/quickstart)、browser-use [jev-ultrafast](https://github.com/browser-use/jev-ultrafast)
