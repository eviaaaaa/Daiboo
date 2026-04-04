# Agent 压缩机制梳理

本文基于当前仓库实现整理，重点覆盖两类“压缩”能力：

1. 运行期上下文压缩
2. 对话结束后的执行轨迹摘要压缩

核心实现位置：

- `context/context_manager.py`
- `utils/agent_factory.py`
- `loggers/experience_middleware.py`
- `loggers/experience_summarizer.py`
- `prompt/experience_prompt.py`
- `test/test_context_compression.py`

## 1. 总览

当前 Agent 的“压缩”不是单一策略，而是两条链路：

- 上下文压缩链路：在每次模型调用前执行，目标是控制 prompt 体积，避免上下文过长。
- 经验摘要链路：在每轮对话结束后异步执行，目标是把完整执行轨迹压缩成可复用经验，存入知识库。

其中，真正影响模型输入上下文的是第一条；第二条更像“执行日志的结构化摘要”。

## 2. 压缩链路挂载位置

Agent 在 `utils/agent_factory.py` 中组装，中间件顺序如下：

1. `ContextManagerMiddleware`
2. `HumanInTheLoopMiddleware`
3. `log_agent_start`
4. `log_playwright_tool_call`
5. `log_agent_response`
6. `log_response_to_database`
7. `log_experience`
8. `delay_tool_call`

这意味着：

- 上下文压缩发生在模型真正推理之前。
- 经验摘要发生在本轮 Agent 执行结束之后。

## 3. 运行期上下文压缩

### 3.1 入口

`ContextManagerMiddleware.before_model()` 是主入口。每次模型调用前，它会按固定顺序执行四步：

1. 给消息补齐 `id`
2. 单条超长消息卸载
3. 旧 `ToolMessage` 压缩
4. 如总量仍超限，则归档旧轮次

如果前 3 步已经足够把上下文压到阈值以内，则只返回改写后的消息列表；如果仍超限，则执行整段归档，并通过 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 重建消息上下文。

### 3.2 默认配置

`ContextManagerMiddleware` 的默认参数如下：

- `recent_tool_messages_to_keep = 3`
- `tool_preview_chars = 200`
- `short_content_chars = 1000`
- `single_msg_max_chars = 120000`
- `max_total_chars = 200000`
- `max_token_ratio = 0.8`
- `single_msg_ratio = 0.8`

token 上限不是写死值，而是优先读取模型 `profile["max_input_tokens"]`，取其 80%：

- `max_context_tokens = max_input_tokens * 0.8`
- `single_msg_limit = max_input_tokens * 0.8`

如果模型没有提供 `max_input_tokens`，则默认按 `128000` 计算。

### 3.3 单条超长消息卸载

实现函数：`_offload_heavy_messages()`

处理对象：

- `HumanMessage`
- `ToolMessage`

触发条件满足任意一个即可：

- 字符数超过 `single_msg_max_chars`
- 估算 token 数超过 `single_msg_limit`

当前 token 估算方式不是 tokenizer 精算，而是经验近似：

- `estimated_tokens = content_len // 2`

也就是默认按“约 2 个字符折算 1 个 token”处理。

触发后会做三件事：

1. 将完整内容写入本地文件
2. 保留一段 preview
3. 用一个系统提示风格的新消息替换原消息内容

替换后的内容会明确写出：

- 原始字符数
- 估算 token 数
- 触发原因是“字符超限”还是“token 超限”
- 完整文件路径
- 预览内容
- 提示可使用 `terminal_read` 读取原文

注意点：

- `ToolMessage` 的 `tool_call_id`、`name`、`id` 会保留。
- `HumanMessage` 的 `id` 也会保留。
- 这是“卸载到文件 + 消息替换”，不是把消息直接删除。

### 3.4 旧 ToolMessage 压缩

实现函数：`_compress_old_tool_messages()`

目标：

- 保留最近若干条工具结果原文
- 将更早的长工具结果压缩成“文件路径 + preview”

处理规则：

- 找出所有 `ToolMessage`
- 最近 `recent_tool_messages_to_keep` 条完整保留
- 更早的 `ToolMessage` 只有在内容长度大于 `short_content_chars` 时才压缩

压缩方式与单条消息卸载类似：

1. 完整内容写入本地文件
2. 生成预览
3. 用说明性文本替换原始 `ToolMessage.content`

当前默认行为可理解为：

- 最近 3 条工具消息保留原文
- 更早的长工具消息折叠成摘要引用
- 较短工具消息即使较旧，也不压缩

这样做的目的，是减少历史工具输出对上下文窗口的占用，同时保留最近操作链路的可追踪性。

### 3.5 总上下文超限后的归档

实现函数：`_archive_old_rounds()`

在完成“单消息卸载”和“旧工具消息压缩”后，系统会重新计算：

- 当前总 token
- 当前总字符数

只有当二者都未超限时，才直接结束压缩流程。只要总 token 或总字符数仍然超限，就会进入归档逻辑。

总字符数统计由 `_count_total_chars()` 负责：

- 字符串内容直接计长度
- 多模态列表内容只累计其中的 `text`

#### 归档策略 A：最近轮次本身已经太大

条件：

- “最后一条 `HumanMessage` 及其之后的所有消息”加上 `SystemMessage` 后，token 仍超过 `max_context_tokens`

动作：

- 归档最后一条 `HumanMessage` 之前的所有聊天消息
- 保留最后一轮及其后续消息

#### 归档策略 B：最近轮次可保留，但历史过长

条件：

- 最近轮次未单独超出 token 限制

动作：

- 从第一条 `HumanMessage` 开始，到最后一条 `HumanMessage` 之前的消息全部归档
- 最后一轮消息保留

### 3.6 归档产物与消息重写方式

归档不会把摘要单独插成一条新的 `HumanMessage`，而是：

1. 先把被归档消息保存到本地文件
2. 生成一个归档通知文本
3. 将通知文本嵌入“保留区中的第一条 `HumanMessage`”前面

这样做的原因已经写在代码里：避免出现连续两条 `HumanMessage`，从而触发上游接口的角色交替错误。

归档通知文本包含：

- 归档原因
- 归档文件路径
- 归档内容预览
- 提示可用 `terminal_read` 查看全文

最终返回的消息列表结构是：

- 所有 `SystemMessage`
- 改写后的保留消息

如果发生了整段归档，`before_model()` 会返回：

- `RemoveMessage(id=REMOVE_ALL_MESSAGES)`
- 新的最终消息列表

表示用新上下文整体替换旧上下文。

### 3.7 文件落盘位置

所有被卸载或归档的内容都写入 `file_store_path`。

默认路径为：

- `storage/heavy_messages/`

文件名前缀包括：

- `msg_content_...txt`：单条超长消息卸载
- `toolmsg_content_...txt`：旧工具消息压缩
- `archived_messages_...txt`：历史消息归档

### 3.8 当前实现特点

优点：

- 不直接丢失超长内容，完整原文仍可通过文件回读
- 压缩顺序清晰，优先保留最近轮次和最近工具结果
- 同时使用字符阈值和 token 阈值，避免单一估算失效

局限：

- 没有使用真实 tokenizer，token 估算较粗糙
- 归档摘要不是 LLM 语义摘要，主要是“文件引用 + 预览”
- 归档文件保存在本地文件系统，依赖后续 `terminal_read` 才能恢复细节
- `_archive_and_summarize()` 目前存在，但当前主流程未使用

## 4. 对话后的执行轨迹摘要压缩

这部分不参与当前轮 prompt 控制，但属于另一种“压缩”。

### 4.1 触发方式

实现入口：`loggers/experience_middleware.py`

`log_experience` 使用 `@after_agent` 挂载，在每轮对话结束后：

1. 读取当前 `state`
2. 用 `asyncio.ensure_future()` 异步启动总结任务
3. 不阻塞主流程返回

所以它是后台异步执行的。

### 4.2 摘要对象

实现类：`ExperienceSummarizer`

它会从 `state` 中抽取：

- `session_id`
- `turn_number`
- 全量 `messages`
- 最后一条用户问题
- AI 的工具调用记录
- 最终回答

然后把完整 trace 序列化成适合 LLM 处理的摘要文本。

### 4.3 轨迹压缩方式

实现函数：`prompt/experience_prompt.py -> format_trace_for_summary()`

压缩规则：

- 按消息顺序生成“步骤 1 / 步骤 2 / ...”
- 对 AI 消息额外列出 `tool_calls`
- 单条内容超过 500 字符时直接截断
- 总摘要长度超过 `15000` 字符时停止，并附加“后续步骤已省略”

这一步相当于把完整执行链压缩成一个结构化 trace summary，再交给 LLM 判断是否值得沉淀为经验。

### 4.4 LLM 经验总结

`ExperienceSummarizer.summarize_from_state()` 会把以下信息拼成 Prompt：

- 用户任务
- 使用过的工具
- 最终回答
- 轨迹摘要

随后调用模型生成 JSON，判断：

- `is_valuable`
- `task_type`
- `success`
- `experience`
- `website_domain`

如果 `is_valuable = true`，会继续：

1. 为经验文本生成 embedding
2. 写入 `Experience` 表

### 4.5 与上下文压缩的关系

这一套机制的目标不是减少“当前对话窗口”的 token，而是把执行过程压缩成可复用知识。

可以把两者理解为：

- `ContextManagerMiddleware`：面向“模型还能继续聊下去”
- `ExperienceSummarizer`：面向“这轮执行能否沉淀经验”

## 5. 测试覆盖到的行为

`test/test_context_compression.py` 当前覆盖了以下关键行为：

- 旧 `ToolMessage` 压缩，且最近若干条保留原文
- 短 `ToolMessage` 不压缩
- 压缩后仍保留 `tool_call_id` 和 `name`
- 单条消息在“字符超限”时触发卸载
- 单条消息在“token 超限”时触发卸载
- 总字符超限时触发历史归档
- 小消息场景下不触发压缩
- 压缩后消息顺序正确，避免连续 `HumanMessage`

这些测试说明当前压缩机制已经明确围绕以下目标设计：

- 优先保留最近语义上下文
- 尽量不丢原始信息
- 保证消息结构仍符合 Agent 对话要求

## 6. 一句话总结

当前仓库的 Agent 压缩机制，本质上是“文件卸载 + 预览替换 + 历史归档 + 异步经验摘要”四层组合：

- 模型调用前，先把超长消息和旧工具输出折叠到文件里
- 若总上下文仍然过长，再归档旧轮次并重写保留区消息
- 对话结束后，再把整轮执行轨迹压缩成结构化摘要，用于沉淀经验知识

这是一套偏工程化、保守型的压缩方案，优先保证可恢复性和上下文稳定，而不是追求激进的语义摘要压缩。
