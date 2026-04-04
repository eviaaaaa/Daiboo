# RAG 架构与文档切块设计

本文档整合并替代旧文档 `docs/current_rag_architecture.md`。

旧文档的主体内容已经迁移到本文：

- `2. 当前 RAG 总览`
- `3. 文档 RAG`
- `4. 经验 RAG`
- `5. AgentTrace RAG`

新增内容主要包括：

- 文档 RAG 的大小块改造
- 当前文档解析对图片、扫描件、表格的处理现状
- 本次改造后的测试与兼容策略

## 1. 结论先看

当前项目不是单一 RAG，而是三套相互独立的数据链路：

1. `rag_documents`
   用于文档片段检索，已经接入主流程，可被 Agent 通过 `search_documents` 工具主动调用。
2. `experiences`
   用于历史任务经验检索，已经接入主流程，可被 Agent 通过 `search_task_experience` 工具主动调用。
3. `agent_traces`
   用于保存完整执行链路，代码里有检索模块，但当前主流程只负责“记录”，没有真正接入 Agent 的可用工具或 Prompt 注入链路。

如果只看“现在真正影响 Agent 行为的 RAG”，核心仍然是：

- 文档 RAG
- 经验 RAG

`AgentTrace` 更像是“为以后做案例检索/Few-shot 准备的数据层”，当前不是主要生效链路。

## 2. 当前 RAG 总览

三类数据的检索底座基本一致，统一走 [`rag/hybrid_search_service.py`](C:\my\python\langchain\BrowerController\rag\hybrid_search_service.py)：

- 向量模型：[`utils/qwen_embeddings.py`](C:\my\python\langchain\BrowerController\utils\qwen_embeddings.py)
  - 使用 DashScope `text-embedding-v1`
  - 维度是 `1536`
- 关键词检索：
  - 用 `jieba` 分词
  - 生成 PostgreSQL `to_tsquery('simple', ...)`
  - 依赖统一的 `SearchableMixin` 事件监听器自动拦截和生成 `fts_vector`
- 融合方式：
  - 向量召回
  - 关键词召回
  - RRF 融合
- 重排序：
  - 默认开启
  - 使用 `BAAI/bge-reranker-base`

现在 `HybridSearchService.search(...)` 也已经支持结构化过滤参数，因此经验检索的 `task_type` / `website_domain` 过滤不再和底层接口冲突。

## 3. 文档 RAG

### 3.1 当前主链路

文档 RAG 的入口是 [`api.py`](C:\my\python\langchain\BrowerController\api.py) 的 `POST /upload`：

1. 上传文件保存到 `temp_uploads/`
2. 调用 [`rag/document_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\document_rag_pgvector.py) 的 `save_document_to_pgvector`
3. 文档解析后切块、生成 embedding、写入 `rag_documents`
4. Agent 在执行中通过 [`tools/rag_tools.py`](C:\my\python\langchain\BrowerController\tools\rag_tools.py) 的 `search_documents` 查询

工具注册点在 [`utils/agent_factory.py`](C:\my\python\langchain\BrowerController\utils\agent_factory.py)。

### 3.2 大小块改造后的数据结构

本次文档 RAG 已从“单层扁平块”改为“父块 + 子块”结构。

表仍然是 [`entity/rag_document.py`](C:\my\python\langchain\BrowerController\entity\rag_document.py) 的 `rag_documents`，但新增了这些字段：

- `chunk_level`
  - `parent` / `child`
- `parent_id`
  - 子块指向父块
- `source_path`
  - 原始文件路径
- `source_name`
  - 原始文件名
- `chunk_index`
  - 当前层内的块序号
- `start_index`
  - 当前块在源文本中的起始偏移

保留的原字段包括：

- `content`
- `meta_data`
- `embedding`
- `fts_vector`

### 3.3 当前切块策略

切块逻辑在 [`rag/document_chunking.py`](C:\my\python\langchain\BrowerController\rag\document_chunking.py)。

当前配置：

- 父块：
  - `chunk_size = 1500`
  - `chunk_overlap = 200`
- 子块：
  - `chunk_size = 300`
  - `chunk_overlap = 50`

切块方式：

1. loader 先输出原始 `Document`
2. 先切成父块
3. 每个父块内部再切成子块
4. 父块和子块都写入数据库

设计目标：

- 子块负责召回精度
- 父块负责最终返回给模型时的上下文完整性

### 3.4 当前查询策略

查询逻辑也在 [`rag/document_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\document_rag_pgvector.py)：

1. 只检索 `chunk_level="child"` 的子块
2. 对命中的子块按 `parent_id` 聚合打分
3. 返回对应的父块

也就是说，当前文档 RAG 的真实行为是：

`子块召回 -> 父块回填 -> 父块返回给 Agent`

这比原先的“直接返回 500 字扁平块”更适合问答和长段上下文引用。

### 3.5 兼容策略

为了不让旧数据失效，当前实现保留了回退逻辑：

- 如果没命中新式子块
- 且表里存在旧的扁平块或旧父块数据

则退回原来的扁平检索方式。

所以这次改造不要求先清空历史数据才能运行。

### 3.6 当前文档解析对照片、扫描件、表格的处理

当前解析链路仍然是“loader 提纯文本”，没有做图片 OCR 或表格结构化增强。

loader 选择逻辑在 [`rag/document_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\document_rag_pgvector.py)：

- `.pdf` -> `PyPDFLoader`
- `.doc/.docx` -> `Docx2txtLoader`
- `.md` -> `UnstructuredMarkdownLoader`
- 其他 -> `TextLoader`

现状判断如下：

1. PDF 中的照片或扫描页
   当前没有 OCR 链路。
   如果 PDF 没有文本层，RAG 基本拿不到内容。

2. PDF 中的表格
   当前没有表格结构保真逻辑。
   即使能抽到文字，也更像线性文本，行列结构容易丢。

3. DOCX 中的图片
   当前没有图片抽取、OCR、caption 化逻辑。
   基本不会进入可检索文本。

4. DOCX 中的表格
   当前大概率只能拿到被拉平后的文本，不是结构化表格。

5. Markdown 中的表格
   纯文本痕迹通常能保留，但仍不是结构化表格检索。

所以当前大小块改造只提升了“文本类内容”的召回和返回质量，没有改变图片和表格的解析上限。

## 4. 经验 RAG

### 4.1 数据来源

经验 RAG 不是人工上传，而是每轮 Agent 结束后自动异步总结：

1. Agent 执行完成后，经过 [`loggers/experience_middleware.py`](C:\my\python\langchain\BrowerController\loggers\experience_middleware.py)
2. 异步启动 [`loggers/experience_summarizer.py`](C:\my\python\langchain\BrowerController\loggers\experience_summarizer.py)
3. Summarizer 从当前 `state` 中提取：
   - 用户问题
   - 工具调用
   - 最终回答
   - 执行轨迹摘要
4. 调用 LLM 按 [`prompt/experience_prompt.py`](C:\my\python\langchain\BrowerController\prompt\experience_prompt.py) 生成结构化经验
5. 对经验文本生成 embedding
6. 写入表 `experiences`

表结构见 [`entity/experience.py`](C:\my\python\langchain\BrowerController\entity\experience.py)。

### 4.2 查询入口

查询入口是 [`tools/rag_tools.py`](C:\my\python\langchain\BrowerController\tools\rag_tools.py) 的 `search_task_experience`。

内部调用 [`rag/experience_rag.py`](C:\my\python\langchain\BrowerController\rag\experience_rag.py) 的 `search_experience`，返回结果会格式化成 Markdown 文本再注入给模型。

### 4.3 当前状态判断

经验 RAG 已接入主流程，向量检索和过滤参数完全可工作。
得益于在 `entity/mixins.py` 的 `SearchableMixin` 处统一部署的全文检索分词监听器，此数据在写入时已经自动计算和配置 `fts_vector`，现在该类检索是名副其实的“向量搜索 + 全文关键词搜索 + RRF融合 + Rerank 重排序”的全量混合查证过程。

## 5. AgentTrace RAG

### 5.1 数据来源

每轮 Agent 执行结束后，[`loggers/screen_logger.py`](C:\my\python\langchain\BrowerController\loggers\screen_logger.py) 的 `log_response_to_database` 会异步把完整链路写入 `agent_traces`：

- `user_query`
- `full_trace`
- `final_answer`
- `tool_names`
- `token_usage`
- `execution_duration`
- `session_id`
- `turn_number`

表结构见 [`entity/agent_trace.py`](C:\my\python\langchain\BrowerController\entity\agent_trace.py)。

### 5.2 检索代码现状

仓库里有 [`rag/question_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\question_rag_pgvector.py)，说明这条线原本是按相似问题检索、历史执行链路召回来设计的。

### 5.3 存在意义及当前的局限

当前系统里，`AgentTrace` 这条线并不是“供直接联机检索”的数据，它被有意识地限制成了“历史离线审计审计与防污染日志集”。

1. 会自动清理高维噪音：通过 `loggers/screen_logger.py` 中新重定向并入库的 `save_agent_trace_to_pgvector` 方法，其能够主动避免 RAG 原文被再次吸纳的交叉污染情况。
2. 数据就位但暂无业务动作引出：通过基类监听器它仍会自动获得 `fts_vector` 检索底层保证，但为降低系统开销特意忽略了其语义特征（`query_embedding=None` 封存）。
3. 其工具包 `get_question_from_pgvector` 特意未向 Agent 的执行大纲下放。

总结来说，这套存储在 RAG 设计里是一个“结构与后处理完备且带有静默自我净化能力”的沉睡日志引擎层，当前绝不直接干扰大模型。

## 6. Agent 实际会用到哪些 RAG

Agent 的工具注册点在 [`utils/agent_factory.py`](C:\my\python\langchain\BrowerController\utils\agent_factory.py)。

当前挂进 Agent 的 RAG 工具只有两个：

- `search_documents`
- `search_task_experience`

所以从执行时是否真实使用的角度：

- 文档 RAG：会
- 经验 RAG：会
- AgentTrace RAG：不会

## 7. 当前 RAG 的真实工作流

### 7.1 文档知识流

`用户上传文档 -> loader 提纯文本 -> 父块切分 -> 子块切分 -> embedding -> 写入 rag_documents -> 检索子块 -> 返回父块`

### 7.2 经验知识流

`Agent 完成任务 -> 异步总结经验 -> embedding -> 写入 experiences -> 后续任务中调用 search_task_experience -> 返回经验文本给模型`

### 7.3 链路沉淀流

`Agent 完成任务 -> 完整轨迹写入 agent_traces`

这条链路目前主要用于记录，不是在线 RAG 主链路。

## 8. 测试与验证

本次大小块改造新增测试：

- [`test/test_hierarchical_rag.py`](C:\my\python\langchain\BrowerController\test\test_hierarchical_rag.py)

当前覆盖行为：

1. 长文本能切出多层父子块
2. 子块能正确携带父块关联元数据
3. 多个子块命中时，父块聚合排序正确
4. 旧式 `parent_id=None` 记录也能兼容聚合逻辑

本地已完成的验证：

- `pytest test/test_hierarchical_rag.py -q`
- `python -m compileall rag test entity tools loggers utils database api.py main.py`

## 9. 现阶段的准确描述

如果用一句话概括当前项目：

> 这是一个“完备混合查询文档 RAG + 经验沉淀 RAG”并跑的主流程规范，且对原始执行链路做过“去污染”严谨设计的健壮级 RAG 应用。

更具体一点：

- 文档 RAG 结构完好，使用层级打分的父子块特征，享有由统一数据库监听下钻获取的首选混查能力。
- 经验 RAG 的双路检索表现全面切合。
- AgentTrace RAG 具备健壮防提示污染清洗层，但为避免认知超载而刻意退回为主系统的一环孤立审计日志，不被大模型染指。
- 图片、扫描件、表格目前仍未进入专门的结构化解析链路。

## 10. 后续优先级建议

如果继续往下做，优先建议是：

1. 给文档解析增加表格抽取和表格摘要，让表格不再只以线性文本进入 RAG。
2. 给 PDF / DOCX 图片增加 OCR 或 caption 化，把扫描件和图片内容纳入可检索文本。
3. （视未来业务方向决定）明确 `AgentTrace` 未来是否要真的升格为系统的 Few-shot 案例库。如有必要可向该表赋予补充的 `query_embedding` 计算配置。

## 11. 相关代码入口

- 文档切块：[`rag/document_chunking.py`](C:\my\python\langchain\BrowerController\rag\document_chunking.py)
- 文档入库与查询：[`rag/document_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\document_rag_pgvector.py)
- 通用检索：[`rag/hybrid_search_service.py`](C:\my\python\langchain\BrowerController\rag\hybrid_search_service.py)
- 文档工具：[`tools/rag_tools.py`](C:\my\python\langchain\BrowerController\tools\rag_tools.py)
- Agent 工具注册：[`utils/agent_factory.py`](C:\my\python\langchain\BrowerController\utils\agent_factory.py)
- 经验总结：[`loggers/experience_summarizer.py`](C:\my\python\langchain\BrowerController\loggers\experience_summarizer.py)
- 链路记录：[`loggers/screen_logger.py`](C:\my\python\langchain\BrowerController\loggers\screen_logger.py)
- AgentTrace 检索：[`rag/question_rag_pgvector.py`](C:\my\python\langchain\BrowerController\rag\question_rag_pgvector.py)
